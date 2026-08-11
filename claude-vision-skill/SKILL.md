---
name: claude-vision-skill
description: 视觉代理，用于给缺少原生识图能力的 Claude Code、Cyberboss 或其他 Agent 运行时配置 OpenAI 兼容图片识别；也用于调用本地或远程图片分析脚本，或排查认证、端点、模型和超时错误。
---

# Claude Vision 代理

用 `scripts/vision.js` 把图片发送给 OpenAI Chat Completions 兼容的视觉模型，再把文字结果交给当前运行时。把凭据留在环境中，把图片发送范围和真实 API 调用保持在用户授权内。

## 执行步骤

1. 确认目标运行时是否已有原生视觉能力。已有且用户没有要求代理时，使用原生能力并结束；缺少原生视觉能力或用户明确要求代理时继续。
2. 选择分支并读取对应资源：
   - 配置普通 Claude Code 项目：读取 `references/providers.md`，复制 `scripts/vision.js` 和 `assets/claude-vision-instructions.md`。
   - 配置或升级 Cyberboss：必须读取 `references/cyberboss.md`，先探测目标版本再选集成路径。
   - 直接分析图片：读取 `references/providers.md`；现有环境变量有效时调用本技能脚本。
   - 排查 401、404、模型、响应或超时错误：读取 `references/providers.md`，按错误类别验证，不输出凭据值。
3. 在目标项目中把脚本安装为 `scripts/vision.js`，保留可执行权限。合并 Claude 指令时保留项目已有规则，只添加图片处理段落。
4. 配置 `VISION_API_KEY`、`VISION_MODEL`、`VISION_BASE_URL`；需要调整超时时再设置 `VISION_TIMEOUT_MS`。使用宿主 shell、秘密管理器或被版本控制忽略且权限受限的环境文件。
5. 先运行离线验证：

   ```bash
   node --check scripts/vision.js
   node --test tests/vision.test.js
   ```

   目标项目只复制运行脚本时，至少运行 `node --check scripts/vision.js`，并只报告每个必填变量“已设置/未设置”。
6. 用户要求实际分析图片时，该请求即授权一次真实接口调用；配置或排障请求不包含真实调用授权。真实调用前说明图片会发送给所选服务并可能产生费用。
7. 按分支完成条件交付结果。

## 调用

```bash
node scripts/vision.js "/absolute/path/to/image.png" "请用中文描述这张图片"
node scripts/vision.js --url "https://example.com/image.png" "请用中文描述这张图片"
```

脚本成功时只在 stdout 输出识别结果；失败时在 stderr 输出错误类别并返回非零退出码。

## 完成条件

- 普通项目：脚本语法通过，三个必填变量均已设置，项目指令覆盖本地图片、附件列表和多图片处理。
- 直接分析：每张图片都有对应识别结果，失败项按图片单独标明，回复中不含凭据。
- Cyberboss：已识别目标版本和图片处理入口，采用该版本支持的集成路径，并完成模拟多图片消息检查。
- 排障：已定位到配置、文件、网络、HTTP 状态或响应结构中的具体类别，并给出不泄露凭据的下一条验证命令。

