#!/usr/bin/env python3
"""gdstudio 音乐聚合接口:搜索、取链接、下载、音质降级、列出与清除下载。

用法:
  python3 download_music.py search --name "七里香"
  python3 download_music.py url --source joox --id <track_id> --br 320
  python3 download_music.py download --source joox --id <track_id> --name "七里香" --artist "周杰倫" --config ~/.config/music-download-skill/config.json
  python3 download_music.py list --config ~/.config/music-download-skill/config.json
  python3 download_music.py clear --keyword "七里香" --config ~/.config/music-download-skill/config.json
  python3 download_music.py config ~/.config/music-download-skill/config.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse

BASE_URL = "https://music-api.gdstudio.xyz/api.php"
DEFAULT_SOURCES = ["netease", "joox", "kuwo"]
# 音质档位 → API 的 br 码率;TIER_NAMES 与 BR_TIERS 必须保持一致(单一来源见 api.md)
TIER_NAMES = {
    "标准音质": 128,
    "高品音质": 192,
    "超品音质": 320,
    "无损": 740,
    "Hi-Res无损": 999,
}
BR_TIERS = [128, 192, 320, 740, 999]  # 升序,索引即降级基准
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"}
DEFAULT_BIT_SIZE = "Hi-Res无损"
RATE_LIMIT_MAX = 50
RATE_LIMIT_WINDOW = 300  # 秒
RATE_LIMIT_MIN_INTERVAL = 0.3  # 秒,请求最小间隔
HTTP_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
USER_AGENT = "music-download-skill/1.0"

EXT_BY_CONTENT_TYPE = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/mp4a-latm": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


# ---------- 繁简转换 ----------

_t2s_table: dict[str, str] | None = None


def _load_t2s_table() -> dict[str, str]:
    """懒加载 scripts/t2s.tsv(OpenCC TSCharacters 繁体→简体),缓存到模块级。"""
    global _t2s_table
    if _t2s_table is not None:
        return _t2s_table
    table: dict[str, str] = {}
    path = Path(__file__).with_name("t2s.tsv")
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                table[parts[0]] = parts[1].split(" ")[0]  # 多值取第一个简体形
    _t2s_table = table
    return table


def to_simplified(text: str) -> str:
    """繁体中文转简体(joox 等源返回繁体);无映射的字符原样保留。"""
    if not text:
        return text
    table = _load_t2s_table()
    return "".join(table.get(ch, ch) for ch in text)


class ConfigError(ValueError):
    """配置非法或缺失。"""


class ApiError(RuntimeError):
    """API 请求失败(网络、HTTP 状态、响应不是 JSON)。

    retryable=True 表示「该档/该源不可用」(如 503、非 JSON 页面),可降级到其它音质重试;
    retryable=False 表示限流或网络问题,不应降级重试。
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class DownloadError(RuntimeError):
    """下载失败(HTTP 错误、空文件、大小不符)。"""


# ---------- 配置 ----------

def load_config(path: Path) -> dict[str, Any]:
    """读取 config.json;文件不存在返回 {} (首次运行信号),JSON 非法抛 ConfigError。"""
    path = path.expanduser()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON 格式错误 {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"JSON 顶层必须为对象: {path}")
    return data


