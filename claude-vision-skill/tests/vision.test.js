const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");

const {
  MAX_IMAGE_BYTES,
  parseArgs,
  loadConfig,
  resolveImageSource,
  buildPayload,
  requestVision,
  runCli,
} = require("../scripts/vision.js");

function startServer(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({
        baseUrl: `http://127.0.0.1:${port}/v1`,
        close: () => new Promise((done) => server.close(done)),
      });
    });
  });
}

function captureIo() {
  const stdout = [];
  const stderr = [];
  return {
    stdout: { write: (value) => stdout.push(String(value)) },
    stderr: { write: (value) => stderr.push(String(value)) },
    stdoutText: () => stdout.join(""),
    stderrText: () => stderr.join(""),
  };
}

test("parseArgs parses a local image and multi-word question", () => {
  assert.deepEqual(parseArgs(["photo.png", "图里", "有什么？"]), {
    source: "photo.png",
    isUrl: false,
    prompt: "图里 有什么？",
  });
});

test("parseArgs parses an HTTPS image URL", () => {
  assert.deepEqual(parseArgs(["--url", "https://example.com/photo.png"]), {
    source: "https://example.com/photo.png",
    isUrl: true,
    prompt: "请详细描述这张图片的内容。",
  });
});

test("parseArgs rejects missing and conflicting image sources", () => {
  assert.throws(() => parseArgs([]), /缺少图片来源/);
  assert.throws(
    () => parseArgs(["local.png", "--url", "https://example.com/remote.png"]),
    /只能指定一个图片来源/
  );
});

test("loadConfig reports every missing required variable without values", () => {
  assert.throws(
    () => loadConfig({}),
    /VISION_API_KEY, VISION_MODEL, VISION_BASE_URL/
  );
});

test("loadConfig normalizes the base URL and timeout", () => {
  assert.deepEqual(
    loadConfig({
      VISION_API_KEY: "secret-value",
      VISION_MODEL: "vision-model",
      VISION_BASE_URL: "https://api.example.com/v1/",
      VISION_TIMEOUT_MS: "4500",
    }),
    {
      apiKey: "secret-value",
      model: "vision-model",
      baseUrl: "https://api.example.com/v1",
      timeoutMs: 4500,
    }
  );
});

test("loadConfig rejects unsafe endpoints and out-of-range timeouts", () => {
  const base = {
    VISION_API_KEY: "secret-value",
    VISION_MODEL: "vision-model",
  };
  assert.throws(
    () => loadConfig({ ...base, VISION_BASE_URL: "http://api.example.com/v1" }),
    /必须使用 HTTPS/
  );
  assert.throws(
    () => loadConfig({ ...base, VISION_BASE_URL: "https://api.example.com/v1", VISION_TIMEOUT_MS: "999" }),
    /1000 到 120000/
  );
});

