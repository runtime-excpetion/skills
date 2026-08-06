---
name: docker-deploy
description: 用 Docker Compose 规范部署一个服务。当用户要求用 Docker 或 Docker Compose 部署某个服务时使用：在默认部署目录下生成 docker-compose.yml、从 8000 起分配空闲宿主端口、以 bridge 网络启动，并汇报容器名、运行状态与端口映射。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - AskUserQuestion
---

# Docker Compose 规范部署

用 **Docker Compose** 把一个服务规范地跑起来：在统一的**默认部署目录**下为该服务建一个项目目录，生成 `docker-compose.yml`，按规则分配宿主端口，启动后汇报容器名、运行状态和端口映射。

## 配置

默认部署目录（所有 Docker 项目的根目录）**不硬编码在本 skill 里**，存在配置文件：

路径：本技能目录下的 `reference/config.json`

```json
{
  "deploy_root": "/opt/docker"
}
```

| 字段 | 必填 | 含义 |
|---|---|---|
| `deploy_root` | 是 | Docker 项目根目录的绝对路径，每个服务在其下建子目录；末尾不带斜杠 |

首次运行（配置文件不存在或缺 `deploy_root`）时向用户询问并保存，详见步骤 1。

## 步骤

### 1. 加载或初始化默认部署目录

1. 读本技能目录下的 `reference/config.json`。
2. 若文件存在且 `deploy_root` 非空，载入之，跳到步骤 2。
3. 否则视为首次运行，用 AskUserQuestion 询问用户默认部署根目录的绝对路径（如 `/opt/docker`）。
4. 拿到后 `mkdir -p <deploy_root>` 确认可创建；创建失败则把错误反馈用户、停下等修正。成功后把 `deploy_root` 写入 `reference/config.json`（去掉末尾斜杠）。

**完成条件**：已拿到可用的 `deploy_root` 绝对路径并持久化到配置文件。

### 2. 确定服务名与项目目录

从用户输入或镜像名确定本次部署的**服务名**（用作项目目录名与容器名，小写、连字符分隔，如 `gitea`、`vaultwarden`）。项目目录 = `deploy_root` + `/` + 服务名。

若项目目录已存在，提示用户选择**复用既有配置**还是**改名新建**。

**完成条件**：已确定服务名与项目目录路径，且与既有部署不冲突。

### 3. 扫描已占用端口并分配宿主端口

收集本机**所有现有容器**（运行中与已停止）的宿主端口映射，从中挑出空闲端口分配给本次服务。

端口分配规则：

- 从 **8000** 起逐个递增，取第一个未被占用的宿主端口。
- 占用判定：`docker ps -a` 输出里任何 `宿主端口->...` 映射都算占用，不区分容器运行状态。
- 每个需要对外暴露的容器端口都要分配一个宿主端口，各自独立探测，彼此不冲突。
- 记下「容器端口 → 选定宿主端口」的对应表，供下一步写入 compose。

扫描命令与端口解析细节见 `reference/docker-compose-reference.md`。

**完成条件**：本次服务需要暴露的每个容器端口都已分配到互不冲突、且不与现有任何容器冲突的宿主端口。

### 4. 生成 docker-compose.yml

在项目目录下创建 `docker-compose.yml`，遵循以下**挂载与网络规范**：

挂载卷规范：

- 持久化数据放项目目录内，用 `./` 相对路径挂载（相对 compose 文件所在目录），如挂载配置目录写 `./config:/app/config`。
- 必须引用项目目录**之外**的文件或目录时，用**绝对路径**，如 `/etc/localtime:/etc/localtime:ro`。

网络规范：

- 使用 **bridge** 网络（Compose 默认行为），即默认网络，满足隔离与端口映射；不得使用 `network_mode: host`。
- 多服务需互通时显式定义命名 bridge 网络并让相关服务加入，仍属 bridge 类型。

端口映射写作：`"<步骤 3 分配的宿主端口>:<容器端口>"`。`container_name` 写服务名。镜像、环境变量、重启策略、健康检查、数据卷等按服务实际需要补齐；完整模板见 `reference/docker-compose-reference.md`。

写完后做一次自检：YAML 语法有效、挂载路径与上述规范一致、端口映射与步骤 3 结果一致。

**完成条件**：项目目录下存在一份符合挂载与网络规范、端口映射与步骤 3 一致、YAML 语法有效的 `docker-compose.yml`。

### 5. 启动容器

在项目目录下执行 `docker compose up -d` 拉取镜像并后台启动。启动失败则输出完整错误日志并停下，交由用户修正后重试。

**完成条件**：`docker compose up -d` 成功返回，容器已创建。

### 6. 汇报运行状态与端口映射

启动后取以下三项汇报给用户：

- **容器名**
- **运行状态**（`Up` / `Exited (code)` / `Restarting` 等）
- **端口映射**（宿主端口 → 容器端口）

用 `docker compose ps` 或 `docker ps --filter "name=<服务名>"` 取信息，命令见 `reference/docker-compose-reference.md`。

**完成条件**：本次部署的容器名、运行状态、端口映射均已报告给用户。
