"""
检查分离出的 _人声 / _音乐 双轨是否有效。

用法:
    python check_split.py                     # 扫 ./test_src
    python check_split.py ./some_dir           # 扫指定目录
    python check_split.py ./out --glob "*人声*"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf


def human_note(ratio_db: float, corr: float) -> str:
    flags = []
    if corr > 0.3:
        flags.append("两轨相关性偏高，可能未真正分离")
    if ratio_db < -3:
        flags.append("人声能量明显低于伴奏，检查输入是否以人声为主")
    return "；".join(flags) if flags else "正常"


def main() -> int:
    parser = argparse.ArgumentParser(description="检查人声/伴奏双轨分离质量")
    parser.add_argument("directory", nargs="?", default="./test_src", help="包含分离结果的目录")
    parser.add_argument("--vocals-suffix", default="_人声", help="人声文件后缀")
    parser.add_argument("--music-suffix", default="_音乐", help="音乐文件后缀")
    args = parser.parse_args()

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    root = Path(args.directory)
    if not root.is_dir():
        print(f"目录不存在: {root}", file=sys.stderr)
        return 1

    pairs: list[tuple[Path, Path]] = []
    for vocals in sorted(root.rglob(f"*{args.vocals_suffix}.wav")):
        music = Path(str(vocals).replace(f"{args.vocals_suffix}.wav", f"{args.music_suffix}.wav"))
        if music.exists():
            pairs.append((vocals, music))

    if not pairs:
        print(f"在 {root} 下没找到配对的 *{args.vocals_suffix}.wav / *{args.music_suffix}.wav")
        print("先用 vocal_extractor.py 以 -s Vocals,Instrumental --beside 生成双轨")
        return 1

    print(f"找到 {len(pairs)} 对双轨\n")
    print(f"{'文件':<20}{'人声RMS':>10}{'音乐RMS':>10}{'能量比':>10}{'相关性':>9}  备注")
    print("-" * 78)

    problems = 0
    for vocals_path, music_path in pairs:
        try:
            v, _ = sf.read(vocals_path)
            i, _ = sf.read(music_path)
        except Exception as exc:  # noqa: BLE001
            print(f"{vocals_path.name:<20} 读取失败: {exc}")
            problems += 1
            continue

        n = min(len(v), len(i))
        v, i = v[:n], i[:n]

        rms_v = np.sqrt((v**2).mean())
        rms_i = np.sqrt((i**2).mean())
        ratio = 10 * np.log10((v**2).sum() / (i**2).sum() + 1e-20)
        corr = np.corrcoef(v.ravel(), i.ravel())[0, 1]
        note = human_note(ratio, corr)
        if note != "正常":
            problems += 1

        print(f"{vocals_path.stem:<20}{rms_v:>10.4f}{rms_i:>10.4f}{ratio:>+9.1f}d{corr:>+9.4f}  {note}")

    print()
    print("能量比 >0dB 表示人声更强；相关性接近 0 表示两轨互不串扰")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
