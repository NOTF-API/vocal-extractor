"""
预下载分离模型，避免首次使用时卡在几百 MB 的下载上。

用法:
    python download_model.py                          # 下载默认模型
    python download_model.py --model-dir ./models     # 指定缓存目录
    python download_model.py --list                   # 列出常用模型
    python download_model.py --model <文件名>          # 下载指定模型
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 默认模型：BS-Roformer-Viperx-1297
# 目前单模型最优（人声 SDR 12.9 dB），比 Demucs v4 高约 2 dB
DEFAULT_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"

# 常用备选，方便按场景选择
KNOWN_MODELS = {
    DEFAULT_MODEL: "BS-Roformer-Viperx-1297 (12.9dB) — 默认，单模型最优",
    "model_bs_roformer_ep_368_sdr_12.9628.ckpt": "BS-Roformer-Viperx-1296 (12.9dB) — 同级备选",
    "vocals_mel_band_roformer.ckpt": "MelBand Roformer (12.6dB) — 略快",
    "melband_roformer_big_beta4.ckpt": "MelBand Roformer Big Beta 4 (12.5dB)",
    "UVR-MDX-NET-Inst_HQ_3.onnx": "MDX-Net Inst HQ 3 (~11.5dB) — 很快，显存占用低",
    "UVR_MDXNET_KARA_2.onnx": "MDX-Net Karaoke 2 — 轻量，适合批量",
    "htdemucs_ft.yaml": "Demucs v4 htdemucs_ft (10.8dB) — 老牌方案，兼容性最好",
}


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="预下载 audio-separator 分离模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="常用模型:\n" + "\n".join(f"  {k}\n      {v}" for k, v in KNOWN_MODELS.items()),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"模型文件名（默认 {DEFAULT_MODEL}）")
    parser.add_argument("--model-dir", type=Path, default=Path("models"), help="模型缓存目录（默认 models）")
    parser.add_argument("--list", action="store_true", help="列出常用模型后退出")
    args = parser.parse_args()

    if args.list:
        print("常用模型：\n")
        for filename, desc in KNOWN_MODELS.items():
            marker = " (默认)" if filename == DEFAULT_MODEL else ""
            print(f"  {filename}{marker}\n      {desc}\n")
        return 0

    # Windows 控制台默认不是 UTF-8，中文提示会乱码
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    from audio_separator.separator import Separator

    args.model_dir.mkdir(parents=True, exist_ok=True)

    print(f"模型缓存目录: {args.model_dir.resolve()}")
    print(f"正在下载: {args.model}\n")

    import logging

    # Separator 的 log_level 要的是 logging 级别整数，不是字符串
    separator = Separator(
        model_file_dir=str(args.model_dir),
        log_level=logging.INFO,
    )
    separator.download_model_files(args.model)

    target = args.model_dir / args.model
    if target.exists():
        print(f"\n完成: {target}  ({human_size(target.stat().st_size)})")
        return 0

    print(f"\n下载未完成，可稍后重试，或直接运行分离任务让工具自动下载", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
