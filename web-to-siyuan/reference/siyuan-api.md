# 思源笔记 kernel API

本文件是 [`web-to-siyuan`](../SKILL.md) 的披露参考：列出笔记本、上传图片、新建文档的接口用法。其中 `createDocWithMd` 的行为以实测为准（官方文档对它的 `path`/`title` 描述有误）。

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

**抓取**。先 WebFetch；返回验证页或内容残缺（反爬站点常见）时，改用 curl 抓取：微信公号链接带移动端微信 User-Agent 与 `Referer: https://mp.weixin.qq.com/` 头可绕过验证页，正文在 `id="js_content"` 容器内，图片真实地址在 `<img>` 的 `data-src` 属性。

**转 Markdown**。HTML 转 Markdown 时（pandoc / html 解析），文字按原样保留，图片转成 `![](URL)` 引用。

**图片资产化**。对每处图片引用，下载原图（沿用抓取时的请求头；外链有防盗链、容易失效，故转存为资产），经 `asset/upload` 上传（`assetsDirPath=/assets`），把引用改写为 `![](assets/<资产文件名>)`，保持原序。上传会给文件加时间戳后缀、每次文件名都不同——引用必须取本次 `succMap` 返回的实际文件名。无法下载的图片保留原外链并在汇报中说明。

**形态校验**。转完 Markdown 后判断形态：图文混排按原结构组合（文字段落与图片引用交织）；若正文除页码占位、空白外无实质文字而页面确有图片，按全图处理——正文只保留按序的图片引用。

## 验证

确认思源实例可访问，跑以下命令自测（把 `$URL`、`$TOKEN` 换成配置里的实际值）：

```bash
curl -s -X POST $URL/api/notebook/lsNotebooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d '{}'
```

返回 `{"code":0,"data":{"notebooks":[...]}}` 即连通正常。鉴权错误（`code` 非 0）则确认 token 与访问授权码设置。
