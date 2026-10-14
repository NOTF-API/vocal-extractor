"""分离结果客观检查：人声轨是否符合语音的频谱特征"""

import glob
import os

import numpy as np
import soundfile as sf


def band_energy(x, sr, lo, hi):
    spectrum = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    mask = (freqs >= lo) & (freqs < hi)
    return spectrum[mask].sum()


print(f"{'文件':<18}{'语音带 300-3.4k':>18}{'>8k 高频':>14}{'<200 低频':>13}")
print("-" * 65)

for out in sorted(glob.glob("output/*.wav")):
    name = os.path.basename(out).split("_(Vocals)_")[0]
    data, sr = sf.read(out)
    mono = data[:, 0] if data.ndim > 1 else data
    total = (np.abs(np.fft.rfft(mono)) ** 2).sum()
    if total <= 0:
        print(f"{name:<18}{'静音/无内容':>18}")
        continue
    speech = band_energy(mono, sr, 300, 3400) / total * 100
    high = band_energy(mono, sr, 8000, sr / 2) / total * 100
    low = band_energy(mono, sr, 0, 200) / total * 100
    print(f"{name:<18}{speech:>17.1f}%{high:>13.1f}%{low:>12.1f}%")

print()
print("语音典型特征：能量集中在 300-3400Hz，超高频很少，低频极少")
print("若上表符合该特征，说明提取出的确实是人声而非残留伴奏或噪声")
