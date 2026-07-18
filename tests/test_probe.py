import importlib.util
import json
import pathlib
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
        out={"http":{"success_rate":1,"last":{"_json":{"blocked":False,"country":"SG","ip":"1.2.3.4"}}}}
        probe.interpret_capability(ep,out)
        self.assertEqual(out["capability_evidence"]["verdict"],"geo_check_passed")
        self.assertNotIn("_json",out["http"]["last"])

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


if __name__ == "__main__": unittest.main()
