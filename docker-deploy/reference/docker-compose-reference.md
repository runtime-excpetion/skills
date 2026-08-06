# Docker Compose 部署参考

本文件是 [`docker-deploy`](../SKILL.md) 的 disclosed reference，收录端口扫描命令、compose 文件模板与状态查询命令的细节。`SKILL.md` 中的规范（挂载路径规则、bridge 网络、从 8000 起分配端口）是权威定义；本文件只给落地用的命令与模板，规范有冲突时以 `SKILL.md` 为准。

## 端口扫描与分配

### 列出所有容器及其端口映射

```bash
docker ps -a --format '{{.Names}}\t{{.Ports}}'
```

`Ports` 列形如 `0.0.0.0:8080->80/tcp, :::0.0.0.0:8080->80/tcp`，或为空（容器未映射端口）。

### 解析已占用的宿主端口

从每行 `Ports` 中提取所有 `宿主端口->` 段里的宿主端口（`:` 后、`->` 前的数字），去重得到已占用集合。例如上例得到 `{8080}`。

### 探测空闲端口

从 8000 起逐个判断是否落在已占用集合：

- 未占用 → 选定该端口。
- 已占用 → 递增到下一个，直到找到空闲。

每个需要暴露的容器端口独立跑一遍上述探测，避免本次服务内部端口互相冲突。

## docker-compose.yml 模板

以下模板体现 `SKILL.md` 的挂载与网络规范，按服务实际需要裁剪：

```yaml
services:
  <service>:
    image: <image>:<tag>
    container_name: <service>
    restart: unless-stopped
    ports:
      - "<host_port>:<container_port>"
    volumes:
      # 项目目录内：相对路径
      - ./config:/app/config
      - ./data:/app/data
      # 项目目录外：绝对路径
      - /etc/localtime:/etc/localtime:ro
    environment:
      - KEY=value
    # network 默认即为 bridge，无需写 network_mode
```

要点（规范的权威定义见 SKILL.md「步骤 4」，本节仅说明模板如何落地）：

```yaml
networks:
  default:
    name: <service>-net
```

## 启动与状态查询

### 启动

在项目目录下（与 `docker-compose.yml` 同级）执行：

```bash
docker compose up -d
```

`-d` 后台运行，首次会拉取镜像。失败时输出完整日志供排查。

### 查询状态与端口

```bash
docker compose ps
# 或按容器名过滤
docker ps --filter "name=<service>" --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
```

`Status` 形如 `Up 2 minutes`、`Exited (1) 5 seconds ago`。`Ports` 同上文格式。汇报时把 `宿主端口->容器端口` 整理成「宿主端口 → 容器端口」呈现给用户。
