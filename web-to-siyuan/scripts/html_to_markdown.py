#!/usr/bin/env python3
"""Extract an article DOM and convert it to validated GFM Markdown."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from lxml import etree, html


EMPTY_CHARS = "\u00a0\u200b\u200c\u200d\u2060\ufeff\ufe0e\ufe0f"
BLOCK_TAGS = {"div", "section", "p", "span", "figure", "figcaption"}
DROP_TAGS = {"script", "style", "noscript", "template", "svg", "canvas", "form", "button"}
LEAK_MARKERS = (
    "document.getElementById('js_content')",
    'document.getElementById("js_content")',
    "document.addEventListener(\"keydown\"",
    "addEventListener(\"selectstart\"",
)
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
LANG_CLASS_RE = re.compile(r"(?:language|lang)-([A-Za-z0-9_+.-]+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("html_file", type=Path)
    parser.add_argument("--original-url", required=True)
    parser.add_argument("--final-url")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def normalize_url(value: str) -> str:
    value = value.strip().strip("<>")
    return value.rstrip("，。；！？、）】》\"'")


def first_text(nodes: list[etree._Element]) -> str:
    for node in nodes:
        text_value = " ".join(node.text_content().split())
        if text_value:
            return text_value
    return ""


def select_article(document: etree._Element, original_url: str) -> tuple[etree._Element, str, str]:
    is_wechat = "mp.weixin.qq.com" in original_url
    if is_wechat:
        candidates = document.xpath('//*[@id="js_content"]')
        if not candidates:
            raise ValueError("微信页面缺少 #js_content，可能抓到了验证页")
        title = first_text(document.xpath('//*[@id="activity-name"]'))
        return candidates[0], title, "wechat:#js_content"

    selectors = (
        "//article",
        "//main",
        '//*[@role="main"]',
        "//body",
    )
    for selector in selectors:
        candidates = document.xpath(selector)
        if candidates:
            title = first_text(document.xpath("//h1"))
            if not title:
                title = first_text(document.xpath("//title"))
            return candidates[0], title, selector
    raise ValueError("未找到正文容器")


def drop_node(node: etree._Element) -> None:
    parent = node.getparent()
    if parent is not None:
        parent.remove(node)


def is_hidden(node: etree._Element) -> bool:
    if "hidden" in node.attrib:
        return True
    if node.attrib.get("aria-hidden", "").lower() == "true":
        return True
    style = re.sub(r"\s+", "", node.attrib.get("style", "").lower())
    return "display:none" in style


def clean_dom(article: etree._Element) -> None:
    for node in list(article.iterdescendants()):
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag in DROP_TAGS or is_hidden(node):
            drop_node(node)

    for image in article.xpath(".//img"):
        lazy_src = image.attrib.get("data-src") or image.attrib.get("data-original")
        src = lazy_src or image.attrib.get("src", "")
        alt = image.attrib.get("alt", "")
        title = image.attrib.get("title", "")
        image.attrib.clear()
        if src:
            image.attrib["src"] = src
        if alt:
            image.attrib["alt"] = alt
        if title:
            image.attrib["title"] = title


def text_with_breaks(node: etree._Element) -> str:
    parts: list[str] = []

    def visit(current: etree._Element) -> None:
        if current.text:
            parts.append(current.text)
        for child in current:
            tag = child.tag.lower() if isinstance(child.tag, str) else ""
            if tag == "br":
                parts.append("\n")
            elif tag not in DROP_TAGS and not is_hidden(child):
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    value = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ")
    lines = [line.rstrip() for line in value.split("\n")]
    if lines and not lines[0].strip():
        lines.pop(0)
    if lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def infer_language(pre: etree._Element, code: etree._Element | None) -> str:
    for node in (code, pre):
        if node is None:
            continue
        match = LANG_CLASS_RE.search(node.attrib.get("class", ""))
        if match:
            return match.group(1).lower()
        for name in ("data-lang", "data-language"):
            if node.attrib.get(name):
                return node.attrib[name].lower()

    previous = pre.getprevious()
    context = previous.text_content().strip().lower() if previous is not None else ""
    if "docker compose" in context or "docker-compose" in context:
        return "yaml"
    return ""


def rebuild_code_blocks(article: etree._Element) -> int:
    blocks = list(article.xpath(".//pre"))
    for pre in blocks:
        code_nodes = pre.xpath(".//code")
        code = code_nodes[0] if code_nodes else None
        source = code if code is not None else pre
        value = text_with_breaks(source)
        language = infer_language(pre, code)

        pre.clear()
        rebuilt = etree.SubElement(pre, "code")
        if language:
            rebuilt.attrib["class"] = f"language-{language}"
        rebuilt.text = value
    return len(blocks)


def meaningful_text(node: etree._Element) -> str:
    value = "".join(node.itertext())
    return value.translate({ord(char): None for char in EMPTY_CHARS}).strip()


def remove_empty_decorations(article: etree._Element) -> None:
    for node in reversed(list(article.iterdescendants())):
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag not in BLOCK_TAGS or node.xpath(".//img|.//video|.//audio|.//pre|.//code"):
            continue
        if not meaningful_text(node):
            drop_node(node)


def run_pandoc(article: etree._Element) -> str:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("未找到 pandoc，无法执行高保真 HTML → Markdown 转换")
    lua_filter = Path(__file__).with_name("strip_wrappers.lua")
    if not lua_filter.exists():
        raise RuntimeError(f"缺少 pandoc 过滤器：{lua_filter}")
    fragment = html.tostring(article, encoding="unicode", method="html")
    result = subprocess.run(
        [
            pandoc,
            "--from=html",
            "--to=gfm",
            "--wrap=none",
            f"--lua-filter={lua_filter}",
        ],
        input=fragment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pandoc 转换失败：{result.stderr.strip()}")
    return result.stdout


def normalize_markdown(markdown: str) -> tuple[str, int]:
    output: list[str] = []
    active_fence: tuple[str, int] | None = None
    code_blocks = 0

    for raw_line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(2)
            marker_type = marker[0]
            if active_fence is None:
                info = match.group(3).strip()
                line = f"{match.group(1)}{marker}{info}"
                active_fence = (marker_type, len(marker))
                code_blocks += 1
            elif marker_type == active_fence[0] and len(marker) >= active_fence[1]:
                active_fence = None
            output.append(line.rstrip())
            continue

        if active_fence is not None:
            output.append(line.rstrip())
            continue

        visible = line.translate({ord(char): None for char in EMPTY_CHARS})
        line = "" if not visible.strip() else line.rstrip()
        if line == "" and (not output or output[-1] == ""):
            continue
        output.append(line)

    if active_fence is not None:
        raise ValueError("Markdown 代码围栏未闭合")
    return "\n".join(output).strip(), code_blocks


def add_source(markdown: str, original_url: str, final_url: str | None) -> str:
    lines = [f"> 原文地址：[{original_url}](<{original_url}>)"]
    if final_url and final_url != original_url:
        lines.append(f"> 最终地址：[{final_url}](<{final_url}>)")
    return "\n".join(lines) + "\n\n" + markdown.strip() + "\n"


def markdown_outside_code(markdown: str) -> str:
    output: list[str] = []
    active_fence: tuple[str, int] | None = None
    for line in markdown.splitlines():
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(2)
            if active_fence is None:
                active_fence = (marker[0], len(marker))
            elif marker[0] == active_fence[0] and len(marker) >= active_fence[1]:
                active_fence = None
            continue
        if active_fence is None:
            output.append(line)
    return "\n".join(output)


def validate(markdown: str, original_url: str, html_code_blocks: int, md_code_blocks: int) -> None:
    if original_url not in markdown.splitlines()[0]:
        raise ValueError("原文地址未出现在 Markdown 首行")
    if html_code_blocks != md_code_blocks:
        raise ValueError(
            f"代码块数量不一致：HTML={html_code_blocks}, Markdown={md_code_blocks}"
        )
    outside_code = markdown_outside_code(markdown)
    for marker in LEAK_MARKERS:
        if marker in outside_code:
            raise ValueError(f"检测到正文边界外脚本泄漏：{marker}")


def main() -> int:
    args = parse_args()
    original_url = normalize_url(args.original_url)
    final_url = normalize_url(args.final_url) if args.final_url else None
    source = args.html_file.read_text(encoding="utf-8", errors="replace")
    document = html.fromstring(source)
    article, title, selector = select_article(document, original_url)
    clean_dom(article)
    html_code_blocks = rebuild_code_blocks(article)
    remove_empty_decorations(article)
    markdown, md_code_blocks = normalize_markdown(run_pandoc(article))
    markdown = add_source(markdown, original_url, final_url)
    validate(markdown, original_url, html_code_blocks, md_code_blocks)

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    print(
        f"title={title!r} selector={selector} code_blocks={md_code_blocks}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
