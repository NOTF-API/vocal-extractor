"""
vocal_extractor - 本地人声分离（去音乐，只留人声）

底层使用 python-audio-separator（UVR 官方模型封装），完全本地推理，音频不出本机。

用法:
    python vocal_extractor.py song.mp3
    python vocal_extractor.py ./songs -o ./vocals
    python vocal_extractor.py song.wav -q best -s Vocals,Instrumental
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from audio_separator.separator import (
    BatchSeparationError,
    InvalidAudioDataError,
    AudioExportError,
    Separator,
)

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}

# 质量档位。ensemble = 多个模型跑完再融合，比单模型更干净。
# 单模型最优: BS-Roformer-Viperx-1297，人声 SDR 12.9（Demucs v4 只有 10.8）
QUALITY_PRESETS = {
    # 档位 -> (ensemble_preset, 说明)
    "fast": (
        "instrumental_low_resource",
        "单模型 MDX，最快，够用于预览/批量初筛",
    ),
    "balanced": (
        "vocal_balanced",
        "2 模型 ensemble，均衡，日常够用（推荐默认）",
    ),
    "clean": (
        "vocal_clean",
        "2 模型 ensemble，min_fft 融合，乐器残留最少",
    ),
    "full": (
        "vocal_full",
        "2 模型 ensemble，max_fft 融合，人声抓取最全（可能带入伴奏）",
    ),
    "karaoke": (
        "karaoke",
        "3 模型 ensemble，UVR 社区验证的清人声配置",
    ),
    "rvc": (
        "vocal_rvc",
        "为人声克隆/训练调优，保留咬字与细节",
    ),
}

# 单模型档：不用 ensemble，追求简单 + 单次最快达到高 SDR
SINGLE_MODEL_PRESETS = {
    "best-single": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",  # BS-Roformer-Viperx-1297
    "best-single-mel": "vocals_mel_band_roformer.ckpt",  # MelBand Roformer, 12.6
    "demucs": "htdemucs_ft.yaml",  # Demucs v4 ft, 10.8 - 最兼容
    "kara": "UVR_MDXNET_KARA_2.onnx",  # MDX ONNX, 快且轻
}


def collect_inputs(targets: list[Path], skip_suffixes: tuple[str, ...] = ()) -> list[Path]:
    """把一个或多个文件/目录解析成待处理的音频文件列表，保持顺序并去重。"""
    found: list[Path] = []
    seen: set[Path] = set()

    for target in targets:
        if target.is_file():
            candidates = [target]
        elif target.is_dir():
            candidates = [
                p
                for p in sorted(target.rglob("*"))
                if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
            ]
            # 跳过已经分离出来的产物，避免重复处理
            candidates = [p for p in candidates if not p.stem.endswith(skip_suffixes)]
        else:
            raise FileNotFoundError(f"路径不存在: {target}")

        for path in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(path)

    return found


def format_duration(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="本地人声分离：去除音乐，只保留人声",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="质量档位:\n"
        + "\n".join(f"  {k:<10} {v[1]}" for k, v in QUALITY_PRESETS.items())
        + "\n  "
        + "\n  ".join(f"{k:<10} 单模型: {v}" for k, v in SINGLE_MODEL_PRESETS.items()),
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="+",
        help="一个或多个音频文件/目录（可拖入多个）",
    )
    parser.add_argument(
        "-q",
        "--quality",
        default="balanced",
        choices=list(QUALITY_PRESETS) + list(SINGLE_MODEL_PRESETS),
        help="质量档位（默认 balanced）",
    )
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("output"), help="输出目录（默认 output）")
    parser.add_argument(
        "--beside",
        action="store_true",
        help="输出到源文件所在目录，而不是统一输出目录",
    )
    parser.add_argument(
        "--vocals-name",
        default="{stem}_人声",
        help="人声文件名模板，{{stem}} 代表原文件名（默认 {{stem}}_人声）",
    )
    parser.add_argument(
        "--music-name",
        default="{stem}_音乐",
        help="音乐文件名模板（默认 {{stem}}_音乐）",
    )
    parser.add_argument(
        "-s",
        "--stems",
        default="Vocals",
        help="要输出的 stem，逗号分隔。默认只要 Vocals；用 'Vocals,Instrumental' 出伴奏",
    )
    parser.add_argument("-f", "--format", default="wav", help="输出格式 wav/flac/mp3（默认 wav，无损）")
    parser.add_argument("--bitrate", default=None, help="有损格式比特率，如 320k")
    parser.add_argument("--model-dir", type=Path, default=None, help="模型缓存目录")
    parser.add_argument(
        "--autocast",
        action="store_true",
        help="半精度加速（NVIDIA GPU 上更快，音质几乎无损）",
    )
    parser.add_argument(
        "--fp16",
        action="store_true",
        help="原生 float16 推理，仅 RoFormer 系列在 CUDA/MPS 上支持，比 --autocast 更快",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")

    args = parser.parse_args()
    stems = [s.strip() for s in args.stems.split(",") if s.strip()]
    if args.autocast and args.fp16:
        parser.error("--autocast 与 --fp16 互斥")

    # 已生成的文件不应被再次当作输入（避免重复处理 / 自我嵌套）
    output_suffixes = ("_vocals", "_instrumental", "_人声", "_音乐")

    files = collect_inputs(args.input, output_suffixes)
    if not files:
        print("没有找到可处理的音频文件", file=sys.stderr)
        return 1

    if not args.beside:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"找到 {len(files)} 个音频文件 | 质量档位: {args.quality}")
    if args.quality in QUALITY_PRESETS:
        print(f"  {QUALITY_PRESETS[args.quality][1]}")
    print(f"  输出 stem: {', '.join(stems)}")
    print(f"  输出位置: {'各自源文件所在目录' if args.beside else args.output_dir}\n")

    # 构建 Separator：ensemble 档走 preset，单模型档直接指定模型文件
    kwargs: dict = {
        "output_dir": str(args.output_dir),
        "output_format": args.format.upper(),
    }
    if args.bitrate:
        kwargs["output_bitrate"] = args.bitrate
    if args.model_dir:
        kwargs["model_file_dir"] = str(args.model_dir)
    if args.verbose:
        kwargs["log_level"] = "debug"
    if args.autocast:
        kwargs["use_autocast"] = True
    if args.fp16:
        kwargs["use_native_fp16"] = True
    # output_single_stem 只接受单个值；多 stem 时交给底层全部输出
    if len(stems) == 1:
        kwargs["output_single_stem"] = stems[0]

    if args.quality in SINGLE_MODEL_PRESETS:
        separator = Separator(**kwargs)
        separator.load_model(model_filename=SINGLE_MODEL_PRESETS[args.quality])
    else:
        separator = Separator(ensemble_preset=QUALITY_PRESETS[args.quality][0], **kwargs)
        separator.load_model()

    # Separator 不暴露 device 属性，直接问 torch
    try:
        import torch

        device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    except ImportError:
        device = "unknown"
    precision = getattr(separator, "effective_precision", "?")
    print(f"设备: {device} | 精度: {precision} | 开始处理...\n")

    start = time.time()
    failures: list[tuple[str, str]] = []
    succeeded = 0

    for index, path in enumerate(files, 1):
        prefix = f"[{index}/{len(files)}] {path.name}"
        print(f"{prefix}", end=" ", flush=True)
        file_start = time.time()
        try:
            if args.beside:
                # 必须同时改 Separator 和 model_instance：
                # common_separator 在构造时把 output_dir 拷进模型实例了
                # （库内部做分块处理时也是两处一起改，见 separator.py:1255）
                separator.output_dir = str(path.parent)
                separator.model_instance.output_dir = str(path.parent)

            # 每个 stem 一个自定义文件名，中文安全（sanitize 只过滤 <>:"/\|?*）
            names = {}
            for stem in stems:
                template = args.vocals_name if stem.lower() == "vocals" else args.music_name
                names[stem] = template.format(stem=path.stem)

            separator.separate(str(path), custom_output_names=names)
            elapsed = time.time() - file_start
            print(f"✓ {format_duration(elapsed)}")
            for stem in stems:
                template = args.vocals_name if stem.lower() == "vocals" else args.music_name
                out_name = template.format(stem=path.stem) + "." + args.format
                out_dir = path.parent if args.beside else args.output_dir
                print(f"      -> {out_dir / out_name}")
            succeeded += 1
        except (InvalidAudioDataError, AudioExportError) as error:
            print(f"✗ {error}", file=sys.stderr)
            failures.append((str(path), str(error)))
        except KeyboardInterrupt:
            print("\n已中断", file=sys.stderr)
            return 130

    total = time.time() - start
    print(f"\n完成 {succeeded}/{len(files)} 个，用时 {format_duration(total)}")
    print(f"输出目录: {args.output_dir.resolve()}")

    if failures:
        print(f"\n失败 {len(failures)} 个:", file=sys.stderr)
        for path, reason in failures:
            print(f"  {path}: {reason}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
