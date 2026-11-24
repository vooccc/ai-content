# -*- coding: utf-8 -*-
"""切片 2 单元测试：免费抓取源解析、选题去重打分、一键开写建项、账号配置与数据复盘接口。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestSlice2TopicsAndMetrics(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AICONTENT_DATA_DIR"] = self.tmp.name
        from server import db
        db._INITIALIZED_PATHS.clear()

    def tearDown(self) -> None:
        os.environ.pop("AICONTENT_DATA_DIR", None)
        self.tmp.cleanup()

    def test_sources_rss_and_github_parse(self) -> None:
        from server import sources

        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Test Feed</title>
          <item>
            <title>Claude Code 实操：一人公司自动化指南</title>
            <link>https://example.com/post-1</link>
            <description><![CDATA[<p>用 AI 工作流把日常运营时间压缩 80%</p>]]></description>
          </item>
        </channel></rss>"""
        parsed = sources.parse_rss_xml(rss_xml, feed_name="测试源")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["source_name"], "测试源")
        self.assertIn("压缩 80%", parsed[0]["raw_summary"])

        fake_gh_html = """
        <article class="Box-row">
          <h2><a href="/vooccc/demo-agent">vooccc / demo-agent</a></h2>
          <p>Lightweight AI agent workflow for solo founders</p>
          <span itemprop="programmingLanguage">Python</span>
          <span>420 stars today</span>
        </article>
        """

        class _FakeGet:
            status_code = 200
            text = fake_gh_html

        with patch("server.sources.requests.get", return_value=_FakeGet()):
            gh = sources.fetch_github_trending(languages=["python"], limit=5)
        self.assertEqual(len(gh), 1)
        self.assertEqual(gh[0]["source_url"], "https://github.com/vooccc/demo-agent")
        self.assertEqual(gh[0]["popularity"], 420)

    def test_topic_refresh_dedupe_and_start_project(self) -> None:
        from fastapi.testclient import TestClient
        from server.app import app

        mock_gathered = {
            "items": [
                {
                    "source_type": "github_trending",
                    "source_name": "GitHub Trending",
                    "source_url": "https://github.com/test/ai-workflow",
                    "raw_title": "test/ai-workflow：自动化 AI 工作流",
                    "raw_summary": "帮一人公司自动化整理素材和发布",
                    "popularity": 350,
                },
                {
                    "source_type": "rss",
                    "source_name": "少数派",
                    "source_url": "https://example.com/dup",
                    "raw_title": "test/ai-workflow：自动化 AI 工作流",
                    "raw_summary": "重复标题应被去重",
                    "popularity": 0,
                },
            ],
            "stats": {"github_trending": 1, "rss": 1, "wechat_search": 0},
            "errors": [],
        }

        with TestClient(app) as client:
            with patch("server.sources.gather_all_sources", return_value=mock_gathered), \
                 patch("server.topic_engine.llm_bridge.chat_completion", side_effect=RuntimeError("offline")):
                r = client.post("/topics/refresh", json={"max_new": 5})
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertEqual(body["added"], 1)
                self.assertEqual(body["mode"], "heuristic")

            r_list = client.get("/topics?status=new")
            self.assertEqual(r_list.status_code, 200)
            topics = r_list.json()["topics"]
            self.assertEqual(len(topics), 1)
            tid = topics[0]["id"]
            chosen_title = topics[0]["suggested_titles"][0]

            r_start = client.post(f"/topics/{tid}/start", json={"selected_title": chosen_title})
            self.assertEqual(r_start.status_code, 200)
            proj = r_start.json()["project"]
            self.assertEqual(proj["topic_id"], tid)
            self.assertEqual(proj["theme"], "moyu_green")
            self.assertIn("禁用词", proj["state"]["data"]["material"])
            self.assertTrue(proj["done"][0])

            r_after = client.get("/topics?status=drafted")
            self.assertEqual(len(r_after.json()["topics"]), 1)

            # 模型与连接配置接口：保存、脱敏回显、保留旧密钥与切换模式
            r_s0 = client.get("/settings/models")
            self.assertEqual(r_s0.status_code, 200)
            r_s1 = client.put("/settings/models", json={
                "mode": "custom",
                "llm_base_url": "https://example.com/v1",
                "llm_api_key": "sk-secret-998877",
                "default_text_model": "deepseek-chat",
                "fast_text_model": "deepseek-flash",
                "default_image_model": "flux-pro",
            })
            self.assertEqual(r_s1.status_code, 200)
            s1 = r_s1.json()
            self.assertEqual(s1["active_source"], "custom")
            self.assertEqual(s1["current_model"], "deepseek-chat")
            self.assertTrue(s1["settings"]["has_llm_api_key"])
            self.assertIn("****", s1["settings"]["llm_api_key_masked"])
            self.assertNotIn("998877", json.dumps(s1))
            r_s2 = client.put("/settings/models", json={
                "mode": "custom",
                "llm_api_key": s1["settings"]["llm_api_key_masked"],
            })
            self.assertTrue(r_s2.json()["settings"]["has_llm_api_key"])

    def test_manual_topic_metrics_and_scheduler(self) -> None:
        from fastapi.testclient import TestClient
        from server import scheduler
        from server.app import app

        with TestClient(app) as client:
            with patch("server.topic_engine.llm_bridge.chat_completion", side_effect=RuntimeError("offline")):
                r_m = client.post("/topics/manual", json={"idea": "用 Claude Code 搭建个人知识库实操"})
                self.assertEqual(r_m.status_code, 200)
                self.assertGreaterEqual(r_m.json()["topic"]["score"], 80)

                r_met = client.post("/metrics", json={
                    "ref_date": "2026-11-21",
                    "title": "我用 AI 压缩了 80% 写稿时间",
                    "target_user": 800,
                    "read_user": 190,
                    "share_count": 14,
                    "fav_count": 32,
                })
                self.assertEqual(r_met.status_code, 200)

                r_get = client.get("/metrics")
                self.assertEqual(r_get.json()["summary"]["total_read_user"], 190)

                r_rev = client.post("/metrics/review")
                self.assertEqual(r_rev.status_code, 200)
                self.assertIn("190", r_rev.json()["summary"])

        # 调度器防重复执行验证
        with patch("server.topic_engine.refresh_topics") as mock_ref:
            scheduler.run_tick(datetime(2026, 11, 22, 8, 5))
            scheduler.run_tick(datetime(2026, 11, 22, 8, 10))
            self.assertEqual(mock_ref.call_count, 1)

    def test_yupi_sources_expansion_resonance_and_is_real(self) -> None:
        from server import sources, topic_engine

        # 1. Query Expansion 缓存 + 禁止泛化词
        with patch("server.topic_engine.llm_bridge.chat_completion", return_value='{"Claude Code": ["claude-code", "AI", "Anthropic CLI"]}'):
            terms = topic_engine.expand_keywords(["Claude Code"])
            self.assertIn("claude-code", terms)
            self.assertIn("Anthropic CLI", terms)
            self.assertNotIn("AI", terms)

        # 2. Hacker News / B站 / 微博热搜解析 mock
        class _FakeResp:
            def __init__(self, payload, status_code=200):
                self._payload = payload
                self.status_code = status_code

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"http {self.status_code}")

            def json(self):
                return self._payload

        def _fake_get(url, **kwargs):
            if "hn.algolia.com" in url:
                return _FakeResp({"hits": [{
                    "objectID": "101",
                    "title": "Claude Code MCP workflow for solo founders",
                    "url": "https://example.com/hn-claude-code",
                    "points": 180,
                    "num_comments": 42,
                }]})
            if "search/type" in url and kwargs.get("params", {}).get("search_type") == "video":
                return _FakeResp({"code": 0, "data": {"result": [{
                    "bvid": "BV1xx411c7mD",
                    "title": "<em class=\"keyword\">Claude Code</em> 一人公司实操工作流",
                    "description": "从零配置 MCP",
                    "author": "实操UP",
                    "play": 12000,
                    "like": 420,
                    "review": 38,
                }]}})
            if "weibo.com/ajax/side/hotSearch" in url:
                return _FakeResp({"ok": 1, "data": {"realtime": [
                    {"note": "Claude Code 爆火", "num": 520000},
                    {"note": "无关娱乐八卦", "num": 999999},
                ]}})
            return _FakeResp({})

        with patch("server.sources.requests.get", side_effect=_fake_get):
            hn, hn_err = sources.fetch_hackernews_topics(["Claude Code"])
            bili, bili_err = sources.fetch_bilibili_topics(["Claude Code"])
            wb, wb_err = sources.fetch_weibo_hot_topics(["Claude Code"])
            self.assertEqual(hn_err, [])
            self.assertEqual(bili_err, [])
            self.assertEqual(wb_err, [])
            self.assertEqual(len(hn), 1)
            self.assertEqual(len(bili), 1)
            self.assertEqual(len(wb), 1)
            self.assertNotIn("<em", bili[0]["raw_title"])

        # 3. 多源共振检测 + is_real=false 淘汰
        merged = topic_engine.annotate_cross_source_resonance([
            {**hn[0], "matched_terms": ["Claude Code"]},
            {**bili[0], "matched_terms": ["Claude Code"]},
            {"source_type": "rss", "source_name": "RSS", "source_url": "https://x.com/spam", "raw_title": "震惊！AI 标题党水文", "raw_summary": "水文", "popularity": 0, "matched_terms": []},
        ])
        self.assertGreaterEqual(len(merged[0]["resonance_sources"]), 2)
        self.assertEqual(merged[2]["resonance_sources"], [])

        fake_llm_out = json.dumps([
            {"idx": 0, "is_real": True, "score": 88, "category": "周二实操", "suggested_titles": ["实测 Claude Code MCP 工作流"], "angle": "实操", "reason": "干货"},
            {"idx": 2, "is_real": False, "score": 90, "category": "周六深度", "suggested_titles": ["水文"], "angle": "水文", "reason": "假消息"},
        ], ensure_ascii=False)
        with patch("server.topic_engine.llm_bridge.chat_completion", return_value=fake_llm_out):
            kept = topic_engine._score_and_rewrite_with_llm(merged, {"niche": "AI", "audience": "dev", "cadence": "", "title_formulas": []}, top_n=5)
            self.assertIsNotNone(kept)
            self.assertEqual(len(kept), 1)
            self.assertIn("多源共振", kept[0]["reason"])

    @unittest.skipUnless(os.getenv("RUN_LIVE_SOURCES") == "1", "set RUN_LIVE_SOURCES=1 for live source check")
    def test_live_yupi_sources_probe(self) -> None:
        from server import sources

        hn, hn_err = sources.fetch_hackernews_topics(["AI Agent"], hours=72, min_points=10, limit_per_kw=3)
        bili, bili_err = sources.fetch_bilibili_topics(["Claude Code"], limit_per_kw=3)
        wb, wb_err = sources.fetch_weibo_hot_topics(["AI"])
        print(f"\n[LIVE] hn={len(hn)} err={hn_err}; bili={len(bili)} err={bili_err}; weibo={len(wb)} err={wb_err}")
        self.assertGreater(len(hn) + len(bili) + len(wb), 0)

    @unittest.skipUnless(os.getenv("RUN_LIVE_REFRESH") == "1", "set RUN_LIVE_REFRESH=1 for live refresh check")
    def test_live_refresh_endpoint(self) -> None:
        import time as _t
        from fastapi.testclient import TestClient
        from server.app import app

        t0 = _t.monotonic()
        with TestClient(app) as client:
            r = client.post("/topics/refresh", json={"max_new": 8})
            dt = _t.monotonic() - t0
            d = r.json()
            print(f"\n[LIVE_REFRESH] dt={dt:.2f}s status={r.status_code} mode={d.get('mode')} fetched={d.get('fetched')} added={d.get('added')} stats={d.get('stats')} errs={d.get('errors')}")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(d.get("ok"))
            self.assertGreater(d.get("added", 0), 0)

    @unittest.skipUnless(os.getenv("RUN_LIVE_REFRESH") == "1", "set RUN_LIVE_REFRESH=1")
    def test_live_llm_bridge_diag(self) -> None:
        from server import llm_bridge
        cat = llm_bridge.build_model_catalog()
        dm = cat.get("default")
        cfg = (cat.get("models") or {}).get(dm, {})
        print(f"\n[LLM_DIAG] default={dm} provider={cfg.get('provider')} has_key={bool(cfg.get('api_key'))} total_models={len(cat.get('models') or {})}")
        try:
            res = llm_bridge.chat_completion([{"role": "user", "content": "只回复OK两字"}], max_tokens=500, timeout=20)
            print(f"[LLM_DIAG] chat_ok={res!r}")
        except Exception as e:
            print(f"[LLM_DIAG] chat_err={type(e).__name__}: {e}")
        providers, cur = llm_bridge._load_providers_raw()
        avail = [(pid, p.get("transport"), bool(p.get("api_key")), [m.get("id") if isinstance(m, dict) else m for m in (p.get("models") or [])][:4]) for pid, p in providers.items() if p.get("enabled", True)]
        print(f"[LLM_DIAG] cur={cur} avail={avail}")

    def test_clustering_viral_badge_import_and_funnel(self) -> None:
        from fastapi.testclient import TestClient
        from server import db, topic_engine
        from server.app import app

        badge, bonus = topic_engine.compute_viral_badge(plays=85000, followers=3200)
        self.assertIn("低粉爆款", badge)
        self.assertGreater(bonus, 0)

        clustered = topic_engine.cluster_candidates([
            {
                "source_type": "github_trending",
                "source_name": "GitHub Trending",
                "source_url": "https://github.com/acme/agent-kit",
                "raw_title": "acme/agent-kit: 开源自动化工作流工具",
                "raw_summary": "一键编排 AI Agent 工作流",
                "popularity": 450,
            },
            {
                "source_type": "bilibili",
                "source_name": "B站·测试UP",
                "source_url": "https://www.bilibili.com/video/BV1xx",
                "raw_title": "开源自动化工作流工具 agent-kit 实操上手",
                "raw_summary": "5分钟跑通 agent-kit",
                "popularity": 8000,
                "metrics_badge": "低粉爆款 ×15",
                "_viral_bonus": 14,
            },
        ])
        self.assertEqual(len(clustered), 1)
        self.assertEqual(len(clustered[0]["raw_signals"]), 2)
        self.assertIn("低粉爆款", clustered[0]["metrics_badge"])

        csv_text = (
            "标题,作者,粉丝,播放,点赞,平台,链接\n"
            "用 Claude Code 10分钟搭完个人工作台,小王AI,4000,6万,1200,小红书,https://xhs.com/1\n"
            "普通AI新闻汇总,大号日报,80万,2万,100,公众号,https://mp.weixin.qq.com/2\n"
        )
        with TestClient(app) as client:
            r_prev = client.post("/topics/import", json={"text": csv_text, "dry_run": True})
            self.assertEqual(r_prev.status_code, 200)
            self.assertEqual(r_prev.json()["new_count"], 2)
            self.assertEqual(r_prev.json()["low_fan_count"], 1)

            r_imp = client.post("/topics/import", json={"text": csv_text, "dry_run": False})
            self.assertEqual(r_imp.status_code, 200)
            self.assertEqual(r_imp.json()["added"], 2)

            r_list = client.get("/topics?filter=resonance")
            self.assertEqual(r_list.status_code, 200)
            body = r_list.json()
            self.assertEqual(body["counts"]["new"], 2)
            self.assertEqual(body["counts"]["resonance"], 1)
            self.assertIn("低粉爆款", body["topics"][0]["metrics_badge"])

            # 恢复已忽略选题
            tid = body["topics"][0]["id"]
            client.patch(f"/topics/{tid}", json={"status": "ignored"})
            self.assertEqual(client.get("/topics").json()["counts"]["ignored"], 1)
            client.patch(f"/topics/{tid}", json={"status": "new"})
            self.assertEqual(client.get("/topics").json()["counts"]["ignored"], 0)

            # 信息源清单与池内计数、RSS enabled=False 过滤
            r_src = client.get("/topics/sources")
            self.assertEqual(r_src.status_code, 200)
            src_body = r_src.json()
            self.assertTrue(src_body["ok"])
            self.assertIn("wechat_search", src_body["sources_config"])
            self.assertGreaterEqual(src_body["pool_counts"].get("import", 0), 1)
            from server import sources
            items, errs, detail = sources.fetch_rss_feeds(
                [{"name": "DisabledFeed", "url": "http://127.0.0.1:9/rss.xml", "enabled": False}]
            )
            self.assertEqual(items, [])
            self.assertEqual(errs, [])
            self.assertEqual(detail, {})

    def test_intel_stream_presets_and_promote(self):
        from fastapi.testclient import TestClient
        from server import intel_engine, sources
        from server.app import app
        with TestClient(app) as client:
            # 1. 一键导入一线 AI 官方博客预设包（幂等不重复）
            r_pre1 = client.post("/topics/sources/apply-presets")
            self.assertEqual(r_pre1.status_code, 200)
            self.assertEqual(r_pre1.json()["added"], len(sources.OFFICIAL_AI_RSS_PRESETS))
            r_pre2 = client.post("/topics/sources/apply-presets")
            self.assertEqual(r_pre2.json()["added"], 0)

            # 2. Mock 采集与 LLM，测试实时快讯刷新 + 可信度分级 + 一键转选题与直开创作台
            fake_gathered = {
                "items": [
                    {
                        "source_type": "hf_papers",
                        "source_name": "HF Daily Papers",
                        "source_url": "https://huggingface.co/papers/2611.0001",
                        "raw_title": "Agentic Memory Scaling Laws",
                        "raw_summary": "A study on scaling memory for long-horizon coding agents | 点赞 42",
                        "popularity": 420,
                    },
                    {
                        "source_type": "github_trending",
                        "source_name": "GitHub Trending",
                        "source_url": "https://github.com/acme/claw-flow",
                        "raw_title": "acme/claw-flow: Agentic workflow engine",
                        "raw_summary": "Open source agent workflow engine",
                        "popularity": 1200,
                    },
                    {
                        "source_type": "hackernews",
                        "source_name": "Hacker News",
                        "source_url": "https://news.ycombinator.com/item?id=999",
                        "raw_title": "acme/claw-flow hits front page on HN",
                        "raw_summary": "HN discussion on claw-flow",
                        "popularity": 300,
                    },
                ],
                "stats": {"hf_papers": 1, "github_trending": 1, "hackernews": 1},
                "rss_detail": {},
                "errors": [],
            }
            with patch("server.sources.gather_all_sources", return_value=fake_gathered), \
                 patch("server.intel_engine._summarize_batch_with_llm", return_value={}):
                r_ref = client.post("/intel/refresh", json={"limit": 20})
                self.assertEqual(r_ref.status_code, 200)
                body = r_ref.json()
                self.assertTrue(body["ok"])
                self.assertEqual(body["added"], 2)  # claw-flow 聚簇合并为 1 条

            r_list = client.get("/intel")
            self.assertEqual(r_list.status_code, 200)
            intel_items = r_list.json()["items"]
            self.assertEqual(len(intel_items), 2)
            self.assertEqual(intel_items[0]["credibility"], "一手官方")

            # 3. 一键升格进选题池并直接开写
            iid = intel_items[0]["id"]
            r_pro = client.post(f"/intel/{iid}/promote", json={"start_project": True})
            self.assertEqual(r_pro.status_code, 200)
            pro = r_pro.json()
            self.assertTrue(pro["ok"])
            self.assertIn("project", pro)
            self.assertEqual(pro["topic"]["status"], "drafted")

            # 4. 幂等再次 promote 不重复建 topic
            res_again = intel_engine.promote_intel_to_topic(iid)
            self.assertTrue(res_again["already_existed"])

    def test_reddit_and_bluesky_fetchers(self):
        from unittest.mock import MagicMock, patch
        from server import intel_engine, sources

        sources._REDDIT_CACHE.clear()
        sources._BLUESKY_CACHE.clear()

        mock_reddit_resp = MagicMock()
        mock_reddit_resp.raise_for_status.return_value = None
        mock_reddit_resp.json.return_value = {
            "data": [
                {
                    "title": "New open weights 70B beats proprietary models on coding",
                    "permalink": "/r/LocalLLaMA/comments/abc123/new_open_weights/",
                    "url": "https://huggingface.co/org/model",
                    "score": 420,
                    "num_comments": 65,
                    "selftext": "Benchmarks and quantization notes...",
                },
                {
                    "title": "Deleted spam post",
                    "removed_by_category": "moderator",
                    "permalink": "/r/LocalLLaMA/comments/spam/",
                },
            ]
        }

        mock_bsky_resp = MagicMock()
        mock_bsky_resp.raise_for_status.return_value = None
        mock_bsky_resp.json.return_value = {
            "feed": [
                {
                    "reason": {"$type": "app.bsky.feed.defs#reasonRepost"},
                    "post": {"uri": "at://did:plc:x/app.bsky.feed.post/1", "record": {"text": "Pure repost should skip"}},
                },
                {
                    "post": {
                        "uri": "at://did:plc:x/app.bsky.feed.post/2",
                        "author": {"handle": "karpathy.bsky.social", "displayName": "Andrej Karpathy"},
                        "record": {"text": "Interesting pattern on agent memory loops and evaluation harnesses."},
                        "likeCount": 800,
                        "repostCount": 120,
                        "replyCount": 40,
                        "embed": {"external": {"title": "Agent Memory Post", "uri": "https://example.com/mem"}},
                    }
                },
            ]
        }

        with patch("server.sources.requests.get", side_effect=[mock_reddit_resp, mock_bsky_resp]):
            r_items, r_errs = sources.fetch_reddit_topics(["LocalLLaMA"], limit_per_sub=5)
            b_items, b_errs = sources.fetch_bluesky_topics(["karpathy.bsky.social"], limit_per_author=5)

        self.assertEqual(r_errs, [])
        self.assertEqual(len(r_items), 1)
        self.assertEqual(r_items[0]["source_type"], "reddit")
        self.assertEqual(r_items[0]["popularity"], 420 + 65 * 3)
        self.assertEqual(intel_engine.classify_credibility(r_items[0]), "社区热议")

        self.assertEqual(b_errs, [])
        self.assertEqual(len(b_items), 1)
        self.assertEqual(b_items[0]["source_type"], "bluesky")
        self.assertIn("Agent Memory Post", b_items[0]["raw_title"])
        self.assertEqual(intel_engine.classify_credibility(b_items[0]), "社区热议")

    def test_metrics_bulk_import_and_48001_message(self):
        from fastapi.testclient import TestClient
        from server.app import app
        from server import wechat_mp

        client = TestClient(app)
        tsv = "发表时间\t文章标题\t总阅读人数\t分享人数\t收藏人数\t在看\n2026-11-22\t实测 Claude Code 工作流\t1.2万\t45\t92\t31\n"
        r_pre = client.post("/metrics/import", json={"text": tsv, "dry_run": True})
        self.assertEqual(r_pre.status_code, 200)
        pre = r_pre.json()
        self.assertTrue(pre["ok"])
        self.assertEqual(pre["count"], 1)
        self.assertEqual(pre["total_reads"], 12000)

        r_imp = client.post("/metrics/import", json={"text": tsv, "dry_run": False})
        self.assertEqual(r_imp.status_code, 200)
        self.assertEqual(r_imp.json()["imported"], 1)

        with patch("server.wechat_mp.fetch_article_total", side_effect=wechat_mp.WeChatError("unauth", errcode=48001)):
            r_sync = client.post("/metrics/sync-wechat", json={"days": 7})
        self.assertEqual(r_sync.status_code, 400)
        self.assertIn("IP 白名单与草稿箱推送权限正常", r_sync.json()["error"])

    def test_intel_translate_pending_and_full_batch(self):
        from server import db, intel_engine
        db.upsert_intel_items([{
            "cluster_key": "u_en_test_1",
            "title": "Pure English Paper Title",
            "summary": "Pure English summary body",
            "raw_title": "Pure English Paper Title",
            "source_type": "hf_papers",
            "source_name": "HF Daily Papers",
            "source_url": "https://huggingface.co/papers/9999.00001",
            "credibility": "一手官方",
        }])
        fake_reply = '[{"idx": 0, "title": "纯英文论文的中文快讯标题", "summary": "中文摘要说明核心成果", "category": "论文研究", "tags": ["论文"]}]'
        with patch("server.llm_bridge.active_source", return_value="mock"), \
             patch("server.llm_bridge.chat_completion", return_value=fake_reply):
            res = intel_engine.translate_pending_intel(limit=20)
        self.assertTrue(res["ok"])
        self.assertEqual(res["translated"], 1)
        self.assertEqual(res["remaining"], 0)
        items = db.list_intel_items(limit=10)
        self.assertEqual(items[0]["title"], "纯英文论文的中文快讯标题")
        self.assertEqual(items[0]["raw_title"], "Pure English Paper Title")

    def test_smart_short_title_no_midword_cut(self):
        from server import sources, topic_engine
        full = "【中配】57分钟带你拆解 Agent 设计模式，从ReAct到上下文工程"
        short = topic_engine._smart_short_title(full, max_len=36)
        self.assertEqual(short, "57分钟带你拆解 Agent 设计模式，从ReAct到上下文工程")
        self.assertNotIn("从R", short.replace("ReAct", ""))

        # 超长英文词边界测试：不能把 SuperLongWord 砍成 Super
        long_title = "深入解析多智能体协作架构中的 ContextEngineeringBestPractices 与实战落地"
        s2 = topic_engine._smart_short_title(long_title, max_len=30)
        self.assertNotIn("ContextE", s2)

        # sources.trim_clean 边界测试
        trimmed = sources.trim_clean("An open source autonomous coding assistant framework", 28)
        self.assertFalse(trimmed.endswith("autono…"))

    def test_x_cookie_masked_storage_and_parser(self):
        from fastapi.testclient import TestClient
        from server import sources, settings_store
        from server.app import app

        client = TestClient(app)
        # 1. 保存 X Cookie 后，GET /topics/sources 只返回脱敏占位，绝不回传明文
        r = client.post("/topics/sources/x-auth", json={
            "auth_token": "secret_auth_token_1234567890",
            "ct0": "secret_ct0_abcdef1234567890",
            "x_mode": "following",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["x_auth"]["has_x_auth_token"])
        self.assertIn("****", body["x_auth"]["x_auth_token_masked"])
        self.assertNotIn("secret_auth_token_1234567890", str(body))
        self.assertEqual(settings_store.load_settings()["x_auth_token"], "secret_auth_token_1234567890")

        # 2. 测试 _parse_x_graphql_tweets 过滤纯转发并解析原创/长推文
        fake_gql = {
            "data": {
                "home": {
                    "home_timeline_urt": {
                        "instructions": [
                            {
                                "entries": [
                                    {
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "__typename": "Tweet",
                                                        "rest_id": "1001",
                                                        "core": {"user_results": {"result": {"core": {"screen_name": "enzjjq", "name": "John"}}}},
                                                        "legacy": {
                                                            "id_str": "1001",
                                                            "full_text": "RT @someone: pure retweet should be skipped",
                                                            "retweeted_status_result": {"result": {}},
                                                            "is_quote_status": False,
                                                        },
                                                    }
                                                }
                                            }
                                        }
                                    },
                                    {
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "__typename": "TweetWithVisibilityResults",
                                                        "tweet": {
                                                            "rest_id": "1002",
                                                            "core": {"user_results": {"result": {"core": {"screen_name": "karpathy", "name": "Andrej Karpathy"}}}},
                                                            "note_tweet": {
                                                                "note_tweet_results": {
                                                                    "result": {"text": "Released Claude Code multi-agent workflow benchmark today https://t.co/abc"}
                                                                }
                                                            },
                                                            "legacy": {
                                                                "id_str": "1002",
                                                                "full_text": "short truncated",
                                                                "favorite_count": 420,
                                                                "retweet_count": 85,
                                                                "reply_count": 19,
                                                                "entities": {"urls": [{"expanded_url": "https://github.com/karpathy/demo"}]},
                                                            },
                                                        },
                                                    }
                                                }
                                            }
                                        }
                                    },
                                ]
                            }
                        ]
                    }
                }
            }
        }
        parsed = sources._parse_x_graphql_tweets(fake_gql)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["source_type"], "x")
        self.assertIn("@karpathy", parsed[0]["raw_title"])
        self.assertIn("https://github.com/karpathy/demo", parsed[0]["raw_summary"])

        # 3. 测试 _build_x_search_query 与 /topics/sources/test-x mock 401/200（含 SearchTimeline POST）
        q_str = sources._build_x_search_query(["AI Agent", "Claude Code"], min_faves=150, days=4)
        self.assertIn('"AI Agent" OR "Claude Code"', q_str)
        self.assertIn("min_faves:150", q_str)
        self.assertIn("since:", q_str)
        self.assertIn("-filter:retweets", q_str)

        with patch("server.sources._resolve_x_graphql_ops", return_value={
            "HomeLatestTimeline": {"queryId": "QID123", "switches": ["s1"]},
            "SearchTimeline": {"queryId": "QID456", "switches": ["s2"]},
        }), patch("server.sources.requests.get") as mget, patch("server.sources.requests.post") as mpost:
            mget.return_value.status_code = 401
            res401 = client.post("/topics/sources/test-x", json={})
            self.assertEqual(res401.status_code, 400)
            self.assertIn("401", res401.json()["error"])

            mget.return_value.status_code = 200
            mget.return_value.raise_for_status = lambda: None
            mget.return_value.json.return_value = fake_gql
            mpost.return_value.status_code = 200
            mpost.return_value.raise_for_status = lambda: None
            mpost.return_value.json.return_value = fake_gql
            res200 = client.post("/topics/sources/test-x", json={"x_search_enabled": True, "x_min_faves": 200})
            self.assertEqual(res200.status_code, 200)
            self.assertEqual(res200.json()["count"], 1)  # 同 URL 去重合并
            self.assertTrue(mpost.called)

    def test_xiaohongshu_dual_engine_xhshow_and_opencli(self):
        from server import settings_store, sources
        from server.app import app
        from fastapi.testclient import TestClient

        self.assertEqual(sources._parse_xhs_like_count("1.2万"), 12000)
        self.assertEqual(sources._parse_xhs_like_count("350+"), 350)
        parsed_ck = sources._parse_xhs_cookie_str("Cookie: a1=abc123; web_session=ws999; nickname=中文名")
        self.assertEqual(parsed_ck, {"a1": "abc123", "web_session": "ws999"})

        client = TestClient(app)
        res_save = client.post(
            "/topics/sources/xhs-auth",
            json={
                "cookie": "a1=test_a1_token_123456; web_session=test_ws_987654",
                "xhs_mode": "xhshow",
                "xhs_keywords": ["AI工具", "一人公司"],
            },
        )
        self.assertEqual(res_save.status_code, 200)
        self.assertTrue(res_save.json()["xhs_auth"]["has_xhs_cookie"])
        self.assertNotIn("test_ws_987654", res_save.json()["xhs_auth"]["xhs_cookie_masked"])

        fake_feed = {
            "success": True,
            "data": {
                "items": [{
                    "id": "6900112233445566778899aa",
                    "xsec_token": "tok_feed_1",
                    "note_card": {
                        "display_title": "Claude Code 一人公司实战复盘",
                        "type": "normal",
                        "user": {"nickname": "独立开发者阿杰"},
                        "interact_info": {"liked_count": "1.5万", "collected_count": "3200"},
                    },
                }]
            },
        }
        fake_search = {
            "success": True,
            "data": {
                "items": [{
                    "id": "6900112233445566778899bb",
                    "xsec_token": "tok_search_2",
                    "note_card": {
                        "display_title": "AI Agent 自动化工作流拆解",
                        "type": "video",
                        "user": {"nickname": "效率实验室"},
                        "interact_info": {"liked_count": "8200", "collected_count": "1100"},
                    },
                }]
            },
        }
        sources._XHS_CACHE["items"] = []
        with patch("server.sources.requests.post") as mpost, patch("server.sources.requests.get") as mget:
            def _post_side_effect(url, **kwargs):
                resp = MagicMock()
                resp.status_code = 200
                resp.raise_for_status = lambda: None
                if "homefeed" in url:
                    resp.json.return_value = fake_feed
                elif "search/notes" in url:
                    resp.json.return_value = fake_search
                else:
                    resp.json.return_value = {"success": True, "data": {}}
                return resp

            mpost.side_effect = _post_side_effect
            mget.return_value.status_code = 200
            mget.return_value.raise_for_status = lambda: None
            mget.return_value.json.return_value = {"success": True, "data": {}}

            res_xh = client.post("/topics/sources/test-xhs", json={"xhs_mode": "xhshow"})
            self.assertEqual(res_xh.status_code, 200)
            self.assertEqual(res_xh.json()["count"], 2)
            self.assertIn("xsec_token=", res_xh.json()["samples"][0]["url"])

        # 测试 OpenCLI 引擎解析与未安装提示
        with patch("server.sources._find_opencli_bin", return_value=""):
            res_no_cli = client.post("/topics/sources/test-xhs", json={"xhs_mode": "opencli"})
            self.assertEqual(res_no_cli.status_code, 400)
            self.assertIn("opencli", res_no_cli.json()["error"].lower())

        fake_cli_out = json.dumps([
            {"title": "OpenCLI 抓到的高赞 AI 笔记", "author": "测试博主", "likes": "2.3万", "url": "https://www.xiaohongshu.com/explore/abc?xsec_token=t1"}
        ])
        with patch("server.sources._find_opencli_bin", return_value="opencli"), \
             patch("server.sources._get_opencli_daemon_status", return_value={"running": True, "extension_connected": False, "version": "2.0.3"}):
            res_no_ext = client.post("/topics/sources/test-xhs", json={"xhs_mode": "opencli"})
            self.assertEqual(res_no_ext.status_code, 400)
            self.assertIn("扩展", res_no_ext.json()["error"])

        with patch("server.sources._find_opencli_bin", return_value="opencli"), \
             patch("server.sources._get_opencli_daemon_status", return_value={"running": True, "extension_connected": True, "version": "2.0.3"}), \
             patch("server.sources.subprocess.run") as mrun:
            mrun.return_value.returncode = 0
            mrun.return_value.stdout = fake_cli_out
            mrun.return_value.stderr = ""
            res_cli = client.post("/topics/sources/test-xhs", json={"xhs_mode": "opencli"})
            self.assertEqual(res_cli.status_code, 200)
            self.assertEqual(res_cli.json()["mode"], "opencli")
            self.assertEqual(res_cli.json()["count"], 1)

    def test_intel_source_filter_and_counts(self):
        from fastapi.testclient import TestClient
        from server.app import app
        from server import db, intel_engine, topic_engine

        db.upsert_intel_items([
            {
                "cluster_key": "k_x_1",
                "title": "X 独家爆料",
                "summary": "s1",
                "raw_title": "X exclusive",
                "source_type": "x",
                "source_name": "X·Sam",
                "source_url": "https://x.com/sam/status/1",
                "signals": [{"source_type": "x", "source_name": "X·Sam", "title": "X exclusive", "url": "https://x.com/sam/status/1"}],
                "credibility": "社区热议",
                "category": "大模型动态",
                "tags": ["X"],
                "popularity": 500,
            },
            {
                "cluster_key": "k_xhs_1",
                "title": "小红书 AI 实操爆款",
                "summary": "s2",
                "raw_title": "AI实操笔记",
                "source_type": "xiaohongshu",
                "source_name": "小红书热搜·测试",
                "source_url": "https://www.xiaohongshu.com/explore/xhs1",
                "signals": [{"source_type": "xiaohongshu", "source_name": "小红书热搜·测试", "title": "AI实操笔记", "url": "https://www.xiaohongshu.com/explore/xhs1"}],
                "credibility": "社区热议",
                "category": "Agent与工具",
                "tags": ["小红书"],
                "popularity": 1200,
            },
            {
                "cluster_key": "k_rss_1",
                "title": "OpenAI 官方博客",
                "summary": "s3",
                "raw_title": "OpenAI post",
                "source_type": "rss",
                "source_name": "OpenAI News",
                "source_url": "https://openai.com/news/test-x-slug",
                "signals": [{"source_type": "rss", "source_name": "OpenAI News", "title": "OpenAI post", "url": "https://openai.com/news/test-x-slug"}],
                "credibility": "一手官方",
                "category": "大模型动态",
                "tags": ["OpenAI"],
                "popularity": 100,
            },
        ])
        client = TestClient(app)
        res_all = client.get("/intel").json()
        self.assertEqual(res_all["source_counts"].get("x"), 1)
        self.assertEqual(res_all["source_counts"].get("xiaohongshu"), 1)
        self.assertEqual(res_all["source_counts"].get("rss"), 1)

        res_x = client.get("/intel", params={"source_type": "x"}).json()
        self.assertEqual(len(res_x["items"]), 1)
        self.assertEqual(res_x["items"][0]["source_type"], "x")

        res_xhs = client.get("/intel", params={"source_type": "xiaohongshu"}).json()
        self.assertEqual(len(res_xhs["items"]), 1)
        self.assertEqual(res_xhs["items"][0]["source_type"], "xiaohongshu")

        picked = intel_engine._select_balanced_clusters(
            [
                {"source_type": "rss", "source_name": "arXiv cs.AI", "popularity": 100},
                {"source_type": "rss", "source_name": "arXiv cs.AI", "popularity": 90},
                {"source_type": "rss", "source_name": "arXiv cs.AI", "popularity": 80},
                {"source_type": "xiaohongshu", "source_name": "小红书热搜", "popularity": 50},
                {"source_type": "x", "source_name": "X·OpenAI", "popularity": 60},
            ],
            limit=3,
        )
        picked_types = {p["source_type"] for p in picked}
        self.assertIn("x", picked_types)
        self.assertIn("xiaohongshu", picked_types)

        # 验证仅含泛词 "AI Agent" 的不相关笔记不会被错聚成一簇，且均衡采样保护小红书热搜与 X
        c_res = topic_engine.cluster_candidates([
            {"source_type": "xiaohongshu", "source_name": "小红书热搜·A", "source_url": "u1", "raw_title": "财务技能+AI Agent一个人也能启动副业", "popularity": 100},
            {"source_type": "xiaohongshu", "source_name": "小红书热搜·B", "source_url": "u2", "raw_title": "Codex 千万别裸装，这几个 AI Agent Skills 必须装上", "popularity": 900},
        ])
        self.assertEqual(len(c_res), 2)

        many_rss = [
            {"source_type": "rss", "source_name": "RSS", "raw_title": f"RSS {i}", "popularity": 9999 - i, "metrics_badge": "低粉爆款 ×20"}
            for i in range(40)
        ]
        many_rss.append({"source_type": "xiaohongshu", "source_name": "小红书热搜·C", "raw_title": "XHS Hot", "popularity": 50})
        many_rss.append({"source_type": "x", "source_name": "X·Sam", "raw_title": "X Post", "popularity": 40})
        bal = topic_engine._select_balanced_topic_candidates(many_rss, limit=12)
        bal_types = {b["source_type"] for b in bal}
        self.assertIn("xiaohongshu", bal_types)
        self.assertIn("x", bal_types)

        db.insert_topic({
            "account_id": db.get_primary_account()["id"],
            "source_type": "bilibili",
            "source_name": "B站·UP",
            "source_url": "https://bilibili.com/video/1",
            "raw_title": "聚合主题",
            "raw_summary": "sum",
            "suggested_titles": ["聚合主题"],
            "raw_signals": [
                {"source_type": "bilibili", "source_name": "B站·UP", "title": "聚合主题", "url": "https://bilibili.com/video/1"},
                {"source_type": "xiaohongshu", "source_name": "小红书热搜·D", "title": "同款笔记", "url": "https://xiaohongshu.com/explore/2"},
            ],
            "score": 88,
            "status": "new",
        })
        self.assertGreaterEqual(db.topic_source_counts().get("xiaohongshu", 0), 1)
        xhs_topics = db.list_topics(source_type="xiaohongshu")
        self.assertTrue(any(t["raw_title"] == "聚合主题" for t in xhs_topics))

    def test_xhs_engagement_badge_and_enrich_route(self):
        from fastapi.testclient import TestClient
        from server.app import app
        from server import db, intel_engine, sources

        self.assertEqual(sources._format_xhs_engagement_badge(50000, 7114, 1317), "👍 5万 · ⭐ 7114 · 💬 1317")
        self.assertEqual(sources._format_xhs_engagement_badge(18500, 0, 0), "👍 1.9万")

        tp = db.insert_topic({
            "source_type": "xiaohongshu",
            "source_name": "小红书热搜·测试博主",
            "source_url": "https://www.xiaohongshu.com/explore/6ade9b2a00000000180257ae?xsec_token=abc",
            "raw_title": "用 AI Skill 自动整理数据",
            "raw_summary": "👍 1.2万 · 作者 测试博主",
            "engagement_badge": "👍 1.2万",
            "engagement": {"likes": 12000, "collects": 0, "comments": 0},
            "score": 88,
        })
        self.assertEqual(tp["engagement_badge"], "👍 1.2万")
        self.assertEqual(tp["engagement"].get("likes"), 12000)

        with patch.object(
            sources,
            "fetch_xiaohongshu_note_detail",
            return_value={
                "likes": 12500,
                "collects": 3400,
                "comments": 420,
                "content": "完整实操步骤：第一步配置 Skill，第二步接飞书自动出周报。",
                "engagement": {"likes": 12500, "collects": 3400, "comments": 420},
                "engagement_badge": "👍 1.2万 · ⭐ 3400 · 💬 420",
            },
        ):
            client = TestClient(app)
            r = client.post(f"/topics/{tp['id']}/enrich")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["topic"]["engagement_badge"], "👍 1.2万 · ⭐ 3400 · 💬 420")
            self.assertEqual(body["topic"]["engagement"]["collects"], 3400)
            self.assertEqual(body["topic"]["engagement"]["comments"], 420)
            self.assertIn("第一步配置 Skill", body["topic"]["raw_summary"])

        # 快讯升格选题时透传 engagement_badge & engagement
        db.upsert_intel_items([
            {
                "cluster_key": "xhs_eng_1",
                "title": "小红书高赞 AI 工作流实测",
                "summary": "详细拆解",
                "raw_title": "小红书高赞 AI 工作流实测",
                "source_type": "xiaohongshu",
                "source_name": "小红书热搜·A",
                "source_url": "https://www.xiaohongshu.com/explore/1111222233334444",
                "engagement_badge": "👍 2.5万 · ⭐ 8900 · 💬 650",
                "engagement": {"likes": 25000, "collects": 8900, "comments": 650},
                "popularity": 25000,
            }
        ])
        items = db.list_intel_items(source_type="xiaohongshu")
        xhs_in = [x for x in items if x["cluster_key"] == "xhs_eng_1"][0]
        promoted = intel_engine.promote_intel_to_topic(xhs_in["id"])
        self.assertEqual(promoted["topic"]["engagement_badge"], "👍 2.5万 · ⭐ 8900 · 💬 650")
        self.assertEqual(promoted["topic"]["engagement"]["comments"], 650)


if __name__ == "__main__":
    unittest.main()
