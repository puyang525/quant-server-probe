import importlib.util
import json
import pathlib
import tempfile
from unittest import mock
import unittest

ROOT=pathlib.Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location("probe",ROOT/"quant_net_probe.py")
probe=importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_stats(self):
        s=probe.stats([1,2,3,4,100])
        self.assertEqual(s["median_ms"],3)
        self.assertEqual(s["n"],5)

    def test_latency_score_monotonic(self):
        self.assertGreater(probe.latency_score(10),probe.latency_score(100))
        self.assertGreater(probe.latency_score(100),probe.latency_score(500))

    def test_polymarket_geo(self):
        ep={"capability":"polymarket_geoblock"}
        out={"http":{"success_rate":1,"last":{"_json":{"blocked":False,"country":"KR","ip":"1.2.3.4"}}}}
        probe.interpret_capability(ep,out)
        self.assertEqual(out["capability_evidence"]["verdict"],"geo_check_passed")
        self.assertNotIn("_json",out["http"]["last"])

    def test_polymarket_japan_frontend_only(self):
        ep={"capability":"polymarket_geoblock"}
        out={"http":{"success_rate":1,"last":{"_json":{"blocked":True,"country":"JP","region":"13"}}}}
        probe.interpret_capability(ep,out)
        evidence=out["capability_evidence"]
        self.assertEqual(evidence["verdict"],"frontend_close_only_api_available")
        self.assertTrue(evidence["api_new_orders_allowed"])
        self.assertTrue(evidence["policy_raw_conflict"])

    def test_polymarket_singapore_api_close_only(self):
        policy=probe.polymarket_policy("SG",None)
        self.assertFalse(policy["api_new_orders_allowed"])
        self.assertTrue(policy["api_close_allowed"])

    def test_binance_perpetual(self):
        ep={"capability":"binance_usdm_perpetual"}
        out={"http":{"success_rate":1,"last":{"_json":{"symbols":[{"symbol":"BTCUSDT","contractType":"PERPETUAL","status":"TRADING"}]}}}}
        probe.interpret_capability(ep,out)
        self.assertEqual(out["capability_evidence"]["live_perpetual_count"],1)

    def test_config(self):
        eps=probe.load_config(str(ROOT/"endpoints.json"))
        ids={x["id"] for x in eps}
        self.assertIn("polymarket-geo",ids)
        self.assertIn("binance-usdm-rest",ids)
        self.assertIn("okx-swap-rest",ids)
        self.assertIn("futu-openapi",ids)
        self.assertIn("ibkr-hong-kong-order",ids)
        self.assertIn("ibkr-europe-data",ids)
        self.assertIn("futu-anchor-tencent-hongkong",ids)
        self.assertIn("futu-anchor-aliyun-malaysia",ids)
        self.assertEqual(len(ids),len(eps))
        self.assertEqual(sum(x.get("group")=="ibkr_official" for x in eps),36)

    def test_ibkr_official_region_summary(self):
        endpoints=[
            {"group":"ibkr_official","ibkr_role":"primary","ibkr_region":"Hong Kong","ibkr_service":"login_orders","host":"hdc1.ibllc.com","port":4001,"score":90,"tcp":{"median_ms":8,"p95_ms":10,"jitter_ms":1,"success_rate":1},"ping":{"median_ms":7,"success_rate":1},"tls":{"success_rate":1}},
            {"group":"ibkr_official","ibkr_role":"primary","ibkr_region":"Hong Kong","ibkr_service":"market_data","host":"hdc1.ibllc.com","port":4000,"score":88,"tcp":{"median_ms":8,"p95_ms":11,"jitter_ms":1,"success_rate":1},"ping":{"median_ms":7,"success_rate":1}},
            {"group":"ibkr_official","ibkr_role":"primary","ibkr_region":"Europe","ibkr_service":"login_orders","host":"zdc1.ibllc.com","port":4001,"score":50,"tcp":{"median_ms":180,"p95_ms":190,"jitter_ms":4,"success_rate":1},"tls":{"success_rate":1}},
            {"group":"ibkr_official","ibkr_role":"primary","ibkr_region":"Europe","ibkr_service":"market_data","host":"zdc1.ibllc.com","port":4000,"score":48,"tcp":{"median_ms":181,"p95_ms":192,"jitter_ms":4,"success_rate":1}},
        ]
        result=probe.summarize_ibkr_official(endpoints)
        self.assertEqual(result["best_region"],"Hong Kong")
        self.assertEqual(result["best_score"],89.0)

    def test_futu_anchor_account_selection(self):
        rows=[
            {"id":"va","group":"futu_anchor","anchor_provider":"Tencent Cloud","futu_region":"Virginia","futu_quote_for":["moomoo-us"],"futu_trade_for":["moomoo-us"],"score":90,"tcp":{"median_ms":10,"p95_ms":12,"success_rate":1},"http":{"ttfb":{"median_ms":20}}},
            {"id":"sg","group":"futu_anchor","anchor_provider":"Tencent Cloud","futu_region":"Singapore","futu_quote_for":["moomoo-us"],"futu_trade_for":[],"score":70,"tcp":{"median_ms":80,"p95_ms":90,"success_rate":1},"http":{"ttfb":{"median_ms":100}}},
        ]
        result=probe.summarize_futu_anchors(rows,"moomoo-us")
        self.assertEqual(result["best_quote_anchor"]["region"],"Virginia")
        self.assertEqual(result["best_trade_anchor"]["region"],"Virginia")
        self.assertEqual(result["selected_score"],90.0)

    def test_language_normalization(self):
        self.assertEqual(probe.normalize_ui_language("en_US.UTF-8"),"en")
        self.assertEqual(probe.normalize_ui_language("zh_CN.UTF-8"),"zh-CN")
        self.assertEqual(probe.normalize_ui_language("zh-Hant"),"zh-TW")
        self.assertIsNone(probe.normalize_ui_language("C.UTF-8"))

    def test_public_labels_are_language_independent(self):
        report={"probe_version":"test","created_at":"2026-01-02T03:04:05Z","provider":"","region":"","profile":"balanced","summary":{"overall_score":50,"group_scores":{}},"endpoints":[],"benchmark":{}}
        sample=probe.public_sample(report,"さくら","東京第2","計算向け")
        self.assertEqual(sample["location"]["provider"],"さくら")
        self.assertEqual(sample["location"]["datacenter"],"東京第2")
        self.assertEqual(sample["public_schema_version"],1)

    def test_explicit_output_directory(self):
        with tempfile.TemporaryDirectory() as td:
            path,fallback=probe.choose_output_dir(str(pathlib.Path(td)/"reports"))
            self.assertTrue(path.is_dir())
            self.assertFalse(fallback)

    def test_output_falls_back_to_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            blocked=pathlib.Path(td)/"not-a-directory"
            blocked.write_text("x")
            fallback_root=pathlib.Path(td)/"fallback"
            with mock.patch.object(probe.Path,"cwd",return_value=blocked), \
                 mock.patch.object(probe.Path,"home",return_value=blocked), \
                 mock.patch.object(probe.tempfile,"gettempdir",return_value=str(fallback_root)):
                path,fallback=probe.choose_output_dir(None)
            self.assertTrue(fallback)
            self.assertTrue(path.is_dir())


if __name__ == "__main__": unittest.main()
