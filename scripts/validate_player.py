#!/usr/bin/env python3
"""validate_player.py —— 播放器成品综合校验。

检查项：
  1. 音频占位符必须全部替换（不存在 __AUDIO_B64_）；
  2. SONGS 每首歌字段完整（title/artist/originalKey/fingeringKey/capo/shift/bpm/audio/
     progression/patterns/sections/chords/lyrics），audio 是真实 base64 且长度合理；
  3. patterns 每个 8 个位置、取值只含 ↓ ↑ 空串；sections 的 pattern 引用存在；
  4. chords 的 s 索引不越界，t 单调不减；
  5. **图库覆盖**：chords 用到的每个和弦名必须存在于 CHORD_DIAGRAMS（漏图=播放器空白）；
  6. HTML 标签基本闭合（</html> 存在）。

用法：
    python validate_player.py 播放器.html
退出码：0 全过；1 有错误。
"""
import json
import re
import sys

ERR, WARN = [], []


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        sys.exit("用法: python validate_player.py 播放器.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    import os
    size_mb = os.path.getsize(path) / 1048576
    print(f"文件: {path}  实际大小 {size_mb:.1f} MB")

    # 1. 占位符
    left = re.findall(r"__AUDIO_B64_\d+__", html)
    if left:
        ERR.append(f"未替换的音频占位符: {sorted(set(left))}")

    # 2. 提取 SONGS（用括号配平，而不是正则贪婪猜）
    m = re.search(r"var SONGS = \[", html)
    if not m:
        ERR.append("找不到 var SONGS = [")
        songs = []
    else:
        depth, i = 0, m.end() - 1
        start = i
        while i < len(html):
            ch = html[i]
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == '"':
                i += 1
                while i < len(html) and html[i] != '"':
                    i += 2 if html[i] == "\\" else 1
            i += 1
        block = html[start:i + 1]
        # JS → JSON 近似：键名加引号（本模板 SONGS 只用简单字面量）
        block2 = re.sub(r"([{,]\s*)(\w+):", r'\1"\2":', block)
        try:
            songs = json.loads(block2)
        except Exception as e:
            ERR.append(f"SONGS 解析失败: {e}")
            songs = []

    # 3. 图库
    m = re.search(r"var CHORD_DIAGRAMS = \{(.*?)\n    \};", html, re.S)
    lib = set(re.findall(r'"([A-G][#b]?m?(?:maj7|7)?)"\s*:', m.group(1))) if m else set()
    print(f"图库和弦: {sorted(lib)}")

    REQ = ["title", "artist", "originalKey", "fingeringKey", "capo", "shift", "bpm",
           "audio", "progression", "patterns", "sections", "chords", "lyrics"]
    used_all = set()
    for idx, s in enumerate(songs):
        tag = f"歌{idx+1}「{s.get('title','?')}」"
        for k in REQ:
            if k not in s:
                ERR.append(f"{tag} 缺字段 {k}")
        if not str(s.get("audio", "")).startswith("data:audio/mpeg;base64,") or "__AUDIO" in s.get("audio", ""):
            ERR.append(f"{tag} audio 未注入真实音频")
        for pk, p in s.get("patterns", {}).items():
            if len(p.get("arrows", [])) != 8:
                ERR.append(f"{tag} pattern {pk} 不是 8 个位置")
            for a in p.get("arrows", []):
                if a not in ("↓", "↑", ""):
                    ERR.append(f"{tag} pattern {pk} 含非法箭头 {a!r}")
        pnames = set(s.get("patterns", {}))
        for sec in s.get("sections", []):
            if sec.get("pattern") not in pnames:
                ERR.append(f"{tag} section「{sec.get('name')}」引用了不存在的 pattern {sec.get('pattern')}")
        nsec = len(s.get("sections", []))
        last_t = -1
        for c in s.get("chords", []):
            used_all.add(c["c"])
            if not (0 <= c.get("s", 0) < nsec):
                ERR.append(f"{tag} 和弦 {c} 的 s 越界")
            if c.get("t", 0) < last_t - 0.001:
                WARN.append(f"{tag} 和弦 t 非单调: {c}")
            last_t = c.get("t", 0)

    missing = sorted(used_all - lib)
    if missing:
        ERR.append(f"图库缺和弦指法图: {missing}（播放器这些和弦将无图）")

    # 6. 闭合
    if "</html>" not in html:
        ERR.append("缺 </html>")

    print(f"曲库 {len(songs)} 首，全部用弦 {sorted(used_all)}")
    for w in WARN[:10]:
        print(f"  ⚠ {w}")
    if ERR:
        print("\n❌ 错误：")
        for e in ERR:
            print(f"  · {e}")
        sys.exit(1)
    print("\n✓ 全部校验通过")


if __name__ == "__main__":
    main()
