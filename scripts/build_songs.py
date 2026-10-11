#!/usr/bin/env python3
"""build_songs.py —— 按配置重建播放器模板中的 SONGS 曲库数组。

核心规则：
  1. 音频用原曲，不转调（保音质）；
  2. 谱面和弦 = 原调和弦自动换算为指法和弦：指法根音 = (原调根音 pc − capo) mod 12，大小调性质不变；
     —— 禁止手写 C→G 这类映射表（本项目踩坑：F/B♭ 换算写反导致整首级数错乱）。
  3. 输出 HTML 保留 __AUDIO_B64_N__ 占位符，再由 build_player.py 注入音频。

用法：
    python build_songs.py --config songs.json --template player_template.html --out 曲库.html

songs.json 结构：
{
  "songs": [
    {
      "slot": 1,                       // 音频槽位（对应 __AUDIO_B64_1__）
      "title": "东京今夜有雨", "artist": "金渔",
      "originalKey": "♭B 小调",         // 展示用原文
      "fingeringKey": "Am",            // 指法调（展示用）
      "capo": 1, "bpm": 89,
      "shift": "原调 ♭B，Am 指法夹 1 品",  // 展示用说明
      "analysis": "analysis_东京.json",  // analyze_song.py 产物（原调和弦）
      "lyrics": "lrc_东京.json",         // fetch_lrc.py 产物
      "sections": [{"name": "前奏", "start": 0, "pattern": "verse"}, ...],
      "patterns": {"verse": {"name": "主歌型", "arrows": ["↓",...], "tip": "..."}, ...},
      "progression": "Am → F → G → Em"  // 可省略，自动按前 10 个不同指法和弦归纳
    }
  ]
}
"""
import argparse
import json
import re
import sys

FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
      "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def parse_chord(name: str):
    """'Bbm' → (10, 'm')；'Fmaj7' → (5, 'maj7')；'G7' → (7, '7')"""
    m = re.match(r"^([A-G][#b]?)(.*)$", name)
    if not m:
        sys.exit(f"无法解析和弦名: {name}")
    return PC[m.group(1)], m.group(2)


def convert(chords, capo):
    """原调和弦列表 → 指法和弦（根音 - capo），合并连续重复"""
    out = []
    for e in chords:
        pc, sfx = parse_chord(e["c"])
        fc = FLAT[(pc - capo) % 12] + sfx
        if not out or out[-1]["c"] != fc:
            out.append({"t": e["t"], "c": fc})
    return out


def attach_section(chords, sections):
    """每个和弦事件标 s = 所属段落索引"""
    for c in chords:
        s = 0
        for i, sec in enumerate(sections):
            if c["t"] >= sec["start"] - 0.01:
                s = i
        c["s"] = s
    return chords


def js_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def song_js(song: dict) -> str:
    with open(song["analysis"], encoding="utf-8") as f:
        ana = json.load(f)
    with open(song["lyrics"], encoding="utf-8") as f:
        lrc = json.load(f)["lrc"]

    chords = attach_section(convert(ana["chords"], song["capo"]), song["sections"])

    progression = song.get("progression")
    if not progression:
        seen, seq = set(), []
        for c in chords:
            if c["c"] not in seen:
                seen.add(c["c"])
                seq.append(c["c"])
            if len(seq) >= 10:
                break
        progression = " → ".join(seq)

    lines = ["      {",
             f"        title: {js_str(song['title'])},",
             f"        artist: {js_str(song['artist'])},",
             f"        originalKey: {js_str(song['originalKey'])},",
             f"        fingeringKey: {js_str(song['fingeringKey'])},",
             f"        capo: {song['capo']},",
             f"        shift: {js_str(song['shift'])},",
             f"        bpm: {song['bpm']},",
             f"        audio: \"data:audio/mpeg;base64,__AUDIO_B64_{song['slot']}__\",",
             f"        progression: {js_str(progression)},"]

    # patterns
    lines.append("        patterns: {")
    pk = list(song["patterns"].items())
    for i, (k, p) in enumerate(pk):
        arrows = ", ".join(js_str(a) for a in p["arrows"])
        assert len(p["arrows"]) == 8, f"{song['title']} pattern {k} 必须 8 个位置"
        comma = "," if i < len(pk) - 1 else ""
        lines.append(f"          {k}: {{ name: {js_str(p['name'])}, arrows: [{arrows}], tip: {js_str(p.get('tip',''))} }}{comma}")
    lines.append("        },")

    # sections
    lines.append("        sections: [")
    for i, sec in enumerate(song["sections"]):
        comma = "," if i < len(song["sections"]) - 1 else ""
        lines.append(f"          {{ name: {js_str(sec['name'])}, start: {sec['start']}, pattern: {js_str(sec['pattern'])} }}{comma}")
    lines.append("        ],")

    # chords（每行 4 个，紧凑）
    lines.append("        chords: [")
    items = [f"{{ t: {c['t']}, c: {js_str(c['c'])}, s: {c['s']} }}" for c in chords]
    for i in range(0, len(items), 4):
        chunk = items[i:i + 4]
        comma = "," if i + 4 < len(items) else ""
        lines.append("          " + ", ".join(chunk) + comma)
    lines.append("        ],")

    # lyrics
    lines.append("        lyrics: [")
    items = [f"{{ t: {x['t']}, text: {js_str(x['text'])} }}" for x in lrc]
    for i in range(0, len(items), 2):
        chunk = items[i:i + 2]
        comma = "," if i + 2 < len(items) else ""
        lines.append("          " + ", ".join(chunk) + comma)
    lines.append("        ]")
    lines.append("      }")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    with open(args.template, encoding="utf-8") as f:
        html = f.read()

    body = ",\n".join(song_js(s) for s in cfg["songs"])
    new_block = "var SONGS = [\n" + body + "\n    ];"

    m = re.search(r"var SONGS = \[.*?\n    \];", html, re.S)
    if not m:
        sys.exit("模板中找不到 SONGS 数组")
    html = html[:m.start()] + new_block + html[m.end():]

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    for s in cfg["songs"]:
        with open(s["analysis"], encoding="utf-8") as f:
            n = len(json.load(f)["chords"])
        print(f"  · {s['title']}：{n} 个原调和弦 → 指法（capo {s['capo']}）")
    print(f"OK: {args.out}（音频占位符待 build_player.py 注入）")


if __name__ == "__main__":
    main()
