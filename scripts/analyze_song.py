#!/usr/bin/env python3
"""analyze_song.py —— 音频扒谱：beat 追踪 + 白名单 HMM/Viterbi + 小节制合并。

产出：原调和弦事件（吸附到拍点，最小单位 1 小节）+ beats + 质量指标。

用法：
    python analyze_song.py --audio 歌.mp3 --key-root Bb --key-mode minor --bpm 89 \
        [--lrc 歌词.json] --out analysis.json

先验说明（必填，来自公开资料/乐理常识，或由智能体听歌判断）：
  --key-root   原调根音：C Db D Eb E F Gb G Ab A Bb B
  --key-mode   major | minor
  --bpm        先验 BPM（粗略即可，beat_track 用它定初始；实测可能倍频，不影响小节划分）

质量指标（打印到 stdout，写进输出 JSON）：
  beat_phase_ratio   beat 处 onset 强度 / beat 中点强度；>1.5 可信
  lrc_beat_hit       歌词行起点 ±0.35s 内有 beat 的比例（仅参考；人声常落反拍，<50% 不代表 beat 错）

依赖：librosa>=0.10（注意 0.11 起 beat_track 在 librosa.beat 子模块）、numpy、ffmpeg（解码 mp3）。
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
PC = {n: i for i, n in enumerate(FLAT)}
PC.update({"C#": 1, "D#": 3, "F#": 6, "G#": 8, "A#": 10})

# 调内白名单：大调 I ii iii IV V vi；小调 i ii bIII iv V v bVI bVII（借用/离调由 HMM 自转移兜住）
MAJ = [(0, ""), (2, "m"), (4, "m"), (5, ""), (7, ""), (9, "m")]
MIN = [(0, "m"), (2, "m"), (3, ""), (5, "m"), (7, ""), (8, "m"), (10, ""), (0, "")]


def resolve_path(path: str) -> str:
    """Windows PowerShell 向 python 传中文 argv 会乱码（替换字符丢失信息）。
    兜底：路径不存在时，提取其中最长连续数字串（如酷我 musicId）在同目录 glob 匹配。"""
    import glob
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
    非 ASCII 路径先在临时目录建硬链接（失败则复制）成 ASCII 名再喂给 ffmpeg。"""
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        pass
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


def decode_audio(path: str, sr: int = 22050) -> str:
    """ffmpeg 解码为 wav（缓存到临时目录同名 wav，避免重复解码）"""
    cache = os.path.join(tempfile.gettempdir(), "gtm_wav")
    os.makedirs(cache, exist_ok=True)
    base = f"audio_{abs(hash(os.path.abspath(path))) & 0xffffffff:x}"
    wav = os.path.join(cache, base + f"_{sr}.wav")
    if not os.path.exists(wav):
        subprocess.run(["ffmpeg", "-y", "-i", ascii_safe_path(path),
                        "-ar", str(sr), "-ac", "1", wav],
                       check=True, capture_output=True)
    return wav


