"""
环境自检：确认依赖安装正确、GPU 可用。

用法:
    python verify_install.py            # 完整检查
    python verify_install.py --quiet    # 只在出问题时输出

安装完成后运行本脚本，可快速定位环境问题。
退出码 0 表示一切正常。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

OK, WARN, BAD = "[OK]", "[!]", "[X]"


def check(label: str, fn, quiet: bool = False, optional: bool = False) -> bool:
    """执行一项检查，打印结果，返回是否通过。"""
    try:
        detail = fn()
        passed = True
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        passed = False

    if not passed and optional:
        mark = WARN
    elif passed:
        mark = OK
    else:
        mark = BAD

    if not quiet or not passed:
        print(f"    {mark} {label:<16}{detail}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 vocal-extractor 环境")
    parser.add_argument("--quiet", action="store_true", help="只在失败时输出")
    args = parser.parse_args()
    quiet = args.quiet

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    print("环境自检")
    print("-" * 62)

    failures = 0

    # --- ffmpeg ---
    def _ffmpeg():
        if not shutil.which("ffmpeg"):
            raise RuntimeError("未安装（解码 MP3/M4A 必需，WAV/FLAC 不受影响）")
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=15)
        return out.stdout.splitlines()[0][:60]

    if not check("ffmpeg", _ffmpeg, quiet, optional=True):
        failures += 1

    # --- Python ---
    print(f"    {OK} {'python':<16}{sys.version.split()[0]}")

    # --- torch ---
    cuda_ok = False
    try:
        import torch

        print(f"    {OK} {'torch':<16}{torch.__version__}")

        if torch.cuda.is_available():
            cuda_ok = True
            print(f"    {OK} {'gpu':<16}{torch.cuda.get_device_name(0)}")
            archs = torch.cuda.get_arch_list()
            print(f"    {OK} {'arch':<16}{', '.join(archs)}")
            x = torch.randn(512, 512, device="cuda")
            (x @ x).sum().item()
            print(f"    {OK} {'gpu 计算':<16}矩阵运算通过")
        else:
            print(f"    {WARN} {'gpu':<16}CUDA 不可用，将使用 CPU（会很慢）")
    except ImportError as exc:
        print(f"    {BAD} {'torch':<16}未安装 —— {exc}")
        failures += 1

    # --- soundfile ---
    def _soundfile():
        import soundfile as sf

        return f"{sf.__version__} (libsndfile {sf.__libsndfile_version__})"

    if not check("soundfile", _soundfile, quiet):
        failures += 1

    # --- onnxruntime ---
    def _onnx():
        import onnxruntime as ort

        provs = ort.get_available_providers()
        has_cuda = "CUDAExecutionProvider" in provs
        return f"{ort.__version__}  CUDA: {'是' if has_cuda else '否'}"

    check("onnxruntime", _onnx, quiet, optional=True)

    # --- audio-separator ---
    def _audio_sep():
        from importlib.metadata import version

        return version("audio-separator")

    if not check("audio-separator", _audio_sep, quiet):
        failures += 1

    # --- 模型 ---
    from pathlib import Path

    model_dir = Path("models")
    ckpts = list(model_dir.glob("*.ckpt")) if model_dir.is_dir() else []
    if ckpts:
        total = sum(f.stat().st_size for f in ckpts)
        print(f"    {OK} {'模型':<16}{len(ckpts)} 个 / {total / 1048576:.0f} MB")
    else:
        print(f"    {WARN} {'模型':<16}未下载，首次使用时会自动获取")

    print("-" * 56)
    if failures:
        print(f"发现 {failures} 个问题。可尝试重新运行 install.ps1 -Force")
        return 1

    if cuda_ok:
        print("一切正常，可以开始使用")
    else:
        print("依赖正常，但未启用 GPU。可用 install.ps1 -Force 重新安装以启用 CUDA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
