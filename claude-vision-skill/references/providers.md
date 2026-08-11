# OpenAI 兼容视觉服务配置

在配置服务、直接识图或排查接口错误时读取本文件。

## 变量契约

| 变量 | 要求 |
|---|---|
| `VISION_API_KEY` | 必填；只存于环境或秘密管理器 |
| `VISION_MODEL` | 必填；模型必须接受 Chat Completions 图片消息 |
| `VISION_BASE_URL` | 必填；API 根路径，不含 `/chat/completions` |
| `VISION_TIMEOUT_MS` | 可选；整数 `1000`–`120000`，默认 `30000` |

脚本接受 HTTPS API 根路径。本机自动化测试额外接受 `localhost`、`127.0.0.1` 或 `::1` 的 HTTP 地址。

## 安全配置

在 zsh 中交互读取 Key，避免把值写入命令历史：

```bash
read -rs "VISION_API_KEY?请输入视觉服务 API Key: "
echo
export VISION_API_KEY
export VISION_MODEL="<支持图片输入的模型名>"
export VISION_BASE_URL="https://<服务域名>/<兼容接口根路径>"
```

使用阿里云百炼兼容接口时，Base URL 示例为：

```bash
export VISION_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

模型名和可用范围以账户控制台为准。使用其他提供商时，采用其 OpenAI Chat Completions 兼容根路径。

需要持久化时，优先使用系统秘密管理器。项目环境文件应满足：已加入 `.gitignore`、权限为 `600`、由宿主显式加载。脚本本身不读取 `.env`。

## 离线验证

只检查变量状态，不打印值：

```bash
for name in VISION_API_KEY VISION_MODEL VISION_BASE_URL; do
  if [[ -n "${(P)name}" ]]; then
    echo "$name: 已设置"
  else
    echo "$name: 未设置"
  fi
done
node --check scripts/vision.js
```

## 错误分类

| 症状 | 首要检查 | 安全验证 |
|---|---|---|
| 启动即报告缺少变量 | 宿主进程是否继承环境 | 只输出变量“已设置/未设置” |
| `401` / `403` | Key 所属服务、权限和有效期 | 在服务控制台核对，不回显 Key |
| `404` | Base URL 是否误含 `/chat/completions` | 打印不含凭据的 URL 路径 |
| `400` / 模型错误 | 模型是否支持图片消息与兼容接口 | 核对控制台模型标识 |
| 请求超时 | 网络、服务延迟、图片大小 | 先用小型非敏感图片；按需提高超时 |
| 响应结构错误 | 服务是否返回标准 `choices[0].message.content` | 保存脱敏后的状态码和 request ID |

真实识图会把图片内容发送给第三方服务。配置和排障阶段保持离线；用户明确要求分析图片时再执行真实请求。

