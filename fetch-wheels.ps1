<#
从 requirements.txt 解析包名+版本 -> 查 PyPI JSON 拿 wheel 直链 -> aria2c 16线程批量下载
用法: powershell -File fetch-wheels.ps1
#>
param(
    [string]$ReqFile = ".\wheels\requirements.txt",
    [string]$OutDir  = ".\wheels"
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$out = (New-Item -ItemType Directory -Force -Path $OutDir).FullName

# 1) 解析 "name==version"
$pkgs = Get-Content $ReqFile | ForEach-Object {
    if ($_ -match '^([A-Za-z0-9._-]+)==([^\s;\\]+)') { [pscustomobject]@{ Name=$Matches[1]; Ver=$Matches[2] } }
} | Sort-Object Name -Unique

"解析到 $($pkgs.Count) 个包，正在查 PyPI 直链..."

# 2) 逐个查 JSON，挑最适合 win_amd64/cp311 的 wheel
$urls = @(); $failed = @(); $totalBytes = 0

foreach ($p in $pkgs) {
    try {
        $j = Invoke-RestMethod "https://pypi.org/pypi/$($p.Name)/$($p.Ver)/json" -TimeoutSec 25
        $wheels = $j.urls | Where-Object { $_.packagetype -eq 'bdist_wheel' }
        if (-not $wheels) { $failed += $p.Name; continue }

        # 优先级：精确平台 > 纯 py > 任意 win > 任意
        $pick = $wheels | Sort-Object -Property `
            @{E={ if ($_.filename -eq "$($p.Name)-$($p.Ver)-cp311-cp311-win_amd64.whl") {0}
                    elseif ($_.filename -match 'cp311.*win_amd64') {1}
                    elseif ($_.filename -match 'py3-none-any|py2\.py3-none-any') {2}
                    elseif ($_.filename -match 'win_amd64') {3}
                    else {9} } } | Select-Object -First 1

        $urls  += $pick.url
        $totalBytes += $pick.size
        "{0,-24} {1,8:N1} MB" -f $p.Name, ($pick.size/1MB)
    }
    catch { $failed += "$($p.Name) (查询失败)" }
}

""
"总计 {0} 个文件 / {1:N0} MB" -f $urls.Count, ($totalBytes/1MB)
if ($failed) { "跳过: $($failed -join ', ')" }
""

$urls | Out-File "$out\urls.txt" -Encoding ascii

# 3) aria2c 多线程下载：-x16 -s16 突破单连接限速
#    --lowest-speed-limit=50K + --max-tries=10 : 低于 50KB/s 超过 60s 就重连，专治卡死
$sw = [Diagnostics.Stopwatch]::StartNew()
aria2c -x16 -s16 -k1M `
        --file-allocation=none `
        --max-tries=10 --retry-wait=2 `
        --connect-timeout=20 --timeout=60 `
        --lowest-speed-limit=50K `
        --console-log-level=warn --summary-interval=0 `
        -d $out -i "$out\urls.txt" 2>&1 | Out-Null
$sw.Stop()

$got = (Get-ChildItem $out -Filter *.whl -File).Count
""
"下载完成: {0}/{1} 个文件，用时 {2:N0}s，平均 {3:N2} MB/s" -f `
    $got, $urls.Count, $sw.Elapsed.TotalSeconds, ($totalBytes/1MB/$sw.Elapsed.TotalSeconds)
