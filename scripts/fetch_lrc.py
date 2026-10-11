#!/usr/bin/env python3
"""fetch_lrc.py —— 双通道抓取带时间轴歌词，输出统一 JSON。

通道优先级：
  1. 酷我 H5（需 musicId，mp3 从酷我下载时文件名里的数字就是 musicId）
  2. 网易云（歌名+歌手搜索）

用法：
    python fetch_lrc.py --title 歌名 [--artist 歌手] [--kuwo-id 358603096] --out 歌词.json

输出格式：{"lrc": [{"t": 秒(float), "text": "..."}, ...]}，已过滤元信息行由调用方处理。
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request


def _get(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def fetch_kuwo(music_id: str):
    """酷我 H5 接口，返回 [(t, text)]；失败返回 None"""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("Referer", "https://m.kuwo.cn/"), ("User-Agent", "Mozilla/5.0")]
    try:
        raw = opener.open(
            f"http://m.kuwo.cn/newh5/singles/songinfoandlrc?musicId={music_id}&httpsStatus=1",
            timeout=15).read().decode("utf-8", "replace")
        d = json.loads(raw)
        lst = d.get("data", {}).get("lrclist") or []
        out = [(float(x["time"]), x["lineLyric"].strip()) for x in lst if x.get("lineLyric", "").strip()]
        return out or None
    except Exception as e:
        print(f"  酷我通道失败: {e}", file=sys.stderr)
        return None


def _parse_lrc_text(lrc: str):
    """标准 LRC 文本 → [(t, text)]"""
    out = []
    for line in lrc.splitlines():
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line.strip())
        if m:
            t = int(m.group(1)) * 60 + float(m.group(2))
            txt = m.group(3).strip()
            if txt:
                out.append((t, txt))
    return out


def fetch_netease(title: str, artist: str = ""):
    """网易云搜索+歌词，返回 [(t, text)]；失败返回 None"""
    try:
        q = urllib.parse.urlencode({"s": f"{title} {artist}".strip(), "type": 1, "limit": 5})
        raw = _get("https://music.163.com/api/search/get",
                   headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"},
                   data=q.encode())
        songs = json.loads(raw).get("result", {}).get("songs") or []
        if not songs:
            return None
        sid = songs[0]["id"]
        raw = _get(f"https://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1",
                   headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"})
        lrc = json.loads(raw).get("lrc", {}).get("lyric", "")
        out = _parse_lrc_text(lrc)
        return out or None
    except Exception as e:
        print(f"  网易云通道失败: {e}", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description="双通道抓取带时间轴歌词")
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--kuwo-id", default="", help="酷我 musicId（mp3 文件名里的数字）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = None
    if args.kuwo_id:
        print(f"· 酷我通道 musicId={args.kuwo_id} …")
        rows = fetch_kuwo(args.kuwo_id)
    if rows is None:
        print(f"· 网易云通道「{args.title} {args.artist}」…")
        rows = fetch_netease(args.title, args.artist)
    if rows is None:
        sys.exit("两个通道都失败，请人工粘贴歌词（可用 --lrc-file 转换标准 lrc 文本，后续扩展）")

    rows.sort()
    payload = {"lrc": [{"t": round(t, 2), "text": txt} for t, txt in rows]}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"OK: {args.out}  {len(rows)} 行  时长至 {rows[-1][0]:.0f}s")


if __name__ == "__main__":
    main()
