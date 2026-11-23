# -*- coding: utf-8 -*-
"""切片 1 单元测试：SQLite 底座、4 套公众号主题排版、图床重写与 datacube 拉取。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"fake-img-bytes"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestSlice1WechatCore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AICONTENT_DATA_DIR"] = self.tmp.name
        from server import db
        db._INITIALIZED_PATHS.clear()

    def tearDown(self) -> None:
        os.environ.pop("AICONTENT_DATA_DIR", None)
        self.tmp.cleanup()

    def test_db_seed_and_crud(self) -> None:
        from server import db

        acc = db.get_primary_account()
        self.assertEqual(acc["id"], "primary")
        self.assertIn("AI 工具实操", acc["niche"])
        self.assertTrue(len(acc["banned_words"]) >= 5)

        updated = db.update_primary_account({"default_theme": "graphite_minimal"})
        self.assertEqual(updated["default_theme"], "graphite_minimal")

        tp = db.insert_topic({
            "source_type": "github_trending",
            "source_name": "GitHub Trending",
            "source_url": "https://github.com/example/agent",
            "raw_title": "example/agent",
            "suggested_titles": ["我用这个开源 Agent 把周报压缩到 3 分钟"],
            "score": 91,
        })
        self.assertEqual(tp["score"], 91)
        self.assertEqual(len(db.list_topics(status="new")), 1)

        art = db.record_article({
            "topic_id": tp["id"],
            "title": "我用这个开源 Agent 把周报压缩到 3 分钟",
            "theme": "moyu_green",
            "draft_media_id": "media_123",
        })
        self.assertEqual(art["draft_media_id"], "media_123")

        met = db.upsert_metric({
            "ref_date": "2026-11-21",
            "msgid": "msg_1",
            "title": "我用这个开源 Agent 把周报压缩到 3 分钟",
            "target_user": 1000,
            "read_user": 220,
            "share_count": 15,
            "fav_count": 30,
            "source": "datacube",
        })
        self.assertEqual(met["read_user"], 220)
        self.assertEqual(met["article_id"], art["id"])

    def test_gzh_themes_wechat_compatibility(self) -> None:
        from server.gzh_themes import THEME_SPECS, render_wechat_theme_html

        md = (
            "# 标题\n\n"
            "> 一句导读==重点词==\n\n"
            "## 第一步：安装\n\n"
            "正文包含 **加粗** 和 `pip install`。\n\n"
            "### 小标题\n\n"
            "- 条目一\n- 条目二\n\n"
            "```python\nprint('hello')\n```\n\n"
            "![示例图](https://example.com/demo.png)\n"
        )
        for tid in THEME_SPECS:
            html_out = render_wechat_theme_html(md, theme_id=tid, author="测试作者", footer="欢迎留言")
            self.assertNotIn("<style", html_out.lower())
            self.assertNotIn("class=", html_out.lower())
            self.assertNotIn("white-space:pre", html_out.lower())
            self.assertIn('<span leaf="">', html_out)
            self.assertIn("测试作者", html_out)

    def test_wechat_image_bed_rewrite_and_datacube(self) -> None:
        from server import wechat_mp

        wechat_mp._TOKEN_CACHE.clear()
        wechat_mp._THUMB_CACHE.clear()
        wechat_mp._ARTICLE_IMG_CACHE.clear()

        local_img = Path(self.tmp.name) / "demo.png"
        local_img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        def fake_get(url, **kwargs):
            if "/token" in url:
                return _FakeResp({"access_token": "tok_123", "expires_in": 7200})
            return _FakeResp({})

        def fake_post(url, **kwargs):
            if "/media/uploadimg" in url:
                return _FakeResp({"url": "https://mmbiz.qpic.cn/mmbiz_png/uploaded_ok/0"})
            if "/draft/add" in url:
                return _FakeResp({"media_id": "draft_999"})
            if "/datacube/getarticletotal" in url:
                return _FakeResp({
                    "list": [{
                        "ref_date": "2026-11-21",
                        "msgid": "1001_1",
                        "title": "测试文章",
                        "details": [{
                            "target_user": 500,
                            "int_page_read_user": 120,
                            "int_page_read_count": 150,
                            "ori_page_read_user": 80,
                            "share_count": 9,
                            "add_to_fav_count": 18,
                            "like_count": 12,
                        }],
                    }]
                })
            return _FakeResp({})

        with patch("server.wechat_mp.requests.get", side_effect=fake_get), \
             patch("server.wechat_mp.requests.post", side_effect=fake_post):
            res = wechat_mp.add_draft(
                title="测试文章",
                content=f"正文附图：\n\n![图1]({local_img})\n",
                thumb_media_id="thumb_1",
                appid="wx_app",
                secret="wx_sec",
                style="moyu_green",
            )
            self.assertEqual(res["media_id"], "draft_999")
            self.assertEqual(res["uploaded_images"], 1)
            self.assertEqual(res["image_warnings"], [])

            stats = wechat_mp.fetch_article_total("2026-11-21", "2026-11-21", appid="wx_app", secret="wx_sec")
            self.assertEqual(len(stats), 1)
            self.assertEqual(stats[0]["read_user"], 120)
            self.assertEqual(stats[0]["fav_count"], 18)


if __name__ == "__main__":
    unittest.main()
