<#
.SYNOPSIS
    vocal-extractor 一键安装脚本（Windows / PowerShell 5.1+）

.DESCRIPTION
    自动完成：
      1. 检查 Python 版本
      2. 检测 NVIDIA 显卡与计算能力，选择匹配的 CUDA 版 PyTorch
      3. 创建虚拟环境
      4. 安装 PyTorch（先于依赖，避免重复下载 CPU 版）
      5. 安装 audio-separator 及依赖
      6. 修复各平台已知的依赖坑
      7. 验证环境，可选预下载分离模型

.PARAMETER Python
    指定 Python 解释器，默认使用 PATH 中的 python。

.PARAMETER Cpu
    强制使用 CPU 版 PyTorch（不装 CUDA）。

.PARAMETER Cuda
    指定 CUDA 大版本，如 118 / 124 / 126 / 128。不指定则自动检测。

.PARAMETER SkipModel
    安装完成后不预下载分离模型。

.PARAMETER Force
    删除已存在的 .venv 重新安装。

.EXAMPLE
    .\install.ps1
    自动检测硬件、安装、预下载模型

.EXAMPLE
    .\install.ps1 -Cpu
    无显卡环境

.NOTES
    网络较慢时可先运行 fetch-wheels.ps1 用 aria2c 多线程预下载依赖。
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$Cpu,
    [string]$Cuda,
    [switch]$SkipModel,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"

# ---------------------------------------------------------------- 终端输出

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "    [X]  $m" -ForegroundColor Red }

# ---------------------------------------------------------------- 环境检测

function Get-GpuProfile {
    <# 返回 @{ Name; ComputeCap; CudaTag }，无 NVIDIA 显卡时返回 $null #>
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) { return $null }

    try { $raw = & nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader 2>$null }
    catch { return $null }
    if (-not $raw) { return $null }

    $parts = ($raw | Select-Object -First 1) -split ','
    $name = $parts[0].Trim()
    $cap = $parts[1].Trim()

    if (-not $cap -or $cap -eq "[N/A]") {
        Write-Warn2 "无法读取计算能力（显卡驱动过旧？），按 CUDA 12.6 处理"
        $cap = "8.6"
    }

    $capNum = [double]$cap
    #   >= 12.0 Blackwell    必须 CUDA 12.8+
    #   >= 7.0  Turing+      CUDA 12.x 足够
    #   <  7.0  Pascal 及更老 CUDA 11.8
    if     ($capNum -ge 12.0) { $tag = "cu128" }
    elseif ($capNum -ge 7.0)  { $tag = "cu126" }
    else                      { $tag = "cu118" }

    return @{ Name = $name; ComputeCap = $cap; CudaTag = $tag }
}

function Get-PyTorchVersion {
    <# 查询指定 CUDA 源上 torch 的最新可用版本 #>
    param([string]$Tag)

    $base = "https://download.pytorch.org/whl/$Tag"
    $html = Invoke-WebRequest "$base/torch/" -UseBasicParsing -TimeoutSec 30
    $m = [regex]::Matches($html.Content, 'torch-(\d+\.\d+\.\d+)%2B' + [regex]::Escape($Tag) + '-cp3\d+-')
    if (-not $m.Count) { throw "在 $base 未找到 PyTorch wheel" }

    $versions = $m | ForEach-Object { [version]$_.Groups[1].Value } | Sort-Object -Unique
    return @{ Index = $base; Version = $versions[-1].ToString() }
}

# ---------------------------------------------------------------- 安装辅助

function Install-Package {
    <# 优先用 uv（更快），没有则用 venv 自带的 pip #>
    param([string[]]$Packages, [string]$Index, [switch]$NoDeps, [switch]$Reinstall)

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        $a = @("pip", "install") + $Packages + @("--python", $VenvPy)
        if ($Index)     { $a += @("--default-index", $Index) }
        if ($NoDeps)    { $a += "--no-deps" }
        if ($Reinstall) { $a += "--reinstall" }
        & $uv.Source @a
    } else {
        $a = @("-m", "pip", "install", "--disable-pip-version-check")
        if ($Index)     { $a += @("-i", $Index) }
        $a += $Packages
        if ($NoDeps)    { $a += "--no-deps" }
        if ($Reinstall) { $a += "--force-reinstall" }
        & $VenvPy @a
    }
    if ($LASTEXITCODE -ne 0) { throw "安装失败: $($Packages -join ' ')" }
}

