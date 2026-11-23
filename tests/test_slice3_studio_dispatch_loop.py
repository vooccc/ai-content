# -*- coding: utf-8 -*-
"""切片 3 端到端测试：选题开写 -> 主题渲染 -> 代理图床转微信图床 -> 推草稿自动归档。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.content = b"img"

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestSlice3StudioDispatchLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AICONTENT_DATA_DIR"] = self.tmp.name
        from server import db, wechat_mp
        db._INITIALIZED_PATHS.clear()
        wechat_mp._TOKEN_CACHE.clear()
        wechat_mp._THUMB_CACHE.clear()
        wechat_mp._ARTICLE_IMG_CACHE.clear()

    def tearDown(self) -> None:
        os.environ.pop("AICONTENT_DATA_DIR", None)
        self.tmp.cleanup()

    def test_full_wechat_closed_loop(self) -> None:
        from fastapi.testclient import TestClient
        from server.app import app

        demo_img = Path(self.tmp.name) / "shot.png"
        demo_img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        with TestClient(app) as client:
            # 1. 手动投喂一条选题并点开写
            with patch("server.topic_engine.llm_bridge.chat_completion", side_effect=RuntimeError("offline")):
                r_tp = client.post("/topics/manual", json={"idea": "用 AI 自动化工作流做一人公司日更"})
                self.assertEqual(r_tp.status_code, 200)
                tid = r_tp.json()["topic"]["id"]

            r_start = client.post(f"/topics/{tid}/start", json={"selected_title": "我用 AI 自动化工作流跑通一人公司日更"})
            self.assertEqual(r_start.status_code, 200)
            proj = r_start.json()["project"]
            pid = proj["id"]

            # 2. 模拟编辑定稿（含工作台本地代理图片路径）
            final_idx = next(i for i, n in enumerate(proj["nodes"]) if n["id"] == "finalize")
            proxy_url = f"/studio/projects/{pid}/image?path={quote(str(demo_img))}"
            md_body = f"# 我用 AI 自动化工作流跑通一人公司日更\n\n## 第一步：配置\n\n看图：\n\n![实测截图]({proxy_url})\n"
            r_edit = client.post(f"/studio/projects/{pid}/edit", json={"index": final_idx, "content": md_body})
            self.assertEqual(r_edit.status_code, 200)

            # 3. 秒切排版主题为石墨极简
            r_theme = client.post(f"/studio/projects/{pid}/render-theme", json={"theme": "graphite_minimal", "author": "老板"})
            self.assertEqual(r_theme.status_code, 200)
            html_out = r_theme.json()["html"]
            self.assertIn("PART 01", html_out)
            self.assertIn(proxy_url, html_out)

            # 4. 推公众号草稿箱：自动上传正文图床 + 自动归档进 articles 表
            uploaded_files = []

            def fake_get(url, **kwargs):
                if "/token" in url:
                    return _FakeResp({"access_token": "tok_slice3", "expires_in": 7200})
                return _FakeResp({})

            def fake_post(url, **kwargs):
                if "/media/uploadimg" in url:
                    uploaded_files.append(url)
                    return _FakeResp({"url": "https://mmbiz.qpic.cn/mmbiz_png/slice3_ok/0"})
                if "/draft/add" in url:
                    return _FakeResp({"media_id": "draft_slice3_888"})
                return _FakeResp({})

            with patch("server.wechat_mp.requests.get", side_effect=fake_get), \
                 patch("server.wechat_mp.requests.post", side_effect=fake_post):
                r_pub = client.post("/content/dispatch/wechat", json={
                    "title": "我用 AI 自动化工作流跑通一人公司日更",
                    "content": html_out,
                    "appid": "wx_1",
                    "secret": "sec_1",
                    "thumb_media_id": "thumb_1",
                    "project_id": pid,
                    "topic_id": tid,
                    "theme": "graphite_minimal",
                })
            self.assertEqual(r_pub.status_code, 200)
            pub_data = r_pub.json()
            self.assertTrue(pub_data["ok"])
            self.assertEqual(pub_data["media_id"], "draft_slice3_888")
            self.assertEqual(pub_data["uploaded_images"], 1)
            self.assertEqual(len(uploaded_files), 1)

            # 5. 验证 articles 表已自动归档且能被 metrics 关联
            r_m = client.post("/metrics", json={
                "ref_date": "2026-11-22",
                "title": "我用 AI 自动化工作流跑通一人公司日更",
                "read_user": 310,
                "fav_count": 45,
            })
            self.assertEqual(r_m.status_code, 200)
            self.assertEqual(r_m.json()["metric"]["article_id"], pub_data["article_id"])

            r_list = client.get("/metrics")
            self.assertEqual(r_list.json()["summary"]["article_count"], 1)
            self.assertEqual(r_list.json()["summary"]["best_read_user"], 310)


if __name__ == "__main__":
    unittest.main()
