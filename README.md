# vocal-extractor

**本地音频人声分离** —— 把一首歌拆成「人声」和「伴奏」两个文件。全部推理在你的电脑上完成，音频不上传任何服务器。

拖一下就能用：

```
song.mp3  ──拖到──▶  人声分离.bat  ──▶  song_人声.wav
                                        song_音乐.wav
```

---

## 为什么不是 Demucs

Demucs v4（Meta）名气最大，但它已经不是当前最优解了。人声分离的信号失真比（SDR，越高越干净）对比：

| 模型 | 人声 SDR | 说明 |
|---|---|---|
| **BS-Roformer-Viperx** | **12.9 dB** | 当前最优，本项目默认 |
| MelBand Roformer (Kim) | 12.6 dB | |
| MDX23C / UVR-MDX 系列 | ~11.5 dB | 残留少，速度快 |
| Demucs v4 `htdemucs_ft` | 10.8 dB | Meta，生态成熟但落后约 2 dB |
| Spleeter | ~6.5 dB | 过于老旧，不建议 |

差距约 2 dB，听感上就是「伴奏还贴着人声」和「干净切开」的区别。

底层用的是 [`python-audio-separator`](https://github.com/nomadkaraoke/python-audio-separator)（MIT，1.4k star），它封装了 UVR 社区的全部模型与架构。本项目负责自动装环境、处理平台差异包好拖拽入口。

---

## 安装

需要 **Python 3.10 ~ 3.13**（3.14 与依赖不兼容）。

### Windows

```powershell
git clone https://github.com/NOTF-API/vocal-extractor.git
cd vocal-extractor
.\install.ps1
```

如果 PowerShell 拒绝执行脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

安装脚本会自动完成：

- 检测 NVIDIA 显卡与计算能力，挑选匹配的 CUDA 版 PyTorch
  （Blackwell / RTX 50 系 → cu128，Ada/Hopper/Ampere → cu126，更老 → cu118）
- 对齐 `onnxruntime-gpu` 与 PyTorch 的 CUDA 主版本（这是最常见的翻车点）
- 修正 Windows 上 `soundfile` 缺失 `libsndfile` DLL 的问题
- 预下载默认模型（约 640 MB）

常用参数：

| 参数 | 作用 |
|---|---|
| `.\install.ps1 -Cpu` | 无显卡 / 强制 CPU |
| `.\install.ps1 -Cuda 126` | 手动指定 CUDA 版本 |
| `.\install.ps1 -SkipModel` | 跳过模型预下载 |
| `.\install.ps1 -Force` | 删除 `.venv` 重建 |
| `.\install.ps1 -Fast` | 跳过 aria2c 预下载，直接用 pip |

### macOS / Linux

```bash
git clone <this-repo>
cd vocal-extractor
python3 -m venv .venv
source .venv/bin/activate
pip install "audio-separator[gpu]"

# CUDA 版 PyTorch（按你的显卡选 cu126 / cu128）
pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
```

另需 `ffmpeg`：`brew install ffmpeg` / `sudo apt install ffmpeg`。

---

## 使用

### 图形入口（最省事）

把音频文件或整个文件夹**拖到 `人声分离.bat` 上**。源文件旁边会生成两个文件：

```
别放松.wav
  ├── 别放松_人声.wav     只有人声
  └── 别放松_音乐.wav     只有伴奏
```

### 命令行

```powershell
# 单个文件
.\.venv\Scripts\python.exe vocal_extractor.py song.mp3

# 批量：传目录
.\.venv\Scripts\python.exe vocal_extractor.py .\songs

# 只要人声，输出到指定目录
.\.venv\Scripts\python.exe vocal_extractor.py song.mp3 -o .\out

# 输出到各自源文件旁，自定义后缀
.\.venv\Scripts\python.exe vocal_extractor.py .\songs --beside -s Vocals,Instrumental
```

---

## 质量档位

`-q` 选择档位。核心区别是**要不要跑多模型 ensemble**：多个模型各自分离后再做频域融合，
误差互相抵消，残留明显更少，代价是慢一倍。

### 单模型（最快达到高 SDR）

| 档位 | 模型 | 人声 SDR |
|---|---|---|
| `best-single` | BS-Roformer-Viperx-1297 | **12.9 dB** |
| `best-single-mel` | MelBand Roformer (Kimberley Jensen) | 12.6 dB |
| `kara` | UVR-MDXNET_KARA_2 | ~11 dB |
| `demucs` | Demucs v4 `htdemucs_ft` | 10.8 dB |

### Ensemble（多模型融合，质量优先）

| 档位 | 配置 | 说明 |
|---|---|---|
| `balanced` | 2 模型 / `avg_fft` | 默认，均衡 |
| `clean` | 2 模型 / `min_fft` | 伴奏残留最少 |
| `full` | 2 模型 / `max_fft` | 人声抓取最全，可能带进伴奏 |
| `karaoke` | 3 模型 | UVR 社区验证的清人声配置 |
| `rvc` | 2 模型 / `avg_wave` | 为人声克隆 / 训练调优 |
| `fast` | 2 模型 / `avg_fft` | 低显存，快速初筛 |

---

## 效果验证

以短语音片段为例，提取后的人声轨频谱分布：

| 文件 | 语音带 300–3.4 kHz | >8 kHz | <200 Hz |
|---|---|---|---|
| 一切正常，美羊羊 | **96.8%** | 0.3% | 0.0% |
| 别放松 | **86.1%** | 2.3% | 0.1% |
| 美羊羊，你这边 | **82.1%** | 1.8% | 0.0% |

能量高度集中在语音频段，低频（贝斯）与超高频（镲片）几乎归零 —— 伴奏的频谱特征被剥离干净。

人声轨与伴奏轨的相关性约 **0.003**，即两轨基本正交、互不串扰。

复现：

```powershell
.\.venv\Scripts\python.exe vocal_extractor.py <音频> -q best-single -s Vocals,Instrumental --beside -o .\test_src
.\.venv\Scripts\python.exe check_split.py
```

> 频域指标只能说明「提取出的是人声频谱」，**主观听感仍需自己确认**。

---

## 原理

不是滤波或降噪，而是**源分离（source separation）**：把混合音频变换到时频表示，
用训练好的神经网络预测每个时频点属于人声还是伴奏，再重建出人声波形。

不同架构的取舍：

- **Demucs** —— 时域波形处理，保留瞬态（鼓点）好
- **MDX-Net** —— 频谱掩蔽，谐波成分干净，低频可能有泄漏
- **RoFormer** —— 切开频带 + 旋转位置编码的 Transformer，同时建模时间与频率关联，目前 SOTA

---

## 踩过的坑

这些是实际部署时真实遇到并已在本项目中处理的问题，记录下来供后来者参考。

### 1. PyPI 上的新版 torch 是 CPU 版

torch 2.14+ 在 PyPI 上只发布 CPU 构建，CUDA 版要单独装：

```powershell
pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
```

安装脚本会自动检测并处理。

### 2. onnxruntime-gpu 与 torch 的 CUDA 主版本必须一致

`onnxruntime-gpu` 1.23+ 是 CUDA 13 构建。配 CUDA 12 的 torch 会报：

```
Failed to load cublas64_13.dll
```

解法：把 onnxruntime 钉到 `1.22.0`（CUDA 12）或 `1.18.1`（CUDA 11.8）。

> 只用 RoFormer 系列（走 torch）的话，这项不影响。

### 3. soundfile 0.13+ 在 Windows 上缺少 libsndfile

```
OSError: cannot load library 'libsndfile.dll'
```

新版 wheel 不再捆绑二进制 DLL。降到 `0.12.1`（自带 `_soundfile_data\libsndfile_64bit.dll`）。

### 4. PowerShell 脚本含中文必须存为 UTF-8 **带 BOM**

Windows PowerShell 5.1 靠 BOM 识别 UTF-8。没有 BOM 时会按系统 ANSI 代码页（中文环境为 GBK）
解码，中文变乱码并破坏引号配对，直接语法报错。

> 对照：`.bat` 文件恰好相反 —— cmd.exe 无法可靠处理 UTF-8，所以本项目的 `人声分离.bat`
> **内容全部是纯 ASCII**，中文一律由 Python 在运行时输出。

### 5. 单连接限速

部分网络环境对单条 TCP 流限速严重。实测同一时刻：

| 下载方式 | 速度 |
|---|---|
| pip（单连接） | 0.4 MB/s，且大文件易挂死 |
| aria2c `-x16`（16 连接） | 11.5 MB/s |
| download.pytorch.org | 48.7 MB/s |

`fetch-wheels.ps1` 封装了 aria2c 多线程下载方案，并在速度跌破阈值时自动重连。

---

## 项目结构

```
vocal-extractor/
├── install.ps1           一键安装（Windows，自动检测硬件）
├── 人声分离.bat          拖拽入口
├── vocal_extractor.py    核心 CLI
├── download_model.py     模型预下载
├── analyze.py            分离结果的频域检查
├── check_split.py        人声/伴奏双轨检查
├── fetch-wheels.ps1      aria2c 多线程下载依赖
├── LICENSE
└── README.md
```

---

## 致谢

本项目是一个便利封装，**不包含模型本身**，运行时下载。以下项目是真正的工作者：

- **[python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator)** — MIT，
  本项目的底层库，提供 CLI / Python API 与全部模型架构支持
- **[Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui)** — UVR 社区模型权重来源
- **[lucidrains/BS-RoFormer](https://github.com/lucidrains/BS-RoFormer)** — RoFormer 架构参考实现
- 各个模型的原作者：viperx、Kimberley Jensen、Gabox、unwa、becruily、Anjok07、Sucial 等

---

## ⚠️ 许可提示

代码以 MIT 发布，但**模型权重各有独立许可**，部分 UVR 社区训练模型禁止商用。

**将本项目用于商业场景前，请自行确认所下载模型的 license。** 详见 [LICENSE](LICENSE)。

另外，分离他人受版权保护的音乐可能违反当地法律，请自行判断用途是否合法。

---

## License

MIT，见 [LICENSE](LICENSE)。
