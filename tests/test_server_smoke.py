# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestServerSmoke(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["AICONTENT_DATA_DIR"] = self._tmp.name
        from fastapi.testclient import TestClient
        from server.app import app
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("AICONTENT_DATA_DIR", None)
        self._tmp.cleanup()

    def test_health_static_and_config(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

        r_idx = self.client.get("/")
        self.assertEqual(r_idx.status_code, 200)
        self.assertIn("text/html", r_idx.headers.get("content-type", ""))

        r_svg = self.client.get("/media-icons/wechat_mp.svg")
        self.assertEqual(r_svg.status_code, 200)

        r2 = self.client.get("/content/config")
        self.assertEqual(r2.status_code, 200)
        self.assertIn("platforms", r2.json())

        r3 = self.client.get("/publish/wechat/status")
        self.assertEqual(r3.status_code, 200)
        self.assertIn("configured", r3.json())

    def test_studio_wechat_and_xhs_pipelines(self):
        r = self.client.get("/studio/styles")
        self.assertEqual(r.status_code, 200)
        self.assertIn("styles", r.json())

        r_txt = self.client.get("/studio/text-models")
        self.assertEqual(r_txt.status_code, 200)
        self.assertIn("models", r_txt.json())

        r_img = self.client.get("/studio/image-models")
        self.assertEqual(r_img.status_code, 200)
        self.assertIn("models", r_img.json())

        r_dirs = self.client.get("/studio/browse-dirs")
        self.assertEqual(r_dirs.status_code, 200)
        self.assertTrue(r_dirs.json()["ok"])

        # 公众号项目：新建 -> 编辑 final -> 运行 format 步 -> 重命名 -> 删除
        r_new = self.client.post("/studio/projects", json={
            "workflow": "content_pipeline",
            "inputs": {"topic": "独立拆迁测试", "platform": "公众号"},
            "title": "独立拆迁测试",
        })
        self.assertEqual(r_new.status_code, 200, r_new.text)
        proj = r_new.json()["project"]
        pid = proj["id"]
        final_idx = next(i for i, n in enumerate(proj["nodes"]) if n["id"] == "finalize")
        fmt_idx = next(i for i, n in enumerate(proj["nodes"]) if n["id"] == "format")

        r_edit = self.client.post(f"/studio/projects/{pid}/edit", json={
            "index": final_idx,
            "content": "# 测试标题\n\n这是独立后的排版测试正文。",
        })
        self.assertEqual(r_edit.status_code, 200)

        with self.client.stream("POST", f"/studio/projects/{pid}/step", json={"index": fmt_idx}) as resp:
            self.assertEqual(resp.status_code, 200)
            body = "".join(resp.iter_text())
            self.assertIn('"type": "step"', body)

        r_get = self.client.get(f"/studio/projects/{pid}")
        self.assertEqual(r_get.status_code, 200)
        layout = r_get.json()["project"]["state"].get("layout")
        self.assertIsInstance(layout, dict)
        self.assertIn("<", layout.get("html", ""))

        r_ren = self.client.post(f"/studio/projects/{pid}/rename", json={"title": "新标题"})
        self.assertEqual(r_ren.status_code, 200)
        self.assertEqual(r_ren.json()["title"], "新标题")

        r_del = self.client.delete(f"/studio/projects/{pid}")
        self.assertEqual(r_del.status_code, 200)

        # 小红书项目：新建与删除
        r_xhs = self.client.post("/studio/projects", json={
            "workflow": "xhs_pipeline",
            "inputs": {"topic": "小红书拆迁测试", "platform": "小红书"},
            "title": "小红书拆迁测试",
        })
        self.assertEqual(r_xhs.status_code, 200, r_xhs.text)
        xid = r_xhs.json()["project"]["id"]
        self.assertEqual(self.client.delete(f"/studio/projects/{xid}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
