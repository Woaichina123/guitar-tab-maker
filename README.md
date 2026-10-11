# Guitar Tab Maker · 吉他谱工坊

自动扒歌 + 生成「边播放边跳和弦」的吉他跟练播放器。技能目录形式，遵循 [Agent Skills](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills) 规范（`SKILL.md` + `scripts/`），**可直接被 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（dsh）、Claude Code 等兼容 harness 加载**。

## 它做什么

输入一首歌的音频（mp3/wav/m4a/flac），输出单文件 HTML 播放器：

- 原曲音频内嵌（**不转调、不损伤音质**）
- 和弦随播放进度跳动高亮，附下一个和弦预告
- 每个和弦带指法图（开放和弦 + 大横按）
- 每小节标注扫弦箭头（8 个八分音符格）
- 歌词逐行同步、段落快捷跳转、播放变速跟练

## 工作管线

| 脚本 | 作用 |
|---|---|
| `scripts/fetch_lrc.py` | 双通道抓带时间轴歌词（酷我 musicId 优先，网易云兜底） |
| `scripts/analyze_song.py` | librosa 扒谱：beat 追踪 + 调内白名单 HMM/Viterbi + 小节制合并 |
| `scripts/verify_song.py` | 音频-谱面一致性校验（低频频谱根音比对），防原调标错/文件错配 |
| `scripts/build_songs.py` | 按配置重建曲库；指法和弦按 `(原调根音 − capo) mod 12` 自动换算 |
| `scripts/build_player.py` | 音频 base64 注入模板，生成单文件 HTML |
| `scripts/validate_player.py` | 成品综合校验（占位符/字段/段落索引/图库覆盖） |

## 快速开始

依赖：Python 3.10+、[ffmpeg](https://ffmpeg.org/)、Node.js（仅 harness 加载需要）。

```bash
pip install -r requirements.txt

# 1) 歌词
python scripts/fetch_lrc.py --title 歌名 --artist 歌手 --kuwo-id 358603096 --out lrc.json
# 2) 扒谱（原调根音与 BPM 为粗略先验，可用网络资料）
python scripts/analyze_song.py --audio song.mp3 --key-root Bb --key-mode minor --bpm 89 --lrc lrc.json --out analysis.json
# 3) 一致性校验（必跑）
python scripts/verify_song.py --audio song.mp3 --analysis analysis.json
# 4) 写配置（参考 examples/songs.example.json）后构建
python scripts/build_songs.py --config songs.json --template assets/player_template.html --out built.html
python scripts/build_player.py --template built.html --out player.html --audio 1=song.mp3
# 5) 终验
python scripts/validate_player.py player.html
```

完整 SOP、变调夹选法与踩坑检查点见 [`SKILL.md`](SKILL.md)。

## 在 DeepSeek Harness 中使用

把整个目录放到 dsh 的技能发现路径即可，无需转换：

- 用户级：`~/.dsh/skills/guitar-tab-maker/`（或 `~/.agents/skills/`，Claude Code 同根）
- 项目级：`<repo>/.agents/skills/guitar-tab-maker/`

dsh 只发现发现根下的**直接**子目录（不递归），不要嵌套两层。frontmatter 支持 `disable-model-invocation`、`user-invocable` 两个 dsh 专属开关。

## 免责声明

- 输出为**参考级谱面**：AI 听辨的切换点可能有小偏差，可在 `SONGS` 数据中改 `t` 值自行校准。
- 本仓库**不含任何歌曲音频或歌词**；请仅对自己有权使用的内容扒谱，并自行处理版权。
- MIT License。
