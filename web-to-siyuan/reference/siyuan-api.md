# 思源笔记 kernel API

本文件是 [`web-to-siyuan`](../SKILL.md) 的披露参考：说明网页到 Markdown 的高保真转换，以及列出笔记本、上传图片、新建文档的接口用法。其中 `createDocWithMd` 的行为以实测为准（官方文档对它的 `path`/`title` 描述有误）。

## 端点与鉴权

- 实例地址与 API token **不硬编码于此**，统一从配置文件 `~/.config/siyuan-clipper/config.json` 读取，字段为 `url`（去掉末尾斜杠）与 `token`。下文用 `$URL`、`$TOKEN` 代指两者的值，所有命令拼接时都从配置取。配置的加载与初始化见 SKILL.md「配置」与步骤 2。
- 方法：除特别说明外均 `POST`，`Content-Type: application/json`
- 鉴权：每个请求都带请求头 `Authorization: Token $TOKEN`。
- 返回统一结构：`{"code":0,"msg":"","data":...}`，`code` 为 `0` 表示成功。`code` 非 0 时 `msg` 为错误原因，多为 token 失效或权限不足。

## 接口

### 列出笔记本 - lsNotebooks

```
POST /api/notebook/lsNotebooks
body: {}
```

返回 `data.notebooks[]`，每项字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | string | 笔记本 ID |
| `name` | string | 笔记本名 |
| `icon` | string | 图标 |
| `sort` | number | 排序值 |
| `sortMode` | number | 文档列表默认排序模式 |
| `closed` | boolean | 是否已关闭（`true` 表示未载入，不可用） |

笔记本与目录的选择见 SKILL.md 步骤 3：优先用本次输入指定的笔记本名，其次配置里的 `notebook`，都没有则取**第一个 `closed` 为 `false` 的笔记本**作兜底；目录取配置里的 `directory`。下文用 `$NB` 代指选中的笔记本 `id`、`$DIR` 代指目录前缀（根目录时为空字符串）。

### 新建文档 - createDocWithMd

```
POST /api/filetree/createDocWithMd
body:
{
  "notebook": "<笔记本ID>",
  "path": "<目录前缀>/<文档名>",
  "markdown": "<Markdown正文>"
}
```

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `notebook` | string | 是 | 目标笔记本 ID（来自 lsNotebooks 的 `id`，即 `$NB`） |
| `path` | string | 是 | 完整文档路径：目录前缀 + `/` + 文档名，最后一段即文档标题，如 `/09-Inbox/文章标题`；存到笔记本根目录时为 `/<文档名>`（即 `$DIR` 为空、直接 `/`+文档名） |
| `markdown` | string | 是 | 文档正文，标准 Markdown |

注意：与官方文档不同，实测此接口**不识别 `title` 字段**——文档名只取自 `path` 的最后一段，传了 `title` 会被忽略且文档落到 `path` 去掉标题后的位置。文档名务必拼进 `path`。

返回 `data` 为字符串，即新文档 ID。用它生成可打开链接：`siyuan://blocks/<data>`。

### 上传图片 - asset/upload

此接口为 `multipart/form-data`（非 JSON）：

```bash
curl -s -X POST $URL/api/asset/upload \
  -H "Authorization: Token $TOKEN" \
  -F "assetsDirPath=/assets" \
  -F "file[]=@<本地文件>"
```

返回 `data.succMap` 为「原文件名 → 资产路径」映射，如 `{"02.png":"assets/02-xxx.png"}`。在 Markdown 中引用：`![](assets/02-xxx.png)`。

⚠️ `assetsDirPath` 固定写 `/assets`：该路径相对思源工作区根目录解析，本实例的工作区目录本身就落在 `data/` 下，写 `/assets` 恰好落在标准资产目录 `data/assets/`，文档中的 `assets/...` 引用可直接解析。

### 正文抽取与图片资产化管线

正文分三种形态，共用一条管线：

| 形态 | 特征 |
|---|---|
| 纯文字 | 正文无 `<img>`，或图片仅为装饰 |
| 图文混排 | 文字段落与图片交织 |
| 全图 | 正文几乎无文字，内容全在图片里（微信公号常见） |

**抓取**。普通网页可先用 WebFetch 判断正文范围。微信公众号必须改用 curl 抓取原始 HTML：带移动端微信 User-Agent 与 `Referer: https://mp.weixin.qq.com/`，正文只取 `id="js_content"` 的完整 DOM 节点，图片真实地址取 `<img>` 的 `data-src`。不得对整页调用 `textContent`，不得用从 `id="js_content"` 到文件末尾的字符串切片；正文结束标签之后紧跟微信防复制脚本，这两种做法都会把脚本带入文章。

微信公众号抓取完成后直接调用 skill 自带脚本：

```bash
python3 scripts/html_to_markdown.py page.html \
  --original-url "https://mp.weixin.qq.com/s/example" \
  --final-url "https://mp.weixin.qq.com/s/example?nwr_flag=1" \
  --output article.md
```

脚本依赖 `lxml` 与 `pandoc`，会确定性完成以下操作：严格截取 `#js_content`；删除 `script/style/template/svg`、隐藏节点和纯空白装饰节点；把图片 `data-src` 提升为 `src`；在 pandoc 前重建 `<pre>` 内由 `<br>` 表示的换行；压缩正文的连续空行；添加原文地址；校验 HTML/Markdown 代码块数量；拒绝含微信页面脚本的结果。脚本失败时停止该链接，不得退回纯文本抽取。

