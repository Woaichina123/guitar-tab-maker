#!/usr/bin/env python3
"""build_player.py —— 把音频文件以 base64 注入播放器模板，生成单文件 HTML 播放器。

用法：
    python build_player.py --template assets/player_template.html \
        --out 播放器.html --audio 1=歌1.mp3 --audio 2=歌2.mp3

模板中占位符 __AUDIO_B64_N__（N 从 1 开始）会被对应槽位音频的 base64 替换。
"""
import argparse
import base64
import glob
import re
import sys
from pathlib import Path


def resolve_path(path: str) -> str:
    """Windows PowerShell 向 python 传中文 argv 会乱码（替换字符丢失信息）。
    兜底：路径不存在时，提取其中最长连续数字串（如酷我 musicId）在同目录 glob 匹配。"""
    p = Path(path)
    if p.exists():
        return path
    m = re.findall(r"\d{5,}", path)
    if m:
        d = p.parent if str(p.parent) != "." else Path(".")
        for digits in sorted(m, key=len, reverse=True):
            hits = glob.glob(str(d / f"*{digits}*"))
            if hits:
                best = max(hits, key=lambda h: Path(h).stat().st_size)  # 同名多版本取最大文件
                print(f"  (argv 乱码兜底) 按数字串 {digits} 匹配到: {best}", file=sys.stderr)
                return best
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="吉他谱播放器构建：音频 base64 注入模板")
    ap.add_argument("--template", required=True, help="播放器模板 HTML 路径")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument(
        "--audio",
        action="append",
        required=True,
        metavar="槽位=音频路径",
        help="例如 1=song.mp3，可多次传入，槽位号对应模板 __AUDIO_B64_N__",
    )
    args = ap.parse_args()

    template_path = Path(args.template)
    if not template_path.is_file():
        sys.exit(f"模板不存在: {template_path}")
    html = template_path.read_text(encoding="utf-8")

    for item in args.audio:
        slot, sep, path = item.partition("=")
        if not sep or not slot.strip().isdigit():
            sys.exit(f"--audio 参数格式错误: {item}（应为 槽位=路径）")
        audio_path = Path(resolve_path(path))
        if not audio_path.is_file():
            sys.exit(f"音频不存在: {audio_path}")
        b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        placeholder = f"__AUDIO_B64_{slot.strip()}__"
        if placeholder not in html:
            sys.exit(f"模板中找不到占位符 {placeholder}，请检查 SONGS 数据中 audio 字段")
        html = html.replace(placeholder, b64)

    if "__AUDIO_B64_" in html:
        print("警告：模板中仍有未替换的音频占位符，请检查是否漏传 --audio", file=sys.stderr)

    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1048576
    print(f"OK: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
