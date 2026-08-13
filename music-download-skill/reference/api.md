# GD 音乐台聚合接口(API 参考)

本文件是 music-download-skill 的披露参考:记录 gdstudio 音乐聚合接口的端点、参数、返回结构、音质档位、源顺序与限流规则。执行搜索与下载步骤时按需查阅。

## 基本信息

- Base URL:`https://music-api.gdstudio.xyz/api.php`,全部 GET 请求,返回 JSON。
- **限流:5 分钟内最多 50 次请求**,超限可能返回 429 或非 JSON 页面。
- 查询参数必须 **URL 编码**:`track_id` 含 base64 字符(`+` `/` `=`),关键词可能是中文。
- 下载链接指向第三方 CDN,需**跟随重定向**下载。

## 端点

### 搜索

```
GET /api.php?types=search&source=<源>&name=<关键词>&count=<每页数>&pages=<页码>
```

| 参数 | 必填 | 含义 |
|---|---|---|
| `source` | 否 | 音乐源,默认 `netease`;见「源顺序」 |
| `name` | 是 | 关键词,可为歌名/歌手/专辑 |
| `count` | 否 | 每页条数,默认 20 |
| `pages` | 否 | 页码,默认 1 |

返回:**顶层 JSON 数组**;`[]` = 无结果。每条记录字段:

| 字段 | 含义 |
|---|---|
| `id` | **track_id**,下载必须 |
| `name` | 歌名 |
| `artist` | **字符串数组**,如 `["周杰伦"]` |
| `album` | 专辑名 |
| `pic_id` | 封面用 |
| `url_id` | 已废弃,忽略 |
| `lyric_id` | 歌词用 |
| `source` / `from` | 来源 |

### 获取下载链接

```
GET /api.php?types=url&source=<源>&id=<track_id>&br=<码率>
```

| 参数 | 必填 | 含义 |
|---|---|---|
| `id` | 是 | 搜索返回的 `track_id` |
| `br` | 否 | 码率,128/192/320/740/999,默认 999 |

返回:`{"url": "...", "br": 实际码率, "size": 文件大小, "from": "music.gdstudio.xyz"}`

- **`url` 为空字符串或 `br == -1` → 该音质不可用**(音质降级的触发信号)。
- `br` 取实际返回,可能与请求值不同(如请求 740 可能返回 999)。
- `size` **实测为字节**、非文档声称的 KB;下载后按字节做大小校验。

### 封面(本 skill 主流程不使用)

```
GET /api.php?types=pic&source=<源>&id=<pic_id>&size=300|500
```

返回 `{"url": "..."}`。

### 歌词(本 skill 主流程不使用)

```
GET /api.php?types=lyric&source=<源>&id=<lyric_id>
```

返回 `{"lyric": "...", "tlyric": "..."}`。

## 音质档位 → br 映射(含降级顺序)

`bit_size` 配置存**语义档位名称**(即下表第一列),脚本内部映射到 API 的 `br` 数字:

| 档位名称 | br | 期望格式 |
|---|---|---|
| 标准音质 | 128 | mp3 |
| 高品音质 | 192 | m4a/mp3 |
| 超品音质 | 320 | mp3 |
| 无损 | 740 | flac |
| Hi-Res无损 | 999 | flac |

**降级顺序**(从当前档位逐级向下,到底为止):

```
999 → 740 → 320 → 192 → 128
```

即:Hi-Res无损 → 无损 → 超品 → 高品 → 标准。指定档位不可用时,按此顺序降一档重试。

**实际文件后缀以 CDN 返回为准**,推断优先级:URL 路径扩展名 > Content-Type > 按 br 兜底(≥740 → `.flac`,否则 `.mp3`)。实测:320 → `.mp3`、192 → `.m4a`、740/999 → `.flac`。

## 源顺序与可用性

稳定源顺序:`netease → joox → bilibili`。搜索时按此顺序逐个请求,**第一个返回非空数组的源**即结果源。

- `netease`:实测常返回 `[]`(中文英文均空),不稳定。
- `joox`:实测可靠,中文搜索有效。
- `bilibili`:偶发返回 503 HTML 页面(非 JSON)。
- `tencent`、`apple` 等返回 `{"detail": "Value of `source` is not supported."}`。

搜索策略:某源返回空数组、非 JSON、或报不支持,视为该源无结果,继续下一个源;全部源无结果才判「找不到」。

## curl 示例

```bash
# 搜索(joox 中文)
curl 'https://music-api.gdstudio.xyz/api.php?types=search&source=joox&name=%E4%B8%83%E9%87%8C%E9%A6%99&count=10&pages=1'

# 取下载链接(id 需 URL 编码)
curl 'https://music-api.gdstudio.xyz/api.php?types=url&source=joox&id=ak_B61XhYbmYujcR%2B7OEHw%3D%3D&br=320'

# 音质不可用样例(假 id → url 为空、br=-1)
curl 'https://music-api.gdstudio.xyz/api.php?types=url&source=joox&id=FAKE_ID&br=999'
# → {"url":"","br":-1,"size":0}

# 下载(跟随重定向)
curl -L -o '七里香-周杰倫.mp3' '<上一步返回的 url>'
```