**转 Markdown**。优先对正文 DOM 做 HTML → Markdown 转换，不要先调用 `textContent`、`innerText` 或纯文本抽取后再猜格式。转换时保留标题、段落、列表、引用、表格、分隔线、链接、图片、行内代码和代码块；图片转成 `![](URL)` 引用。

环境中存在 pandoc 时，优先把**正文 DOM 的 HTML 片段**交给 `pandoc --from=html --to=gfm --wrap=none`，并加载 skill 自带的 `scripts/strip_wrappers.lua`，在 Pandoc AST 中移除微信装饰性 Div/Span，同时保留标题、列表、段落等语义；不要把包含导航栏、页脚的整页 HTML 直接转换。pandoc 输出后仍须执行下方的代码块数量与围栏检查，并把围栏语言规范为思源易识别的 `` ```python `` 形式（围栏与语言之间不留空格）。pandoc 不存在或输出检查失败时，按下方 DOM 规则转换。

### 代码块转换

代码必须在通用正文清洗之前处理。推荐流程如下：

1. 在正文 DOM 中查找 `<pre><code>...</code></pre>`、独立 `<pre>...</pre>`，以及常见的 `div.highlight pre`、`div.highlighter-rouge pre`、`figure.highlight pre` 等高亮容器。
2. 对每个代码节点读取其文本内容并解码 HTML 实体，把内部 `<br>` 明确转换成换行符，同时保留行首空格。微信公众号常把代码行写成连续 `<span>` 并用 `<br>` 分隔；直接取纯文本会把整块代码压成一行。只移除由 HTML 排版本身引入的单个首尾空行；不要 `trim` 每一行、折叠连续空格或合并换行。
3. 从以下位置依次识别语言：`code` 的 `class="language-*"` / `class="lang-*"`、容器的 `data-lang` / `data-language`、高亮器类名、紧邻的代码标题。规范常见别名，如 `js`、`ts`、`py`、`sh`、`shell`、`html`、`css`、`json`、`yaml`、`sql`、`java`、`go`、`rust`、`cpp`。无法可靠判断时留空，不要臆测。
4. 先用不可与正文冲突的占位符替换代码节点，再处理其余 HTML，最后把占位符恢复成 Markdown 代码块。这样可以避免段落归一化、图片资产化或 Markdown 转义破坏代码。
5. 围栏长度必须大于代码内容中连续反引号的最大长度，且至少为 3。例如代码内已有三个连续反引号时，外层使用四个反引号；也可改用长度足够的 `~` 围栏。
6. 围栏前后各保留一个空行：

   ````markdown
   ```python
   def hello():
       print("hello")
   ```
   ````

7. `<code>` 不在 `<pre>` 内时转为行内代码。若内容自身含反引号，使用更长的反引号定界并在必要时在内容两侧加空格。

不要把代码块内的 `#`、`-`、`*`、`[]()`、HTML 标签或图片样式文本当作正文 Markdown 再解析；也不要下载或改写代码块里的图片 URL。

转换完成后，比较正文 DOM 中的代码块数与 Markdown fenced code block 数。两者不一致，或 `<code>` 中含换行但输出没有围栏时，判为转换失败并重走原始 HTML 管线。

**图片资产化**。对每处图片引用，下载原图（沿用抓取时的请求头；外链有防盗链、容易失效，故转存为资产），经 `asset/upload` 上传（`assetsDirPath=/assets`），把引用改写为 `![](assets/<资产文件名>)`，保持原序。上传会给文件加时间戳后缀、每次文件名都不同——引用必须取本次 `succMap` 返回的实际文件名。无法下载的图片保留原外链并在汇报中说明。

**形态校验**。转完 Markdown 后判断形态：图文混排按原结构组合（文字段落与图片引用交织）；若正文除页码占位、空白外无实质文字而页面确有图片，按全图处理——正文只保留按序的图片引用。

**空白校验**。DOM 转换前删除只包含 `<br>`、`&nbsp;`、零宽字符或变体选择符的装饰块；Markdown 转换后把空白字符行归一为空行，并把连续空行压成一个。不要修改 fenced code block 内的空行。来源区块与首段正文之间只保留一个空行。

**尾部校验**。Markdown 中出现 `document.getElementById('js_content')`、`document.addEventListener`、`selectstart` 等微信页面脚本特征时，说明正文选择范围越过 `#js_content`，必须判为失败并重新按 DOM 节点提取；不要仅从尾部猜测截断位置。

### 来源信息组装

抓取开始时保存用户输入的 URL 为 `original_url`，不得让 HTTP 重定向结果覆盖它。Markdown 正文必须以以下区块开头：

```markdown
> 原文地址：[https://example.com/article](<https://example.com/article>)
```

链接文本与目标都使用完整的 `original_url`，链接目标外层使用尖括号，避免 URL 中的括号破坏 Markdown。若 `final_url` 不同，在下一行增加 `> 最终地址：[{final_url}](<{final_url}>)`。来源区块后空一行，再写正文。

## 验证

确认思源实例可访问，跑以下命令自测（把 `$URL`、`$TOKEN` 换成配置里的实际值）：

```bash
curl -s -X POST $URL/api/notebook/lsNotebooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d '{}'
```

返回 `{"code":0,"data":{"notebooks":[...]}}` 即连通正常。鉴权错误（`code` 非 0）则确认 token 与访问授权码设置。
