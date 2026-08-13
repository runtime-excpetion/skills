from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import download_music as dm  # noqa: E402


class TierTests(unittest.TestCase):
    def test_tier_mapping(self):
        self.assertEqual(
            dm.TIER_NAMES,
            {"标准音质": 128, "高品音质": 192, "超品音质": 320, "无损": 740, "Hi-Res无损": 999},
        )
        self.assertEqual(dm.BR_TIERS, sorted(dm.BR_TIERS))

    def test_degrade_chain(self):
        self.assertEqual(dm.degrade_chain("超品音质"), [320, 192, 128])
        self.assertEqual(dm.degrade_chain("Hi-Res无损"), [999, 740, 320, 192, 128])
        self.assertEqual(dm.degrade_chain("标准音质"), [128])

    def test_degrade_chain_unknown(self):
        with self.assertRaises(dm.ConfigError):
            dm.degrade_chain("未知档位")


class FilenameTests(unittest.TestCase):
    def test_build_filename_single_artist(self):
        self.assertEqual(
            dm.build_filename("七里香", ["周杰倫"], ".mp3"),
            "七里香-周杰倫.mp3",
        )

    def test_build_filename_multi_artist(self):
        self.assertEqual(
            dm.build_filename("千里之外", ["周杰倫", "费玉清"], ".mp3"),
            "千里之外-周杰倫&费玉清.mp3",
        )

    def test_build_filename_unknown_artist(self):
        self.assertEqual(
            dm.build_filename("无名曲", [], ".flac"),
            "无名曲-未知歌手.flac",
        )

    def test_sanitize_filename_part(self):
        self.assertEqual(dm.sanitize_filename_part('周/杰:倫*?"'), "周_杰_倫___")
        self.assertEqual(dm.sanitize_filename_part("  七里香   "), "七里香")


class ExtensionTests(unittest.TestCase):
    def test_url_suffix_priority(self):
        self.assertEqual(
            dm.infer_extension("https://cdn.example.com/a/b/audio.mp3?sign=1", 999),
            ".mp3",
        )

    def test_br_fallback_flac(self):
        self.assertEqual(dm.infer_extension("https://x/y", 999), ".flac")
        self.assertEqual(dm.infer_extension("https://x/y", 740), ".flac")

    def test_br_fallback_mp3(self):
        self.assertEqual(dm.infer_extension("https://x/y", 320), ".mp3")

    def test_content_type_mapping(self):
        self.assertEqual(
            dm.infer_extension("https://x/y", 999, "audio/x-flac; charset=utf-8"),
            ".flac",
        )
        self.assertEqual(
            dm.infer_extension("https://x/y", 320, "audio/mp4"),
            ".m4a",
        )


class SearchTests(unittest.TestCase):
    def test_source_fallback(self):
        with mock.patch.object(dm, "api_request") as req:
            req.side_effect = [
                [],  # netease 空
                [{"id": "a", "name": "七里香", "artist": ["周杰倫"]}],  # joox 有
            ]
            source, records = dm.search_sources("七里香", sources=["netease", "joox"])
        self.assertEqual(source, "joox")
        self.assertEqual(records[0]["name"], "七里香")
        self.assertEqual(records[0]["artist"], ["周杰倫"])

    def test_all_sources_empty(self):
        with mock.patch.object(dm, "api_request") as req:
            req.return_value = []
            source, records = dm.search_sources("找不到的歌", sources=["netease", "joox"])
        self.assertIsNone(source)
        self.assertEqual(records, [])

    def test_non_json_skipped(self):
        # netease 返回 dict(非列表)、joox 抛 ApiError(bilibili 503 HTML 模拟)
        with mock.patch.object(dm, "api_request") as req:
            req.side_effect = [
                {"detail": "not supported"},
                dm.ApiError("响应不是 JSON"),
                [{"id": "b", "name": "Hello", "artist": ["Lionel Richie"]}],
            ]
            source, records = dm.search_sources("hello", sources=["netease", "joox", "bilibili"])
        self.assertEqual(source, "bilibili")
        self.assertEqual(records[0]["name"], "Hello")

    def test_normalize_record(self):
        self.assertIsNone(dm.normalize_record("not-a-dict"))
        self.assertIsNone(dm.normalize_record({"id": "a"}))  # 缺 name
        rec = dm.normalize_record({"id": "a", "name": "X", "artist": ["A", "B"], "album": "Z", "source": "joox"})
        self.assertEqual(rec, {"id": "a", "name": "X", "artist": ["A", "B"], "album": "Z", "source": "joox"})