def save_config(path: Path, config: dict[str, Any]) -> None:
    """写回 config.json(indent=2, UTF-8)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_bit_size(config: dict[str, Any], explicit: str | None = None) -> str:
    """确定音质档位名称。优先级:命令行 --bit-size > config.bit_size > DEFAULT_BIT_SIZE。"""
    value = (explicit or config.get("bit_size") or DEFAULT_BIT_SIZE).strip()
    if value not in TIER_NAMES:
        raise ConfigError(f"未知音质档位: {value!r},可选 {sorted(TIER_NAMES)}")
    return value


# ---------- 限流 ----------

class RateLimiter:
    """进程内滑动窗口限流:window_seconds 内最多 max_requests 次,请求间留最小间隔。"""

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_MAX,
        window_seconds: int = RATE_LIMIT_WINDOW,
        min_interval: float = RATE_LIMIT_MIN_INTERVAL,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.min_interval = min_interval
        self._timestamps: deque[float] = deque()
        self._last_request = 0.0

    def wait(self) -> None:
        now = time.time()
        while self._timestamps and now - self._timestamps[0] > self.window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_requests:
            delay = self._timestamps[0] + self.window_seconds - now
            if delay > 0:
                time.sleep(delay)
            self._timestamps.clear()
        gap = self.min_interval - (now - self._last_request)
        if gap > 0:
            time.sleep(gap)
        self._last_request = time.time()
        self._timestamps.append(self._last_request)


# ---------- API 请求 ----------

def api_request(params: dict[str, Any], rate_limiter: RateLimiter | None = None) -> Any:
    """GET BASE_URL?urlencode(params),解析并返回 JSON。错误统一抛 ApiError。"""
    if rate_limiter is not None:
        rate_limiter.wait()
    url = f"{BASE_URL}?{urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                raise ApiError(f"HTTP {resp.status}")
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code == 429:
            raise ApiError("限流(429),请稍后重试", retryable=False) from exc
        raise ApiError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise ApiError(f"网络错误: {exc.reason}", retryable=False) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # 源偶发 503/HTML 页(如 joox 740 返回 200+503HTML 页)等 → 视为该档/该源不可用
        raise ApiError("响应不是 JSON(该音质或源不可用)") from exc


# ---------- 搜索 ----------

def normalize_record(record: Any) -> dict[str, Any] | None:
    """从搜索记录抽 id/name/artist(数组)/album/source;缺 id 或 name 返回 None;繁体转简体。"""
    if not isinstance(record, dict):
        return None
    track_id = str(record.get("id", "")).strip()
    name = to_simplified(str(record.get("name", "")).strip())
    if not track_id or not name:
        return None
    artists = record.get("artist")
    if isinstance(artists, list):
        artists = [to_simplified(str(a).strip()) for a in artists if str(a).strip()]
    else:
        artists = [to_simplified(str(artists).strip())] if str(artists or "").strip() else []
    return {
        "id": track_id,
        "name": name,
        "artist": artists,
        "album": to_simplified(str(record.get("album", "") or "")),
        "source": str(record.get("source", "")),
    }


def search_sources(
    name: str,
    sources: list[str] | None = None,
    count: int = 10,
    page: int = 1,
    rate_limiter: RateLimiter | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """按源顺序逐个请求,第一个返回非空数组的源即结果源。

    空数组、非列表、{"detail": ...}、ApiError(含非 JSON HTML)都视为该源无结果,继续下一个。
    全部失败返回 (None, [])。
    """
    for source in sources or DEFAULT_SOURCES:
        try:
            data = api_request(
                {
                    "types": "search",
                    "source": source,
                    "name": name,
                    "count": count,
                    "pages": page,
                },
                rate_limiter,
            )
        except ApiError:
            continue
        if isinstance(data, list) and data:
            records = [r for r in (normalize_record(r) for r in data) if r]
            if records:
                return source, records
    return None, []


# ---------- 取下载链接与音质降级 ----------

def get_download_url(
    source: str,
    track_id: str,
    br: int,
    rate_limiter: RateLimiter | None = None,
) -> dict[str, Any]:
    """返回 {"url", "br", "size"};url=="" 且 br==-1 表示该音质不可用(不抛错)。"""
    data = api_request(
        {"types": "url", "source": source, "id": track_id, "br": br},
        rate_limiter,
    )
    if not isinstance(data, dict):
        raise ApiError("url 接口返回结构异常")
    return {
        "url": str(data.get("url", "")),
        "br": int(data.get("br", -1)),
        "size": int(data.get("size", 0)),
    }


def degrade_chain(bit_size_name: str) -> list[int]:
    """从该档位 br 向下到 128 的降级序列,如超品音质 → [320, 192, 128]。"""
    if bit_size_name not in TIER_NAMES:
        raise ConfigError(f"未知音质档位: {bit_size_name!r},可选 {sorted(TIER_NAMES)}")
    start = TIER_NAMES[bit_size_name]
    return BR_TIERS[BR_TIERS.index(start) :: -1]


def resolve_url_with_degrade(
    source: str,
    track_id: str,
    bit_size_name: str,
    rate_limiter: RateLimiter | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """沿 degrade_chain 逐级取链接,返回 (可用 url, 对应 info);全不可用 → (None, 空 info)。"""
    for br in degrade_chain(bit_size_name):
        try:
            info = get_download_url(source, track_id, br, rate_limiter)
        except ApiError:
            continue  # 该档不可用(503 / 非 JSON 页),继续降级
        if info["url"] and info["br"] != -1:
            return info["url"], info
    return None, {"url": "", "br": -1, "size": 0}


# ---------- 命名与扩展名 ----------

def sanitize_filename_part(value: str) -> str:
    """去首尾空白,把 \\/:*?"<>| 与控制字符换成 _,折叠空白,截断 80 字符。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80]