def label(nm):
    return FLAT[nm[0]] + nm[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--key-root", required=True, help="C Db D Eb E F Gb G Ab A Bb B（也认 #）")
    ap.add_argument("--key-mode", required=True, choices=["major", "minor"])
    ap.add_argument("--bpm", type=float, required=True, help="先验 BPM（粗略即可）")
    ap.add_argument("--lrc", default="", help="歌词 JSON（fetch_lrc.py 产物），用于命中率指标")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import librosa  # 延迟导入，--help 不依赖

    root = PC[args.key_root]
    degrees = MAJ if args.key_mode == "major" else MIN
    states = [((root + iv) % 12, sfx) for iv, sfx in degrees]
    S = len(states)

    wav = decode_audio(resolve_path(args.audio))
    y, sr = librosa.load(wav, sr=22050, mono=True)
    dur = len(y) / sr

    # ---- beat 追踪（start_bpm 用先验；倍频无妨，beat 点都是真实攻击点）----
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    try:
        tempo, bt = librosa.beat.beat_track(y=y, sr=sr, units="frames",
                                            onset_envelope=onset_env,
                                            start_bpm=args.bpm, tightness=100)
    except AttributeError:  # librosa <0.10 兼容
        tempo, bt = librosa.beat.beat_track(y=y, sr=sr, units="frames",
                                            onset_envelope=onset_env, start_bpm=args.bpm)
    bt_t = librosa.frames_to_time(bt, sr=sr, hop_length=512)
    tempo = float(np.atleast_1d(tempo)[0])

    # beat 相位自检：beat 处 onset / beat 中点 onset
    fr_beat = np.clip(librosa.time_to_frames(bt_t, sr=sr, hop_length=512), 0, len(onset_env) - 1)
    mid_t = (bt_t[:-1] + bt_t[1:]) / 2 if len(bt_t) > 1 else np.array([])
    fr_mid = np.clip(librosa.time_to_frames(mid_t, sr=sr, hop_length=512), 0, len(onset_env) - 1)
    phase_ratio = float(onset_env[fr_beat].mean() / max(onset_env[fr_mid].mean(), 1e-6)) if len(fr_mid) else 0.0

    # ---- chroma → 帧级观测 ----
    chroma = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=4096, hop_length=1024)
    frame_t = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=1024)

    # 和弦模板 → 与 12 维 chroma 的余弦相似度（温度压缩到 [0.4, 1.0]）
    def tpl(pc, sfx):
        v = np.zeros(12)
        v[pc] = 1.0
        v[(pc + (3 if sfx == "m" else 4)) % 12] = 0.9
        v[(pc + 7) % 12] = 0.9
        return v / np.linalg.norm(v)

    T = np.stack([tpl(pc, sfx) for pc, sfx in states])  # S×12
    cn = chroma / (np.linalg.norm(chroma, axis=0, keepdims=True) + 1e-9)
    sim = T @ cn  # S×F
    energy = chroma.sum(axis=0)
    low = energy < np.percentile(energy, 20)  # 极低能量帧（休止/人声solo）发射均匀
    emit = 0.4 + 0.6 * np.clip(sim, 0, 1)
    emit[:, low] = 1.0 / S

    # ---- HMM：自转移 0.96（和弦至少稳定 1 拍），他转移均分 ----
    logA = np.full((S, S), math.log(0.04 / (S - 1)))
    np.fill_diagonal(logA, math.log(0.96))
    logE = np.log(emit + 1e-12)

    # Viterbi
    F = emit.shape[1]
    dp = np.full((S, F), -np.inf)
    ptr = np.zeros((S, F), dtype=np.int8)
    dp[:, 0] = math.log(1.0 / S) + logE[:, 0]
    for f in range(1, F):
        m = dp[:, f - 1][:, None] + logA
        ptr[:, f] = np.argmax(m, axis=0)
        dp[:, f] = m[ptr[:, f], np.arange(S)] + logE[:, f]
    path = np.zeros(F, dtype=np.int8)
    path[-1] = int(np.argmax(dp[:, -1]))
    for f in range(F - 2, -1, -1):
        path[f] = ptr[path[f + 1], f + 1]

    # ---- 小节制：4 拍一小节取路径众数；孤立小节（与左右不同）用后继平滑 ----
    def state_in(t0, t1):
        m = (frame_t >= t0) & (frame_t < t1)
        if not m.any():
            return None
        vals, cnt = np.unique(path[m], return_counts=True)
        return int(vals[np.argmax(cnt)])

    bounds = [(0.0, float(bt_t[0]))] if len(bt_t) else []  # 引子
    bounds += [(float(bt_t[i]), float(bt_t[min(i + 4, len(bt_t) - 1)])) for i in range(0, len(bt_t) - 1, 4)]
    if len(bt_t) and dur - float(bt_t[-1]) > 0.8:
        bounds.append((float(bt_t[-1]), dur))  # 尾奏
    if len(bounds) >= 2 and bounds[-1][1] - bounds[-1][0] < 0.8:  # 末小节过短并入前节
        bounds[-2] = (bounds[-2][0], bounds[-1][1])
        bounds.pop()

    bar_states = [state_in(a, b) for a, b in bounds]
    bar_states = [s if s is not None else (bar_states[i - 1] if i else 0) for i, s in enumerate(bar_states)]
    for i in range(1, len(bar_states) - 1):  # 孤立小节平滑
        if bar_states[i] != bar_states[i - 1] and bar_states[i] != bar_states[i + 1]:
            bar_states[i] = bar_states[i + 1]

    events = []  # (t, state_idx)
    for i, (a, b) in enumerate(bounds):
        if not events or events[-1][1] != bar_states[i]:
            events.append((round(a, 2), bar_states[i]))

    ev_out = [{"t": t, "c": label(states[stt])} for t, stt in events]

    # ---- 歌词命中率（过滤元信息行；±0.35s 窗口，人声常落反拍）----
    hit = None
    if args.lrc and os.path.exists(args.lrc):
        _META = re.compile(r"作词|作曲|编曲|制作人|吉他|贝斯|鼓|键盘|弦乐|和声|混音|母带|录音|监制|企划|OP|SP|：")
        with open(args.lrc, encoding="utf-8") as f:
            lrc = json.load(f)["lrc"]
        lyric_times = [x["t"] for x in lrc if x["text"].strip() and not _META.search(x["text"])]
        if lyric_times and len(bt_t):
            hits = sum(1 for t in lyric_times if np.min(np.abs(bt_t - t)) <= 0.35)
            hit = round(100 * hits / len(lyric_times), 1)

    out = {
        "chords": ev_out,
        "beats": [round(float(t), 3) for t in bt_t],
        "tempo": round(tempo, 1),
        "duration": round(dur, 1),
        "key": f"{args.key_root} {args.key_mode}",
        "beat_phase_ratio": round(phase_ratio, 2),
        "lrc_beat_hit": hit,
        "whitelist": [label(s) for s in states],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    cs = sorted({e["c"] for e in ev_out})
    print(f"tempo={out['tempo']} beats={len(bt_t)} beat相位比={out['beat_phase_ratio']}")
    print(f"chords={len(ev_out)} set={cs}" + (f" 歌词行命中={hit}%" if hit is not None else ""))
    print(f"OK: {args.out}")


if __name__ == "__main__":
    main()