class DegradeTests(unittest.TestCase):
    def test_resolve_with_degrade(self):
        with mock.patch.object(dm, "get_download_url") as get_url:
            get_url.side_effect = [
                {"url": "", "br": -1, "size": 0},   # 740 不可用
                {"url": "https://x/a.mp3", "br": 320, "size": 100},  # 320 可用
            ]
            url, info = dm.resolve_url_with_degrade("joox", "id", "无损")
        self.assertEqual(url, "https://x/a.mp3")
        self.assertEqual(info["br"], 320)

    def test_resolve_with_degrade_all_unavailable(self):
        with mock.patch.object(dm, "get_download_url") as get_url:
            get_url.return_value = {"url": "", "br": -1, "size": 0}
            url, info = dm.resolve_url_with_degrade("joox", "id", "无损")
        self.assertIsNone(url)
        self.assertEqual(info["br"], -1)


class ClearTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "七里香-周杰倫.mp3").write_bytes(b"a" * 100)
        (self.dir / "夜曲-周杰倫.mp3").write_bytes(b"b" * 100)
        (self.dir / "普通文件.txt").write_text("hi")
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "七里香-sub.mp3").write_bytes(b"c" * 100)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clear_matching_only_target(self):
        matched = dm.clear_matching(self.dir, "七里香")
        self.assertEqual([p.name for p in matched], ["七里香-周杰倫.mp3"])
        # 只删匹配的顶层音频:其余保留
        self.assertTrue((self.dir / "夜曲-周杰倫.mp3").exists())
        self.assertTrue((self.dir / "普通文件.txt").exists())
        self.assertTrue((self.dir / "sub" / "七里香-sub.mp3").exists())

    def test_clear_dry_run_does_not_delete(self):
        matched = dm.clear_matching(self.dir, "七里香", dry_run=True)
        self.assertEqual(len(matched), 1)
        self.assertTrue((self.dir / "七里香-周杰倫.mp3").exists())

    def test_clear_invalid_keyword(self):
        with self.assertRaises(ValueError):
            dm.clear_matching(self.dir, "  ")
        with self.assertRaises(ValueError):
            dm.clear_matching(self.dir, "a/b")

    def test_list_downloaded_first_level_only(self):
        files = dm.list_downloaded(self.dir)
        names = [p.name for p in files]
        self.assertEqual(names, ["七里香-周杰倫.mp3", "夜曲-周杰倫.mp3"])
        self.assertNotIn("普通文件.txt", names)


class ConfigTests(unittest.TestCase):
    def test_load_config_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dm.load_config(Path(tmp) / "nope.json")
        self.assertEqual(cfg, {})

    def test_load_config_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(dm.ConfigError):
                dm.load_config(p)

    def test_load_config_non_object_top_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "arr.json"
            p.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaises(dm.ConfigError):
                dm.load_config(p)

    def test_resolve_bit_size_precedence(self):
        cfg = {"bit_size": "高品音质"}
        self.assertEqual(dm.resolve_bit_size(cfg), "高品音质")
        self.assertEqual(dm.resolve_bit_size(cfg, "无损"), "无损")
        self.assertEqual(dm.resolve_bit_size({}), "Hi-Res无损")
        with self.assertRaises(dm.ConfigError):
            dm.resolve_bit_size(cfg, "量子音质")


if __name__ == "__main__":
    unittest.main()
