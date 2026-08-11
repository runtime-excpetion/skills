#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const https = require("node:https");

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 30_000;
const MIN_TIMEOUT_MS = 1_000;
const MAX_TIMEOUT_MS = 120_000;
const DEFAULT_PROMPT = "请详细描述这张图片的内容。";

const MIME_TYPES = Object.freeze({
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".bmp": "image/bmp",
});

function parseArgs(argv) {
  let source = "";
  let isUrl = false;
  const promptParts = [];

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--url") {
      const url = argv[index + 1];
      if (source) throw new Error("只能指定一个图片来源。");
      if (!url || url.startsWith("--")) throw new Error("--url 后缺少图片 URL。");
      source = url;
      isUrl = true;
      index += 1;
      continue;
    }
    if (argument.startsWith("--")) throw new Error(`未知参数: ${argument}`);
    if (!source) {
      source = argument;
    } else {
      promptParts.push(argument);
    }
  }

  if (!source) throw new Error("缺少图片来源。");
  return {
    source,
    isUrl,
    prompt: promptParts.join(" ").trim() || DEFAULT_PROMPT,
  };
}

function loadConfig(env) {
  const required = ["VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL"];
  const missing = required.filter((name) => !String(env[name] || "").trim());
  if (missing.length) throw new Error(`缺少环境变量: ${missing.join(", ")}`);

  let endpoint;
  try {
    endpoint = new URL(String(env.VISION_BASE_URL).trim());
  } catch {
    throw new Error("VISION_BASE_URL 不是有效 URL。");
  }
  const loopback = ["127.0.0.1", "localhost", "::1"].includes(endpoint.hostname);
  if (endpoint.protocol !== "https:" && !(endpoint.protocol === "http:" && loopback)) {
    throw new Error("VISION_BASE_URL 必须使用 HTTPS（本机回环测试除外）。");
  }
  if (endpoint.username || endpoint.password) {
    throw new Error("VISION_BASE_URL 不得包含用户名或密码。");
  }

  const rawTimeout = env.VISION_TIMEOUT_MS || DEFAULT_TIMEOUT_MS;
  const timeoutMs = Number(rawTimeout);
  if (!Number.isInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS || timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error(`VISION_TIMEOUT_MS 必须是 ${MIN_TIMEOUT_MS} 到 ${MAX_TIMEOUT_MS} 之间的整数。`);
  }

  return {
    apiKey: String(env.VISION_API_KEY).trim(),
    model: String(env.VISION_MODEL).trim(),
    baseUrl: endpoint.toString().replace(/\/$/, ""),
    timeoutMs,
  };
}

function resolveImageSource(source, isUrl) {
  if (isUrl) {
    let imageUrl;
    try {
      imageUrl = new URL(source);
    } catch {
      throw new Error("图片 URL 无效。");
    }
    if (imageUrl.protocol !== "https:") throw new Error("图片 URL 必须使用 HTTPS。");
    if (imageUrl.username || imageUrl.password) throw new Error("图片 URL 不得包含凭据。");
    return imageUrl.toString();
  }

  const resolved = path.resolve(source);
  if (!fs.existsSync(resolved)) throw new Error(`文件不存在: ${resolved}`);
  const stat = fs.statSync(resolved);
  if (!stat.isFile()) throw new Error(`图片路径不是文件: ${resolved}`);

  const extension = path.extname(resolved).toLowerCase();
  const mimeType = MIME_TYPES[extension];
  if (!mimeType) {
    throw new Error(`不支持的图片格式: ${extension || "无扩展名"}。支持: ${Object.keys(MIME_TYPES).join(", ")}`);
  }
  if (stat.size > MAX_IMAGE_BYTES) {
    throw new Error(`图片超过 20 MiB: ${stat.size} 字节。`);
  }

  const data = fs.readFileSync(resolved);
  return `data:${mimeType};base64,${data.toString("base64")}`;
}

function buildPayload(imageUrl, prompt, model) {
  return {
    model,
    messages: [
      {
        role: "user",
        content: [
          { type: "image_url", image_url: { url: imageUrl } },
          { type: "text", text: prompt },
        ],
      },
    ],
    stream: false,
    max_tokens: 1024,
  };
}

function redact(text, secrets) {
  let result = String(text || "");
  for (const secret of secrets) {
    if (secret) result = result.split(secret).join("[REDACTED]");
  }
  return result.replace(/[\r\n\t]+/g, " ").trim().slice(0, 300);
}

function safeErrorSummary(raw, apiKey) {
  let message = "";
  try {
    const parsed = JSON.parse(raw);
    message = parsed?.error?.message || parsed?.message || "";
  } catch {
    message = raw;
  }
  return redact(message, [apiKey]);
}

function requestVision(payload, config) {
  const endpoint = new URL(`${config.baseUrl}/chat/completions`);
  const body = JSON.stringify(payload);
  const transport = endpoint.protocol === "https:" ? https : http;

  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      callback(value);
    };

    const req = transport.request(
      endpoint,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${config.apiKey}`,
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let raw = "";
        let bytes = 0;
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          bytes += Buffer.byteLength(chunk);
          if (bytes > MAX_RESPONSE_BYTES) {
            res.destroy(new Error("上游响应超过 2 MiB 限制。"));
            return;
          }
          raw += chunk;
        });
        res.on("error", (error) => finish(reject, error));
        res.on("end", () => {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            const requestId = redact(res.headers["x-request-id"] || "", []);
            const summary = safeErrorSummary(raw, config.apiKey);
            const details = [requestId && `request_id=${requestId}`, summary].filter(Boolean).join("; ");
            finish(reject, new Error(`上游 API 返回 ${res.statusCode}${details ? `: ${details}` : ""}`));
            return;
          }

          let parsed;
          try {
            parsed = JSON.parse(raw);
          } catch {
            finish(reject, new Error("上游响应不是有效 JSON。"));
            return;
          }
          const content = parsed?.choices?.[0]?.message?.content;
          if (typeof content !== "string") {
            finish(reject, new Error("上游响应缺少 choices[0].message.content。"));
            return;
          }
          finish(resolve, content);
        });
      }
    );

    req.setTimeout(config.timeoutMs, () => {
      req.destroy(new Error(`请求超时（${config.timeoutMs}ms）。`));
    });
    req.on("error", (error) => {
      const message = redact(error.message, [config.apiKey]);
      const normalized = message.includes("请求超时") ? message : `网络请求失败: ${message}`;
      finish(reject, new Error(normalized));
    });
    req.write(body);
    req.end();
  });
}

async function runCli(argv, env, io = process) {
  try {
    const config = loadConfig(env);
    const { source, isUrl, prompt } = parseArgs(argv);
    const imageUrl = resolveImageSource(source, isUrl);
    const result = await requestVision(buildPayload(imageUrl, prompt, config.model), config);
    io.stdout.write(`${result}\n`);
    return 0;
  } catch (error) {
    io.stderr.write(`识图失败: ${error.message}\n`);
    return 1;
  }
}

if (require.main === module) {
  runCli(process.argv.slice(2), process.env, process).then((exitCode) => {
    process.exitCode = exitCode;
  });
}

module.exports = {
  MAX_IMAGE_BYTES,
  parseArgs,
  loadConfig,
  resolveImageSource,
  buildPayload,
  requestVision,
  runCli,
};
