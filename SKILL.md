---
name: guitar-tab-maker
description: 吉他谱扒谱与同步播放器生成技能。当用户上传歌曲音频（mp3/wav/m4a/flac）并要求扒谱、制作吉他谱、生成"边播放边跳和弦"的跟练谱面，或向已有曲库播放器中添加新歌时使用。自动管线：抓歌词→librosa 扒谱（beat追踪+HMM+小节制）→音频-谱面一致性校验→变调夹指法自动换算→构建单文件 HTML 播放器（原曲音频内嵌、和弦跳动高亮、扫弦箭头、歌词同步、段落跳转、变速跟练）。
---

# 吉他谱扒谱播放器

## 能力边界

- 产物是**可弹的参考级谱面**：AI 扒谱的和弦切换点可能有小偏差，交付时告知用户可在 SONGS 数据里改 `t` 值（秒）自行校准。
- 仅供个人学习练习，涉及他人作品时提示用户自行处理版权。
- **不转调**：音频保持原曲音质，通过变调夹 + 简单指法适配用户水平（默认用户会 C/G 开放和弦；用户声明会大横按后可用 F/Bm/B）。

## 配套文件

- `scripts/fetch_lrc.py`：双通道抓歌词（酷我 musicId 优先，网易云兜底），输出统一 JSON。
- `scripts/analyze_song.py`：扒谱核心。beat 追踪 + 调内白名单 HMM/Viterbi + 小节制合并，输出原调和弦事件（吸附拍点、最小单位 1 小节）+ 质量指标。依赖 `pip install librosa` 与 ffmpeg。
- `scripts/verify_song.py`：音频-谱面一致性校验（低频频谱根音比对）。**每首必跑**，防"原调标错/文件错配"。
- `scripts/build_songs.py`：按 `songs.json` 配置重建模板 SONGS 数组；指法和弦由程序按 `(原调根音 − capo) mod 12` 自动换算。
- `assets/player_template.html`：播放器模板（含 11 和弦指法图库：C G Am Dm Em A E D + 横按 F Bm B）。
- `scripts/build_player.py`：把音频 base64 注入模板占位符，生成最终单文件 HTML。
- `scripts/validate_player.py`：成品综合校验（占位符/字段/pattern/段落索引/图库覆盖/HTML 闭合）。

## 标准作业流程（SOP）

### 0. 收集素材与先验

- 让用户把音频文件放进项目目录；**酷我下载的 mp3 文件名里的数字是 musicId**，抓歌词用得上。
- 确定每首歌的先验：**原调（根音+大小调）、大约 BPM**。来源：搜索引擎查"歌名 原调/吉他谱"，或播放前 30 秒让用户哼唱确认。原调拿不准时宁可先按候选调跑 analyze+verify，用 verify 不一致率仲裁。

### 1. 抓歌词

```bash
python scripts/fetch_lrc.py --title 歌名 --artist 歌手 [--kuwo-id 358603096] --out lrc_歌名.json
```

### 2. 扒谱

```bash
python scripts/analyze_song.py --audio 歌.mp3 --key-root Bb --key-mode minor --bpm 89 --lrc lrc_歌名.json --out analysis_歌名.json
```

看输出的质量指标：
- `beat相位比 > 1.5` → beat 追踪可信；
- 和弦事件数大致 = 时长(秒)/8 上下（约 2 秒一个和弦），**事件数 >> 该值说明还在抖，不要交付**；
- `歌词行命中率` 仅参考：流行歌人声常落反拍/弱起，50% 上下是正常的，**不要用它判断 beat 质量**。

### 3. 一致性校验（每首必跑，不可跳过）

```bash
python scripts/verify_song.py --audio 歌.mp3 --analysis analysis_歌名.json
```

- MISMATCH < 15% → 通过；
- ≥ 15% → **停下**：截一段 MISMATCH 音频让用户听辨，或换候选原调重跑第 2 步。常见根因：公开资料原调标错、音频文件与歌名不符。

### 4. 定指法方案（变调夹）

目标：指法和弦全部落在用户会按的集合内（默认开放和弦 C G Am Dm Em A E D；会横按后加 F Bm B）。

选法规则：
- 指法根音 = (原调根音 − capo) mod 12。遍历 capo 0-5，优先选"指法调为 Am/Em/C/G/D 系"且 **capo ≤ 4** 的方案（夹太高音色发尖）；
- 小调歌优先 Am/Em 指法；大调歌优先 C/G 指法；
- 参考：原调 ♭B 小调 → Am 指法夹 1 品；B 大调 → G 指法夹 4 品；♭E 大调 → C 指法夹 3 品；♭B 大调 → G 指法夹 3 品；A 大调 → G 指法夹 2 品。
- **换算只信程序**（build_songs.py 自动算），禁止手写映射表。

### 5. 写配置并构建曲库

`songs.json` 每首填：slot/title/artist/originalKey（展示用，如 "♭B 小调"）/fingeringKey（如 "Am"）/capo/shift（展示说明）/bpm/analysis/lyrics/sections/patterns。

- `sections` 段落边界：主歌/预副歌/副歌等的起点，用歌词 JSON 的时间轴辅助定位（副歌第一句歌词时间 ≈ 副歌起点）；pattern 引用本歌 patterns 的 key。
- `patterns`：8 个位置 = 一小节 8 个八分音符，`↓` 下扫 `↑` 上扫 `""` 空拍。默认：verse 叙事轻扫、pre 每拍蓄力、chorus 放开扫。

```bash
python scripts/build_songs.py --config songs.json --template assets/player_template.html --out 曲库_待注入.html
python scripts/build_player.py --template 曲库_待注入.html --out 吉他谱播放器_交付名.html --audio 1=歌1.mp3 --audio 2=歌2.mp3 ...
```

### 6. 成品校验

```bash
python scripts/validate_player.py 吉他谱播放器_交付名.html
```

全部通过才交付；报错（尤其"图库缺和弦"）必须回修——缺图意味着播放器里该和弦无指法图。

### 7. 交付说明必含

- 每首：原调、指法调、变调夹品数；
- 校准方法（改 SONGS 里的 `t` / `patterns` 箭头）；
- 扫弦箭头读法（↓ 下扫、↑ 上扫、· 空拍，8 格一小节）。

## 踩坑检查点（执行时逐条自查）

1. **Windows PowerShell 下禁止内联 python**（含引号/f-string/中文必炸）：一律写脚本文件再 `python 脚本.py`。
2. **转调/换算取模陷阱**：pc 差值必须 `mod 12` 且注意负半音方向；任何手写换算表都要用程序复核。
3. **LRC 元信息污染**：LRC 前部常有"作词/作曲/编曲…"行，参与统计前必须过滤（analyze_song.py 已内置）。
4. **librosa 版本**：0.11 起 `beat_track` 在 `librosa.beat.beat_track`，`chroma_stft` 参数是 `hop_length`（analyze_song.py 已兼容）。
5. **和弦抖动**：帧级/拍级结果直接出事件必然抖动，必须小节制合并（已内置）；交付前看事件数是否合理。
6. **节拍倍频**：beat_track 可能把 65 BPM 检成 129，不影响小节划分，展示时按先验写。
7. **缺图事故**：新出现的和弦名（如 Fmaj7）必须同步进模板 CHORD_DIAGRAMS，validate_player.py 会拦截。
8. **图库与用户的琴技同步**：用户只会开放和弦时不要出现横按；用户学会新和弦（如大横按）后第一时间更新模板图库与本文件第 4 步的可用集合。
9. **大文件构建**：5 首 320k 原曲内嵌约 55MB 属正常；校验脚本以磁盘实际大小为准。

