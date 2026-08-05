# Skills

本项目用于集中存放和维护可供 AI 助手调用的技能（Skills）。每个 Skill 位于独立目录中，通过 `SKILL.md` 描述触发条件、执行步骤、工具权限和完成标准；部分 Skill 还包含 `reference/` 等补充资料目录。

## 项目结构

```text
skills/
├── web-to-siyuan/        # 将网页内容剪藏到思源笔记
├── weekly-report/        # 根据飞书日历生成工作周报
└── writing-great-skills/ # 编写和优化 Skills 的方法论参考
```

## Skills 说明

### web-to-siyuan

将一个或多个网页链接剪藏到思源笔记。该 Skill 会抓取网页正文并转换为 Markdown，下载和上传文章图片，然后通过思源笔记 Kernel API 在指定笔记本及目录中创建独立文档。

思源实例地址、API token、默认笔记本和目标目录由本地配置提供，不写入 Skill 文件。具体配置方式和处理流程见 [`web-to-siyuan/SKILL.md`](web-to-siyuan/SKILL.md)。

### weekly-report

根据指定时间范围内的飞书日历日程生成工作周报。该 Skill 会读取日程的时间、标题和描述，按开始时间排序，并根据内容标注“需求开发”“运维处理”“资料整理”等类别，最终输出结构化周报。

飞书接口的凭证要求、调用方式和字段映射见 [`weekly-report/SKILL.md`](weekly-report/SKILL.md) 与 [`weekly-report/reference/feishu-calendar-api.md`](weekly-report/reference/feishu-calendar-api.md)。

### writing-great-skills

提供编写和优化 Skills 的方法论参考，涵盖触发方式、描述设计、信息层级、渐进式披露、拆分原则、内容精简和常见失败模式等内容。

该 Skill **不是本项目原创**，引用自 Matt Pocock 的开源 Skills 项目：

- 上游来源：[mattpocock/skills - writing-great-skills](https://github.com/mattpocock/skills/tree/main/skills/productivity/writing-great-skills)
- 本地文件：[`writing-great-skills/SKILL.md`](writing-great-skills/SKILL.md)

如需了解原始内容、后续更新或相关授权信息，请以上游项目为准。

## 使用说明

使用某个 Skill 时，应先阅读对应目录中的 `SKILL.md`，并根据其中的前置条件配置所需凭证、服务地址或工具。包含 token、应用密钥等敏感信息的本地配置不应提交到本项目中。