def build_filename(name: str, artists: list[str], ext: str) -> str:
    """按「歌名-歌手.后缀」命名,如 七里香-周杰伦.mp3;多歌手用 & 连接。"""
    artist_part = sanitize_filename_part(to_simplified("&".join(artists or ["未知歌手"])))
    song_part = sanitize_filename_part(to_simplified(name or "未知歌曲"))
    return f"{song_part}-{artist_part}{ext}"


def infer_extension(url: str, br: int, content_type: str = "") -> str:
    """推断文件后缀。优先级:URL 路径扩展名 > Content-Type > 按 br 兜底(≥740 flac,否则 mp3)。"""
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return suffix
    if content_type:
        primary = content_type.split(";", 1)[0].strip().lower()
        if primary in EXT_BY_CONTENT_TYPE:
            return EXT_BY_CONTENT_TYPE[primary]
    return ".flac" if br >= 740 else ".mp3"


# ---------- 下载与校验 ----------

def download(
    url: str,
    dest_dir: Path,
    name: str,
    artists: list[str],
    br: int,
    expected_size: int = 0,
    timeout: int = DOWNLOAD_TIMEOUT,
) -> Path:
    """跟随重定向流式下载。先读响应头定扩展名 → 定文件名,写 .part 校验后原子改名。

    空文件抛 DownloadError;已知 expected_size(字节,即 API 返回的 size,实测为字节)
    时做 ±10% 容差比对。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except HTTPError as exc:
        raise DownloadError(f"下载失败 HTTP {exc.code}") from exc
    except URLError as exc:
        raise DownloadError(f"下载网络错误: {exc.reason}") from exc

    content_type = resp.headers.get("Content-Type", "")
    ext = infer_extension(url, br, content_type)
    final = dest_dir / build_filename(name, artists, ext)
    part = dest_dir / f"{final.name}.part"
    total = 0
    try:
        with part.open("wb") as handle:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
                total += len(chunk)
    finally:
        resp.close()
    if total == 0:
        part.unlink(missing_ok=True)
        raise DownloadError(f"下载文件为空: {final.name}")
    if expected_size > 0:
        expected = expected_size
        if abs(total - expected) > max(1024, expected * 0.1):
            part.unlink(missing_ok=True)
            raise DownloadError(f"文件大小不符:期望 {expected} 字节,实际 {total}")
    os.replace(part, final)
    return final


# ---------- 列出与清除 ----------

def list_downloaded(dest_dir: Path) -> list[Path]:
    """download_path 第一层的音频文件(不递归),按文件名排序。"""
    if not dest_dir.is_dir():
        return []
    return sorted(
        p
        for p in dest_dir.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def clear_matching(dest_dir: Path, keyword: str, dry_run: bool = False) -> list[Path]:
    """按文件名(stem)包含关键词(忽略大小写)匹配并删除。

    仅删音频、仅第一层;keyword 非空且不含路径分隔符。dry_run=True 只列出不删。
    """
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("清除关键词不能为空")
    if any(ch in keyword for ch in "/\\"):
        raise ValueError("关键词不能包含路径分隔符")
    matches = [
        p
        for p in list_downloaded(dest_dir)
        if keyword.lower() in p.stem.lower()
    ]
    if not dry_run:
        for p in matches:
            p.unlink()
    return matches


# ---------- 子命令 ----------

def _parse_track_id(value: str) -> str:
    return value.strip()


def _load_dest_dir(args: argparse.Namespace) -> Path:
    config = load_config(Path(args.config)) if args.config else {}
    raw = args.output_dir or config.get("download_path", "")
    dest = Path(raw).expanduser().resolve() if raw else None
    if dest is None or not str(dest):
        raise ConfigError("未配置下载目录:请提供 --output-dir 或 config.json 的 download_path")
    return dest


def cmd_search(args: argparse.Namespace) -> int:
    limiter = RateLimiter()
    if args.source:
        source, records = search_sources(
            args.name, sources=[args.source], count=args.count, page=args.page,
            rate_limiter=limiter,
        )
    else:
        source, records = search_sources(
            args.name, count=args.count, page=args.page, rate_limiter=limiter,
        )
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0 if source is not None else 3


def cmd_url(args: argparse.Namespace) -> int:
    limiter = RateLimiter()
    info = get_download_url(args.source, _parse_track_id(args.id), args.br, limiter)
    print(json.dumps(info, ensure_ascii=False))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config)) if args.config else {}
    dest_dir = _load_dest_dir(args)
    limiter = RateLimiter()

    if args.br is not None:
        chain = [args.br]
        requested_name = f"br {args.br}"
    else:
        bit_size = resolve_bit_size(config, args.bit_size)
        chain = degrade_chain(bit_size)
        requested_name = bit_size

    if args.degrade or args.br is None:
        if args.br is not None:
            url, info = resolve_url_with_degrade_for_br(args.source, args.id, args.br, limiter)
        else:
            url, info = resolve_url_with_degrade(args.source, args.id, bit_size, limiter)
    else:
        try:
            info = get_download_url(args.source, _parse_track_id(args.id), args.br, limiter)
        except ApiError as exc:
            if not exc.retryable:
                raise
            # 该档/该源不可用(503、非 JSON 页) → 按「音质不可用」返回 2,让用户走降级询问
            print(
                json.dumps(
                    {
                        "saved": None,
                        "reason": "quality_unavailable",
                        "detail": str(exc),
                        "requested": requested_name,
                        "requested_chain": chain,
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        url = info["url"] if info["url"] and info["br"] != -1 else None

    if not url:
        print(
            json.dumps(
                {
                    "saved": None,
                    "reason": "quality_unavailable",
                    "requested": requested_name,
                    "requested_chain": chain,
                },
                ensure_ascii=False,
            )
        )
        return 2

    final = download(
        url,
        dest_dir,
        args.name,
        args.artist,
        info["br"],
        expected_size=info["size"],
    )
    print(
        json.dumps(
            {
                "saved": str(final),
                "br": info["br"],
                "size": info["size"],
                "source": args.source,
            },
            ensure_ascii=False,
        )
    )
    return 0


def resolve_url_with_degrade_for_br(
    source: str, track_id: str, br: int, rate_limiter: RateLimiter | None = None
) -> tuple[str | None, dict[str, Any]]:
    """显式 --br 场景的降级:从该 br 向下到 128 取第一个可用链接。"""
    chain = BR_TIERS[BR_TIERS.index(br) :: -1]
    for candidate in chain:
        try:
            info = get_download_url(source, _parse_track_id(track_id), candidate, rate_limiter)
        except ApiError:
            continue  # 该档不可用,继续降级
        if info["url"] and info["br"] != -1:
            return info["url"], info
    return None, {"url": "", "br": -1, "size": 0}


def cmd_list(args: argparse.Namespace) -> int:
    dest_dir = _load_dest_dir(args)
    files = [str(p) for p in list_downloaded(dest_dir)]
    print(json.dumps(files, ensure_ascii=False, indent=2))
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    dest_dir = _load_dest_dir(args)
    matches = clear_matching(dest_dir, args.keyword, dry_run=args.dry_run)
    print(json.dumps([str(p) for p in matches], ensure_ascii=False, indent=2))
    return 0 if matches else 4


def cmd_config(args: argparse.Namespace) -> int:
    path = Path(args.path)
    try:
        config = load_config(path)
        download_path = str(config.get("download_path", "")).strip()
        bit_size = str(config.get("bit_size", "")).strip()
        valid = bool(download_path) and bit_size in TIER_NAMES
        print(
            json.dumps(
                {
                    "valid": valid,
                    "download_path": download_path,
                    "bit_size": bit_size,
                },
                ensure_ascii=False,
            )
        )
        return 0 if valid else 1
    except ConfigError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download_music",
        description="gdstudio 音乐聚合接口:搜索、取链接、下载、音质降级、列出与清除下载。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="搜索歌曲(自动按源顺序回退)")
    p_search.add_argument("--name", required=True, help="歌名/歌手/专辑关键词")
    p_search.add_argument("--count", type=int, default=10, help="每页条数,默认 10")
    p_search.add_argument("--page", type=int, default=1, help="页码,默认 1")
    p_search.add_argument("--source", help="指定单个源,跳过源回退")
    p_search.set_defaults(func=cmd_search)

    p_url = sub.add_parser("url", help="获取歌曲下载链接")
    p_url.add_argument("--source", required=True, help="音乐源")
    p_url.add_argument("--id", required=True, help="搜索返回的 track_id")
    p_url.add_argument("--br", type=int, default=999, help="码率 128/192/320/740/999")
    p_url.set_defaults(func=cmd_url)

    p_dl = sub.add_parser("download", help="下载歌曲到目录")
    p_dl.add_argument("--source", required=True, help="音乐源")
    p_dl.add_argument("--id", required=True, help="搜索返回的 track_id")
    p_dl.add_argument("--name", required=True, help="歌名")
    p_dl.add_argument("--artist", action="append", default=[], help="歌手(可重复,多歌手)")
    p_dl.add_argument("--output-dir", help="下载目录(覆盖 config.json 的 download_path)")
    p_dl.add_argument("--config", help="config.json 路径(取 download_path / bit_size)")
    p_dl.add_argument("--br", type=int, help="显式指定码率,跳过 bit_size 档位")
    p_dl.add_argument("--bit-size", help="覆盖音质档位名称")
    p_dl.add_argument("--degrade", action="store_true", help="音质不可用时自动降级到可用档")
    p_dl.set_defaults(func=cmd_download)

    p_list = sub.add_parser("list", help="列出 download_path 下已下载的音频文件")
    p_list.add_argument("--output-dir", dest="output_dir", help="下载目录(覆盖 config)")
    p_list.add_argument("--config", help="config.json 路径")
    p_list.set_defaults(func=cmd_list)

    p_clear = sub.add_parser("clear", help="删除文件名包含关键词的音频文件")
    p_clear.add_argument("--keyword", required=True, help="匹配关键词(文件名 stem 包含)")
    p_clear.add_argument("--output-dir", dest="output_dir", help="下载目录(覆盖 config)")
    p_clear.add_argument("--config", help="config.json 路径")
    p_clear.add_argument("--dry-run", action="store_true", help="只列出将删除的文件,不删除")
    p_clear.set_defaults(func=cmd_clear)

    p_cfg = sub.add_parser("config", help="校验 config.json")
    p_cfg.add_argument("path", help="config.json 路径")
    p_cfg.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, ApiError, DownloadError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
