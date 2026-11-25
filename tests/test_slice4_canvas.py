# -*- coding: utf-8 -*-
"""切片 4 端到端测试：创作台·新版（Canvas 项目 CRUD、多模态上传、流式联动、违禁词检查、微信渲染、推草稿图床与习惯沉淀）。"""
from __future__ import annotations

import json
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


class TestSlice4Canvas(unittest.TestCase):
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

    def test_canvas_full_workflow(self) -> None:
        from fastapi.testclient import TestClient
        from server.app import app

        with TestClient(app) as client:
            # 1. 新建 Canvas 项目并检查列表
            r_new = client.post("/canvas/projects", json={"title": "测试新画布"})
            self.assertEqual(r_new.status_code, 200)
            proj = r_new.json()["project"]
            pid = proj["id"]
            self.assertTrue(pid.startswith("c_"))

            r_list = client.get("/canvas/projects")
            self.assertEqual(r_list.status_code, 200)
            self.assertEqual(len(r_list.json()["projects"]), 1)

            # 2. 投喂图片、文档与笔记素材
            r_img = client.post(
                f"/canvas/projects/{pid}/sources/upload",
                files={"file": ("shot.png", b"\x89PNG\r\n\x1a\nfakeimg", "image/png")},
                data={"purpose": "source"},
            )
            self.assertEqual(r_img.status_code, 200)
            img_src = r_img.json()["source"]
            self.assertEqual(img_src["kind"], "image")

            r_doc = client.post(
                f"/canvas/projects/{pid}/sources/upload",
                files={"file": ("notes.md", "# 笔记\n\n实测延迟降低 40%".encode("utf-8"), "text/markdown")},
                data={"purpose": "source"},
            )
            self.assertEqual(r_doc.status_code, 200)
            self.assertIn("40%", r_doc.json()["source"]["content"])

            r_txt = client.post(
                f"/canvas/projects/{pid}/sources/text",
                json={"title": "真实想法", "content": "我想重点讲怎么接上 Gemini 4 Hydrogen"},
            )
            self.assertEqual(r_txt.status_code, 200)

            # 验证图片可安全读取，路径穿越被拒
            r_get_img = client.get(f"/canvas/projects/{pid}/image", params={"path": img_src["path"]})
            self.assertEqual(r_get_img.status_code, 200)
            r_bad_img = client.get(f"/canvas/projects/{pid}/image", params={"path": str(ROOT / "README.md")})
            self.assertEqual(r_bad_img.status_code, 403)

            # 3. 模拟流式 Copilot 对话生成 <article> 并自动保存版本快照
            fake_chunks = [
                ("model", "deepseek-chat"),
                ("reasoning", "先理清对比结构"),
                ("content", "我已根据你给的笔记写好了初稿。\n\n<article>\n# 实测接通 Gemini 4 Hydrogen\n\n综上所述，全网首发实测。\n</article>"),
            ]

            def fake_stream(*args, **kwargs):
                for item in fake_chunks:
                    yield item

            with patch("server.canvas_routes.stream_multimodal_chat", side_effect=fake_stream):
                r_chat = client.post(
                    f"/canvas/projects/{pid}/chat",
                    json={"message": "先帮我起草一版", "image_paths": [img_src["path"]]},
                )
                self.assertEqual(r_chat.status_code, 200)
                body_lines = [ln for ln in r_chat.text.splitlines() if ln.startswith("data:")]
                events = [json.loads(ln[5:].strip()) for ln in body_lines]
                ev_types = [e.get("type") for e in events]
                self.assertIn("article_start", ev_types)
                self.assertIn("article_delta", ev_types)
                self.assertIn("done", ev_types)
                done_ev = [e for e in events if e.get("type") == "done"][-1]
                self.assertIn("实测接通 Gemini 4 Hydrogen", done_ev["project"]["content"])
                self.assertTrue(done_ev["applied_version"])

            # 4. 违禁词与 AI 味检查
            r_chk = client.post(f"/canvas/projects/{pid}/check", json={})
            self.assertEqual(r_chk.status_code, 200)
            chk_data = r_chk.json()
            words_hit = {f["word"] for f in chk_data["findings"]}
            self.assertIn("全网首发", words_hit)
            self.assertIn("综上所述", words_hit)

            # 5. 划选局部替换与版本撤回
            r_proj = client.get(f"/canvas/projects/{pid}").json()["project"]
            prev_vid = r_proj["versions"][-1]["id"]
            client.post(f"/canvas/projects/{pid}/save", json={"content": "# 新改稿\n\n手工修改版本", "push_version": True, "version_label": "手改"})
            r_rest = client.post(f"/canvas/projects/{pid}/restore-version", json={"version_id": prev_vid})
            self.assertEqual(r_rest.status_code, 200)
            self.assertIn("全网首发", r_rest.json()["project"]["content"])

            # 6. 微信排版渲染 + 代理图床解析 + 推送草稿箱回写 draft_media_id
            proxy_img = f"/canvas/projects/{pid}/image?path={quote(img_src['path'])}"
            md_with_img = f"# 最终标题\n\n![实测图]({proxy_img})\n\n正文内容。"
            r_render = client.post("/canvas/render-wechat", json={"markdown": md_with_img, "theme": "moyu_green"})
            self.assertEqual(r_render.status_code, 200)
            html_out = r_render.json()["html"]
            self.assertIn(proxy_img, html_out)

            uploaded_imgs = []

            def fake_get(url, **kwargs):
                if "/token" in url:
                    return _FakeResp({"access_token": "tok_canvas", "expires_in": 7200})
                return _FakeResp({})

            def fake_post(url, **kwargs):
                if "/material/add_material" in url:
                    return _FakeResp({"media_id": "thumb_canvas_001"})
                if "/media/uploadimg" in url:
                    uploaded_imgs.append(url)
                    return _FakeResp({"url": "https://mmbiz.qpic.cn/mmbiz_png/canvas_ok/0"})
                if "/draft/add" in url:
                    return _FakeResp({"media_id": "draft_canvas_999"})
                return _FakeResp({})

            with patch("server.wechat_mp.requests.get", side_effect=fake_get), \
                 patch("server.wechat_mp.requests.post", side_effect=fake_post):
                r_pub = client.post("/content/dispatch/wechat", json={
                    "title": "最终标题",
                    "content": html_out,
                    "appid": "wx_c1",
                    "secret": "sec_c1",
                    "cover_url": proxy_img,
                    "project_id": pid,
                    "theme": "moyu_green",
                })
                self.assertEqual(r_pub.status_code, 200)
                self.assertTrue(r_pub.json()["ok"])
                self.assertEqual(r_pub.json()["uploaded_images"], 1)
                self.assertEqual(len(uploaded_imgs), 1)

            r_after_pub = client.get(f"/canvas/projects/{pid}").json()["project"]
            self.assertEqual(r_after_pub["draft_media_id"], "draft_canvas_999")

            # 7. 个人写作习惯读写与沉淀
            r_ms = client.put("/canvas/my-style", json={"content": "- 禁止套话"})
            self.assertEqual(r_ms.status_code, 200)
            self.assertEqual(client.get("/canvas/my-style").json()["content"], "- 禁止套话")

            # 8. 从旧创作台无损导入
            r_old_new = client.post("/studio/projects", json={"workflow": "content_pipeline", "inputs": {"topic": "旧项目主题", "platform": "公众号"}, "title": "旧项目主题"})
            old_pid = r_old_new.json()["project"]["id"]
            r_imp = client.post(f"/canvas/projects/import-studio/{old_pid}")
            self.assertEqual(r_imp.status_code, 200)
            self.assertEqual(r_imp.json()["project"]["source_studio_id"], old_pid)


if __name__ == "__main__":
    unittest.main()
