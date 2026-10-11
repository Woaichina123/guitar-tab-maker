#!/usr/bin/env python3
"""verify_song.py —— 音频-谱面一致性校验（防"原调标错/文件错配"事故）。

原理：对每个和弦事件对应的音频段做低频频谱分析，提取 30-300Hz 能量峰值
（贝斯/低音区通常落在和弦根音或五音），与谱面和弦比对：
  根音吻合 → OK；五音吻合 → OK-5th；都不吻合 → MISMATCH。

判定阈值：
  mismatch 率 < 15% 视为正常（转位/经过音/人声音干扰）；
  ≥15% 高度可疑——原调标错或音频文件与谱面不符，必须人工听辨确认后再构建。

用法：
    python verify_song.py --audio 歌.mp3 --analysis analysis.json
"""
import argparse
import json
import re
import subprocess
import sys

import numpy as np

FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
      "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def pc_of(name: str) -> int:
    m = name.rstrip("m").replace("maj7", "").replace("7", "").replace("m", "")
    return PC[m]


def resolve_path(path: str) -> str:
    """Windows PowerShell 向 python 传中文 argv 会乱码（替换字符丢失信息）。
    兜底：路径不存在时，提取其中最长连续数字串（如酷我 musicId）在同目录 glob 匹配。"""
    import glob
    import os
    if os.path.exists(path):
        return path
    m = re.findall(r"\d{5,}", path)
    if m:
        d = os.path.dirname(path) or "."
        for digits in sorted(m, key=len, reverse=True):
            hits = glob.glob(os.path.join(d, f"*{digits}*"))
            if hits:
                best = max(hits, key=os.path.getsize)  # 同名多版本取最大文件
                print(f"  (argv 乱码兜底) 按数字串 {digits} 匹配到: {best}", file=sys.stderr)
                return best
    return path  # 让下游报错


def ascii_safe_path(path: str) -> str:
    """Windows 上 mingw 版 ffmpeg 打不开中文路径（Illegal byte sequence）：
    非 ASCII 路径先建硬链接（失败则复制）成 ASCII 临时名。"""
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        pass
    import os
    import tempfile
    safe_dir = os.path.join(tempfile.gettempdir(), "gtm_ascii")
    os.makedirs(safe_dir, exist_ok=True)
    safe = os.path.join(safe_dir, f"audio_{abs(hash(os.path.abspath(path))) & 0xffffffff:x}"
                        + os.path.splitext(path)[1].lower())
    if not os.path.exists(safe):
        try:
            os.link(path, safe)
        except OSError:
            import shutil
            shutil.copy2(path, safe)
    return safe


def load_mono(path: str, sr: int = 22050):
    p = subprocess.run(["ffmpeg", "-i", ascii_safe_path(path),
                        "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                       capture_output=True)
    if p.returncode != 0 or not p.stdout:
        sys.exit(f"ffmpeg 解码失败: {path}\n{p.stderr.decode('utf-8', 'replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype=np.float32), sr


def low_peaks(seg: np.ndarray, sr: int, topn: int = 3):
    """返回片段 30-300Hz 的 topn 峰值 pc 集合"""
    if len(seg) < sr // 2:
        return set()
    win = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    mask = (freqs >= 30) & (freqs <= 300)
    f, s = freqs[mask], spec[mask]
    if len(f) == 0 or s.max() < 1e-6:
        return set()
    idx = np.argsort(s)[-topn * 6:]  # 多取些再去重（同音泛音相邻）
    pcs = []
    for i in sorted(idx, key=lambda i: -s[i]):
        pc = int(round(12 * np.log2(f[i] / 440.0))) % 12  # A4=440 → 9
        pc = (pc + 9) % 12
        if pc not in pcs:
            pcs.append(pc)
        if len(pcs) >= topn:
            break
    return set(pcs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--analysis", required=True, help="analyze_song.py 产物（含 chords 与 duration）")
    args = ap.parse_args()

    with open(args.analysis, encoding="utf-8") as f:
        ana = json.load(f)
    chords = ana["chords"]
    dur = ana["duration"]
    y, sr = load_mono(resolve_path(args.audio))

    rows = []
    for i, e in enumerate(chords):
        t0 = e["t"]
        t1 = chords[i + 1]["t"] if i + 1 < len(chords) else dur
        if t1 - t0 < 0.8:  # 太短不验
            continue
        seg = y[int(t0 * sr):int(min(t1, t0 + 4.0) * sr)]  # 最多取前 4 秒
        peaks = low_peaks(seg, sr)
        root = pc_of(e["c"])
        fifth = (root + 7) % 12
        if root in peaks:
            verdict = "OK"
        elif fifth in peaks:
            verdict = "OK-5th"
        else:
            verdict = "MISMATCH"
        rows.append({"t": t0, "chord": e["c"], "low_pcs": sorted(peaks), "verdict": verdict})

    n = len(rows)
    bad = [r for r in rows if r["verdict"] == "MISMATCH"]
    rate = 100 * len(bad) / max(n, 1)
    print(f"校验 {n} 个和弦段：OK {sum(1 for r in rows if r['verdict']=='OK')}，"
          f"OK-5th {sum(1 for r in rows if r['verdict']=='OK-5th')}，MISMATCH {len(bad)}（{rate:.0f}%）")
    if bad:
        print("不一致段（前 10）：")
        for r in bad[:10]:
            print(f"  {r['t']:7.1f}s  谱面 {r['chord']:4s}  低频实测 {[FLAT[p] for p in r['low_pcs']]}")
    if rate >= 15:
        print("\n⚠ 不一致率偏高：原调标错或音频文件与谱面不符的可能性大，"
              "请截取 MISMATCH 段人工听辨，必要时修正 --key-root 重跑 analyze_song.py。")
        sys.exit(2)
    print("✓ 一致性通过")


if __name__ == "__main__":
    main()
