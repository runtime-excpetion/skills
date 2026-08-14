---
name: music-download-skill
description: 下载歌曲或清除已下载的音乐。当用户要求下载歌曲、搜索音乐、清除已下载的音乐文件时使用。
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
---

# 音乐下载

## 配置

下载目录与默认音质**不硬编码在本 skill 里**,存在配置文件:

路径:`~/.config/music-download-skill/config.json`

```json
{
  "download_path": "/Users/<you>/Music/Downloaded",
  "bit_size": "超品音质"
}
```

| 字段 | 必填 | 含义 |
|---|---|---|
| `download_path` | 是 | 下载目录的绝对路径(下载/清除操作必需);末尾可带斜杠 |
| `bit_size` | 是 | 默认音质的**语义档位名称**,取值见 `reference/api.md` 档位表:标准音质 / 高品音质 / 超品音质 / 无损 / Hi-Res无损 |

`bit_size` 未配置时脚本兜底为 `Hi-Res无损`。音质档位 → API 码率的映射与降级顺序**只**定义在 `reference/api.md`,不要在 SKILL.md 或脚本里重复维护。

首次运行(文件不存在或缺任一字段)时初始化,详见步骤 1。

## 步骤

### 1. 加载或初始化配置

1. 读 `~/.config/music-download-skill/config.json`。
2. 若文件存在且 `download_path`、`bit_size` 均非空,载入之,跳到步骤 2。
3. 否则视为首次运行:**用一次 AskUserQuestion 同时询问两件事**——
   - 下载目录的绝对路径(如 `/Users/<you>/Music/Downloaded`)
   - 默认音质档位(展示 `reference/api.md` 档位表供选择,如「超品音质」)
4. 对下载目录执行 `mkdir -p <download_path>` 验证可创建;创建失败则把错误反馈用户、停下等修正,**不写配置**。
5. 验证通过后,用 Write 工具把两值写回 `~/.config/music-download-skill/config.json`(缩进 2,UTF-8)。可运行 `python3 scripts/download_music.py config ~/.config/music-download-skill/config.json` 自检(退出码 0 = 配置可用)。

**完成条件**:已拿到可用且可创建的 `download_path` 与合法 `bit_size` 档位名,并已持久化到配置文件。

### 2. 搜索歌曲

1. 从用户输入解析搜索意图:歌名、歌手或专辑关键词。
2. 运行:

   ```bash
   python3 scripts/download_music.py search --name "<关键词>" --count 10
   ```

   脚本按 `reference/api.md` 的稳定源顺序逐个请求,第一个返回非空数组的源即结果源;结果中的繁体中文(如 joox 源)会自动转为简体。
3. 退出码 `3` 表示三个稳定源全部无结果 → 告知用户找不到该音乐,停下。

**完成条件**:要么拿到非空搜索结果(含来源源与记录数组),要么已明确告知找不到并停下。

### 3. 过滤与展示选择

1. 若用户指定了歌手、专辑或歌名,在搜索结果上过滤(包含式、忽略大小写):歌手匹配 `artist` 数组任一项,专辑匹配 `album`,歌名匹配 `name`。
2. 过滤后为空 → 告知用户找不到,可建议放宽条件或换关键词。
3. 展示候选,每行格式 `[序号] 歌名 - 歌手(专辑,源)`,最多 10 条;用 AskUserQuestion 让用户选择,或接受用户明确的「第 N 首」。
4. 记下选定记录的 `id`(track_id)、`name`、`artist`(数组)、`source`。

**完成条件**:唯一确定一首歌及其 source/id/name/artists 四要素;否则已明确告知找不到。

### 4. 下载

1. 用选定记录运行:

   ```bash
   python3 scripts/download_music.py download \
     --source <source> --id <track_id> \
     --name "<歌名>" --artist "<歌手1>" [--artist "<歌手2>"] \
     --config ~/.config/music-download-skill/config.json
   ```

   脚本读取配置中的 `download_path` 与 `bit_size`,映射档位到码率,取下载链接、跟随重定向下载,按 **`歌名-歌手.后缀`** 命名(多歌手用 `&` 连接,如 `千里之外-周杰伦&费玉清.mp3`),做文件非空与大小校验后保存到下载目录。文件后缀以 CDN 返回为准。
2. 按退出码处理:
   - `0` → 记录保存路径、实际码率(`br`)、文件大小,进步骤 7。
   - `2` → 指定音质不可用(JSON 含 `reason: "quality_unavailable"`),进步骤 5。
   - `1` → 报告 stderr 错误,停下。

**完成条件**:文件已保存到 download_path 且非空、命名符合规范,或已明确进入音质降级流程。

### 5. 音质降级

1. 告知用户「指定音质(档位名)不可用」,用 AskUserQuestion 询问是否降低音质。
2. 同意 → 重跑下载命令,加 `--degrade`;脚本沿 `reference/api.md` 的降级顺序逐级降到第一个可用档,成功后进步骤 7 汇报。
3. `--degrade` 后仍退出码 `2`(全档不可用)→ 告知用户「该歌曲所有音质均不可用」,停下。
4. 拒绝 → 停止,不下载。

**完成条件**:已下载(可能是降级后的音质),或已明确告知不可用原因。

### 6. 清除下载(独立分支)

用户要求「清除/删除已下载的音乐」时进入本分支,不执行步骤 2~5。

1. 让用户给出要清除的歌曲关键词(歌名/歌手的一部分);未指定时先运行 `list` 展示已下载文件供选择。
2. 先 dry-run 展示将删除的列表:

   ```bash
   python3 scripts/download_music.py clear --keyword "<关键词>" \
     --config ~/.config/music-download-skill/config.json --dry-run
   ```

3. 用户确认后,去掉 `--dry-run` 正式执行。只删 `download_path` **第一层**、文件名包含关键词的**音频文件**,不递归、不删非音频、不删用户自行放入的其他文件。
4. 退出码 `4` = 无匹配文件,告知用户。

**完成条件**:匹配的音频文件已删除,或 dry-run 列表已展示给用户。

### 7. 汇报结果

列出保存的文件路径、音质/码率、大小;清除场景列出已删除的文件。回复仅含这些信息。

**完成条件**:本次操作的全部结果均已向用户报告。

## 安全与限流约束

- **限流**:脚本内置节流(限额见 `reference/api.md`);一次完整流程(搜索 ≤3 + 取链 + 降级重试若干)远低于上限。若脚本连续报「限流(429)」或「响应不是 JSON」,视为触发限流,**停下并提示用户稍后重试**。
- 只写 `download_path`:仅创建下载文件,不修改目录外文件。
- 清除只删匹配的音频文件;关键词为空时拒绝执行(脚本会报错)。
- 文件名仅含歌名与歌手。
- 下载链接指向第三方 CDN,需跟随重定向下载(脚本已处理)。
