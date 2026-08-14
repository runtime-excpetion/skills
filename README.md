# Skills

本项目用于集中存放和维护可供 AI 助手调用的技能（Skills）。每个 Skill 位于独立目录中，通过 `SKILL.md` 描述触发条件、执行步骤、工具权限和完成标准；部分 Skill 还包含 `reference/` 等补充资料目录。

## 项目结构

```text
skills/
├── claude-vision-skill/  # 为无原生识图能力的运行时配置 OpenAI 兼容图片识别
├── docker-deploy/        # 用 Docker Compose 规范部署服务
├── music-download-skill/ # 从 gdstudio 音乐接口搜索并下载歌曲到本地目录
├── web-to-siyuan/        # 将网页内容剪藏到思源笔记
├── weekly-report/        # 根据飞书日历生成工作周报
└── writing-great-skills/ # 编写和优化 Skills 的方法论参考
```

## Skills 说明

### claude-vision-skill

为缺少原生识图能力的 Claude Code、Cyberboss 或其他 Agent 运行时配置 OpenAI 兼容图片识别。该 Skill 通过 `scripts/vision.js` 将本地图片或图片 URL 发送给 OpenAI Chat Completions 兼容的视觉模型，并支持本地图片、远程图片、多图片处理，以及认证、端点、模型和超时错误的排查。

凭据通过 `VISION_API_KEY`、`VISION_MODEL`、`VISION_BASE_URL` 环境变量提供，不写入 Skill 文件。使用方式、配置要求和排障流程见 [`claude-vision-skill/SKILL.md`](claude-vision-skill/SKILL.md)。

### docker-deploy

用 Docker Compose 规范部署一个服务。该 Skill 会在默认部署目录（首次运行时询问并保存）下为服务建项目目录，生成 `docker-compose.yml`，扫描现有所有容器的宿主端口占用、从 8000 起分配空闲端口，以 bridge 网络启动，并汇报容器名、运行状态与端口映射。挂载卷遵循项目目录内用 `./` 相对路径、目录外用绝对路径的规范。

默认部署目录与配置方式见 [`docker-deploy/SKILL.md`](docker-deploy/SKILL.md)。

### music-download-skill

通过 gdstudio 音乐聚合接口(`https://music-api.gdstudio.xyz/api.php`)搜索歌曲并下载到本地目录。该 Skill 按稳定源顺序自动回退(`netease → joox → kuwo`)，支持语义音质档位(标准/高品/超品/无损/Hi-Res无损)、音质不可用时逐级降级、按「歌名-歌手」命名(繁体自动转简体)，以及按歌曲关键词清除已下载文件。

下载目录、默认音质由本地配置提供，不写入 Skill 文件；API 端点、音质档位映射与限流规则见 [`music-download-skill/reference/api.md`](music-download-skill/reference/api.md)。

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
