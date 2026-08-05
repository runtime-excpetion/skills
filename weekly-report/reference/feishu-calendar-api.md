# 飞书日历 API 调用

本文件是 [`weekly-report`](../SKILL.md) 步骤 2 的披露参考：如何用飞书开放平台 API 拉取指定时间区间的日历日程。

## 前置：凭证

飞书 API 需要应用凭证，从环境变量读取：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

若两者未配置，步骤 2 应停止并提示用户先配置。应用需在飞书开放平台后台开启日历只读权限（scope：`calendar:calendar:readonly`）。

## 调用流程

### a. 获取 tenant_access_token

```bash
curl -s -X POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal \
  -H "Content-Type: application/json" \
  -d "{\"app_id\":\"$FEISHU_APP_ID\",\"app_secret\":\"$FEISHU_APP_SECRET\"}"
```

从返回 JSON 取 `tenant_access_token`。

### b. 拉取主日历日程

主日历的 `calendar_id` 为 `primary`。日程接口的时间参数用 **Unix 秒级时间戳**：

```bash
curl -s -X GET "https://open.feishu.cn/open-apis/calendar/v4/calendars/primary/events?start_time=$START&end_time=$END&page_size=50&page_token=$PAGE_TOKEN" \
  -H "Authorization: Bearer $TOKEN"
```

参数：

- `start_time` / `end_time`：区间起止，Unix 秒级时间戳。
- `page_size`：单页条数，建议 50。
- `page_token`：分页令牌，首次请求省略；后续取上一页返回的 `page_token`。

### c. 处理分页

若返回 `has_more` 为 `true`，用返回的 `page_token` 继续请求，直到 `has_more` 为 `false`，合并所有页的日程。

## 返回字段映射

每条日程取以下字段：

| 周报需要 | 飞书字段 |
|---|---|
| 时间 | `start_time.unix`（Unix 秒级时间戳） |
| 标题 | `summary` |
| 描述 | `description` |