test("resolveImageSource converts a supported local image to a data URL", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "vision-skill-"));
  const imagePath = path.join(tempDir, "sample.png");
  fs.writeFileSync(imagePath, Buffer.from([0x89, 0x50, 0x4e, 0x47]));
  try {
    assert.equal(
      resolveImageSource(imagePath, false),
      "data:image/png;base64,iVBORw=="
    );
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test("resolveImageSource rejects missing, unsupported, and oversized files", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "vision-skill-"));
  const unsupported = path.join(tempDir, "sample.svg");
  const oversized = path.join(tempDir, "large.png");
  fs.writeFileSync(unsupported, "<svg/>");
  fs.writeFileSync(oversized, "x");
  fs.truncateSync(oversized, MAX_IMAGE_BYTES + 1);
  try {
    assert.throws(
      () => resolveImageSource(path.join(tempDir, "missing.png"), false),
      /文件不存在/
    );
    assert.throws(() => resolveImageSource(unsupported, false), /不支持的图片格式/);
    assert.throws(() => resolveImageSource(oversized, false), /超过 20 MiB/);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test("resolveImageSource accepts HTTPS URLs and rejects other protocols", () => {
  assert.equal(
    resolveImageSource("https://example.com/photo.png", true),
    "https://example.com/photo.png"
  );
  assert.throws(
    () => resolveImageSource("http://example.com/photo.png", true),
    /图片 URL 必须使用 HTTPS/
  );
  assert.throws(() => resolveImageSource("not-a-url", true), /图片 URL 无效/);
});

test("buildPayload emits an OpenAI-compatible multimodal message", () => {
  assert.deepEqual(buildPayload("data:image/png;base64,AA==", "描述图片", "vision-model"), {
    model: "vision-model",
    messages: [
      {
        role: "user",
        content: [
          { type: "image_url", image_url: { url: "data:image/png;base64,AA==" } },
          { type: "text", text: "描述图片" },
        ],
      },
    ],
    stream: false,
    max_tokens: 1024,
  });
});

test("requestVision sends auth and returns the caption", async () => {
  let received;
  const server = await startServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      received = { url: req.url, auth: req.headers.authorization, body: JSON.parse(body) };
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ choices: [{ message: { content: "识别结果" } }] }));
    });
  });
  try {
    const config = loadConfig({
      VISION_API_KEY: "secret-value",
      VISION_MODEL: "vision-model",
      VISION_BASE_URL: server.baseUrl,
    });
    const payload = buildPayload("https://example.com/photo.png", "描述", config.model);
    assert.equal(await requestVision(payload, config), "识别结果");
    assert.equal(received.url, "/v1/chat/completions");
    assert.equal(received.auth, "Bearer secret-value");
    assert.equal(received.body.model, "vision-model");
  } finally {
    await server.close();
  }
});

test("requestVision returns a safe upstream error without leaking the key", async () => {
  const server = await startServer((req, res) => {
    res.writeHead(401, { "content-type": "application/json", "x-request-id": "req-123" });
    res.end(JSON.stringify({ error: { message: "invalid credential" } }));
  });
  try {
    const config = loadConfig({
      VISION_API_KEY: "secret-value",
      VISION_MODEL: "vision-model",
      VISION_BASE_URL: server.baseUrl,
    });
    await assert.rejects(
      requestVision(buildPayload("https://example.com/a.png", "描述", config.model), config),
      (error) => {
        assert.match(error.message, /上游 API 返回 401/);
        assert.match(error.message, /req-123/);
        assert.match(error.message, /invalid credential/);
        assert.doesNotMatch(error.message, /secret-value/);
        return true;
      }
    );
  } finally {
    await server.close();
  }
});

test("requestVision reports timeouts as a distinct error", async () => {
  const server = await startServer((_req, res) => {
    setTimeout(() => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ choices: [{ message: { content: "late" } }] }));
    }, 80);
  });
  try {
    const config = {
      apiKey: "secret-value",
      model: "vision-model",
      baseUrl: server.baseUrl,
      timeoutMs: 20,
    };
    await assert.rejects(
      requestVision(buildPayload("https://example.com/a.png", "描述", config.model), config),
      /请求超时/
    );
  } finally {
    await server.close();
  }
});

test("runCli preserves the stdout, stderr, and exit-code contract", async () => {
  const server = await startServer((_req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ choices: [{ message: { content: "CLI 结果" } }] }));
  });
  try {
    const io = captureIo();
    const exitCode = await runCli(
      ["--url", "https://example.com/a.png", "描述"],
      {
        VISION_API_KEY: "secret-value",
        VISION_MODEL: "vision-model",
        VISION_BASE_URL: server.baseUrl,
      },
      io
    );
    assert.equal(exitCode, 0);
    assert.equal(io.stdoutText(), "CLI 结果\n");
    assert.equal(io.stderrText(), "");

    const failedIo = captureIo();
    const failedCode = await runCli(["photo.png"], {}, failedIo);
    assert.equal(failedCode, 1);
    assert.equal(failedIo.stdoutText(), "");
    assert.match(failedIo.stderrText(), /VISION_API_KEY, VISION_MODEL, VISION_BASE_URL/);
    assert.doesNotMatch(failedIo.stderrText(), /secret-value/);
  } finally {
    await server.close();
  }
});
