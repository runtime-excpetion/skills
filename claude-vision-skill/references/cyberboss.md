# Cyberboss 集成

在配置、升级或排查 Cyberboss 图片识别时完整读取本文件。目标是适配用户安装的实际版本，而不是套用固定源码片段。

## 1. 探测当前实现

在 Cyberboss 仓库根目录运行只读搜索：

```bash
rg -n "vision|image|attachment|caption|buildInbound|resolveVision" src package.json .env.example README.md
```

记录以下事实后再修改：

- 图片附件保存在哪里，传递的是绝对路径还是 URL。
- 入站消息在哪个函数中组合。
- 当前版本是否已有视觉服务、caption 模式或 OpenAI 兼容提供商配置。
- persona 文件和状态目录由哪个配置项决定。
- 仓库提供哪些 check、doctor 或 test 命令。

## 2. 选择集成路径

### 当前版本已有原生视觉配置

采用当前版本文档和配置代码中定义的正式环境变量，把模式设为适合文本模型的 caption/描述模式。使用仓库现有实现完成附件读取、接口请求和文本注入；本技能脚本只用于独立诊断。

完成条件：正式配置能被应用读取；源码保持未改；模拟消息为每张图片生成描述。

### 当前版本没有原生视觉配置

1. 把本技能的 `scripts/vision.js` 安装到 Cyberboss 的 `scripts/vision.js`。
2. 按 `references/providers.md` 配置四个通用变量。
3. 在实际 persona 文件中加入 `assets/claude-vision-instructions.md` 的图片处理规则。
4. 在已定位的入站消息组合点加入明确提示：对每张图片执行脚本，收集全部描述后回复。
5. 修改只围绕当前图片消息入口；使用项目现有编码、错误处理和测试模式。

完成条件：`node --check scripts/vision.js` 通过；persona 中的调用路径有效；模拟两张图片时生成两次调用并在两次完成后回复。

## 3. 验证与交付

运行目标仓库自身提供的 check、doctor 和相关测试命令。没有对应脚本时，运行最接近的语法检查和图片消息单元测试。

真实微信测试使用不含敏感信息的小图片，并在用户授权后进行。交付时说明：

- 采用了哪条集成路径以及判断依据。
- 修改了哪些文件和配置名。
- 图片会发送到哪个第三方视觉服务。
- 用户需要执行的重启命令；重启动作完成后配置才生效。