function Install-TorchFast {
    <#
      torch 的 CUDA wheel 约 2.6 GB，是整个安装中最大的单文件。
      pip / uv 使用单连接下载，在限速网络下可能耗时很久且中途挂死。
      aria2c 用 16 个分片并发，实测快 10 倍以上。
      没有 aria2c 时自动回退到常规 pip 安装。
    #>
    param([string]$Tag, [string]$Version)

    $aria = Get-Command aria2c -ErrorAction SilentlyContinue
    if (-not $aria) {
        Write-Warn2 "未找到 aria2c，改用 pip 下载（2.6GB 可能较慢）"
        Write-Warn2 "装上 aria2c 可大幅提速: winget install aria2.aria2"
        $pkg = if ($Tag -eq "cpu") { "torch==$Version" } else { "torch==$Version+$Tag" }
        Install-Package -Packages @($pkg) -Index "https://download.pytorch.org/whl/$Tag"
        return
    }

    # 从 PyTorch 官方索引解析出与当前 Python / 架构匹配的 wheel 直链
    # 注意平台标签是 win_amd64 / win32，不是 amd64
    $pyTag = (& $VenvPy -c "import sys;print('cp%d%d' % sys.version_info[:2])").Trim()
    $arch = if ([Environment]::Is64BitOperatingSystem) { "win_amd64" } else { "win32" }
    $fileName = "torch-$Version+$Tag-$pyTag-$pyTag-$arch.whl"
    $url = "https://download.pytorch.org/whl/$Tag/$fileName"
    Write-Host "    wheel: $fileName" -ForegroundColor DarkGray

    # 用 Range GET 探测文件大小。
    #   不能用 HEAD —— download.pytorch.org 对 HEAD 返回 403。
    #   该源在高频请求时会短暂限流返回 403，故带重试；仍失败则跳过校验直接交给 aria2c。
    $size = 0L
    for ($try = 1; $try -le 3 -and $size -le 0; $try++) {
        try {
            $req = [Net.HttpWebRequest]::Create($url)
            $req.Method = "GET"
            $req.Timeout = 30000
            $req.AddRange(0, 0)
            $req.UserAgent = "vocal-extractor-installer"
            $resp = $req.GetResponse()
            # Content-Range 形如 "bytes 0-0/2626709376"
            $cr = $resp.Headers["Content-Range"]
            $resp.Close()
            if ($cr -match "/(\d+)$") { $size = [int64]$Matches[1] }
        } catch {
            $why = $_.Exception.Message
            if ($try -lt 3) {
                Write-Warn2 "探测文件大小失败（第 $try/3 次）: $why"
                Start-Sleep -Seconds (2 * $try)
            } else {
                Write-Warn2 "探测文件大小失败（已重试 3 次）: $why"
            }
        }
    }
    if ($size -gt 0) {
        Write-Ok ("wheel {0:N0} MB，使用 aria2c 16 线程下载" -f ($size / 1MB))
    } else {
        Write-Warn2 "未能获取文件大小（源站限流），仍尝试 aria2c 下载"
    }

    Write-Ok "使用 aria2c 16 线程下载"
    $dlDir = Join-Path $env:TEMP "vocal_extractor_dl"
    New-Item -ItemType Directory -Force -Path $dlDir | Out-Null
    $wheelPath = Join-Path $dlDir $fileName
    Remove-Item "$wheelPath*" -Force -EA SilentlyContinue

    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $aria.Source -x16 -s16 -k4M --file-allocation=none `
        --max-tries=10 --retry-wait=2 --connect-timeout=20 --timeout=60 `
        --lowest-speed-limit=50K --console-log-level=warn --summary-interval=0 `
        -d $dlDir $url 2>&1 | Out-Null
    $sw.Stop()

    # 校验：已知大小时比对长度，否则只要求文件存在且足够大（torch wheel 必然 >100MB）
    $ok = Test-Path $wheelPath
    if ($ok) {
        $actual = (Get-Item $wheelPath).Length
        if ($size -gt 0) { $ok = $actual -ge $size } else { $ok = $actual -gt 100MB }
    }
    if (-not $ok) {
        Remove-Item "$wheelPath*" -Force -EA SilentlyContinue
        Write-Warn2 "aria2c 下载不完整，回退 pip（可能较慢）"
        Install-Package -Packages @("torch==$Version+$Tag") -Index "https://download.pytorch.org/whl/$Tag"
        return
    }

    $downloaded = (Get-Item $wheelPath).Length
    $mbps = ($downloaded / 1MB) / [Math]::Max($sw.Elapsed.TotalSeconds, 0.1)
    Write-Ok ("下载完成 {0:N0} MB / {1:N0}s，平均 {2:N2} MB/s" -f ($downloaded / 1MB), $sw.Elapsed.TotalSeconds, $mbps)

    Install-Package -Packages @($wheelPath) -NoDeps
    Remove-Item $dlDir -Recurse -Force -EA SilentlyContinue
}

# ---------------------------------------------------------------- 主流程

Write-Host ""
Write-Host "  ============================================" -ForegroundColor White
Write-Host "   vocal-extractor  安装程序" -ForegroundColor White
Write-Host "  ============================================" -ForegroundColor White

# 控制台按 UTF-8 输出，保证中文提示在非中文 Windows 下也不乱码
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

# --- 1. Python ---
Write-Step "检查 Python"
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    Write-Err "找不到 '$Python'。请安装 Python 3.10 ~ 3.13 后重试"
    exit 1
}
$pyVer = (& $Python -c "import sys;print('%d.%d.%d' % sys.version_info[:3])").Trim()
Write-Ok "Python $pyVer"

$pyMaj = [int]($pyVer.Split('.')[0])
$pyMin = [int]($pyVer.Split('.')[1])
if ($pyMaj -lt 3 -or ($pyMaj -eq 3 -and $pyMin -lt 10)) {
    Write-Err "需要 Python 3.10 以上，当前 $pyVer"
    exit 1
}
if ($pyMaj -eq 3 -and $pyMin -gt 13) {
    Write-Err "当前 $pyVer 与本项目依赖不兼容"
    Write-Err "请使用 Python 3.10 ~ 3.13"
    exit 1
}

# --- 2. 虚拟环境 ---
Write-Step "准备虚拟环境"
if (Test-Path $VenvDir) {
    if ($Force) {
        Write-Warn2 "删除已存在的 .venv"
        Remove-Item $VenvDir -Recurse -Force
    } else {
        Write-Ok ".venv 已存在（加 -Force 可重建）"
    }
}
if (-not (Test-Path $VenvPy)) {
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Err "创建虚拟环境失败"; exit 1 }
    Write-Ok "已创建 .venv"
}
& $VenvPy -m pip install --upgrade pip --quiet --disable-pip-version-check

# --- 3. CUDA 检测 ---
$cudaTag = "cpu"
if ($Cpu) {
    Write-Ok "按要求使用 CPU 版"
} else {
    $gpu = Get-GpuProfile
    if ($gpu) {
        Write-Ok "检测到 $($gpu.Name)  计算能力 $($gpu.ComputeCap)"
        $cudaTag = $gpu.CudaTag
    } else {
        Write-Warn2 "未检测到 NVIDIA 显卡，使用 CPU 版"
    }
}
if ($Cuda) {
    $cudaTag = if ($Cuda.StartsWith("cu")) { $Cuda } else { "cu$Cuda" }
    Write-Ok "按要求使用 CUDA $cudaTag"
}

try {
    $torch = Get-PyTorchVersion -Tag $cudaTag
    Write-Ok "PyTorch $($torch.Version)+$cudaTag"
} catch {
    Write-Err "查询 PyTorch 版本失败: $($_.Exception.Message)"
    Write-Err "可尝试 .\install.ps1 -Cpu 或指定 -Cuda 118"
    exit 1
}

# --- 4. 先装 PyTorch ---
<#
  必须排在依赖之前：PyPI 上新版 torch 只发 CPU 构建（118MB）。
  先从 PyTorch 官方源装好 CUDA 版，后续依赖解析就会直接满足 torch 依赖，
  不会再白下一份 CPU 版。
#>
Write-Step "安装 PyTorch ($cudaTag)"
Install-TorchFast -Tag $cudaTag -Version $torch.Version

# --- 5. 核心依赖 ---
Write-Step "安装 audio-separator 及依赖"
Install-Package -Packages @("audio-separator[gpu]")

# --- 6. ONNX Runtime 版本对齐 ---
<#
  onnxruntime-gpu 1.23+ 是 CUDA 13 构建，与 CUDA 12 的 torch 搭配会报
  "Failed to load cublas64_13.dll"。这里钉到与 torch 大版本一致的版本。
  仅影响 ONNX 类模型（MDX .onnx）；RoFormer 走 torch，不受影响。
#>
if ($cudaTag -ne "cpu") {
    Write-Step "对齐 ONNX Runtime 与 CUDA 大版本"
    $ortVer = if ($cudaTag -eq "cu118") { "1.18.1" } else { "1.22.0" }
    Install-Package -Packages @("onnxruntime-gpu==$ortVer") -NoDeps -Reinstall
    Write-Ok "onnxruntime-gpu $ortVer"
} else {
    Write-Step "安装 CPU 版 ONNX Runtime"
    Install-Package -Packages @("onnxruntime")
}

# --- 7. 平台修正 ---
Write-Step "应用平台修正"
if ($IsWindows -or $env:OS -eq "Windows_NT") {
    <#
      soundfile 0.13+ 的 Windows wheel 不再捆绑 libsndfile DLL，
      会报 OSError: cannot load library 'libsndfile.dll'。
      0.12.1 自带 _soundfile_data\libsndfile_64bit.dll。
    #>
    $sfOk = $true
    try { & $VenvPy -c "import soundfile" 2>$null } catch { $sfOk = $false }
    if (-not $sfOk) {
        Write-Warn2 "soundfile 不可用，降级到 0.12.1（自带 libsndfile DLL）"
        Install-Package -Packages @("soundfile==0.12.1") -NoDeps -Reinstall
    } else {
        Write-Ok "soundfile 可用"
    }
} else {
    Write-Ok "非 Windows 平台，无需 libsndfile 修正"
}

# --- 8. ffmpeg ---
Write-Step "检查 ffmpeg"
if (Get-Command ffmpeg -EA SilentlyContinue) {
    Write-Ok "ffmpeg 已安装"
} else {
    Write-Warn2 "未找到 ffmpeg —— 解码 MP3 / M4A 等格式会失败（WAV / FLAC 不受影响）"
    Write-Warn2 "Windows: winget install Gyan.FFmpeg"
    Write-Warn2 "macOS  : brew install ffmpeg"
    Write-Warn2 "Debian : sudo apt install ffmpeg"
}

# --- 9. 验证 ---
Write-Step "验证安装"
& $VenvPy (Join-Path $ProjectRoot "verify_install.py")

if ($LASTEXITCODE -ne 0) {
    Write-Err "验证未通过，请查看上方输出"
    exit 1
}

# --- 10. 预下载模型 ---
if (-not $SkipModel) {
    Write-Step "预下载分离模型（BS-Roformer，约 640 MB）"
    $modelDir = Join-Path $ProjectRoot "models"
    New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
    & $VenvPy (Join-Path $ProjectRoot "download_model.py") --model-dir $modelDir
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "模型预下载失败，首次使用时会自动重试"
    }
}

# --- 完成 ---
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "   安装完成" -ForegroundColor Green
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""
Write-Host "   把音频文件（或整个文件夹）拖到「人声分离.bat」上"
Write-Host "   即可在源文件旁生成 _人声.wav 和 _音乐.wav"
Write-Host ""
exit 0
