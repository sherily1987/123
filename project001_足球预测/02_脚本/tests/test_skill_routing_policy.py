import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "01_规划" / "治理" / "技能路由策略.json"


class SkillRoutingPolicyTests(unittest.TestCase):
    def test_policy_locks_production_routes_and_legacy_skills(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["production"]["quant"], "football-quant-fusion-prediction")
        self.assertEqual(policy["production"]["llm_ops"], "llm-football-prediction-ops")
        self.assertEqual(policy["production"]["evidence"], "football-evidence-collection")
        self.assertIn("football-llm-ensemble-prediction", policy["legacy_only"])
        self.assertEqual(policy["proxy_policy"]["domestic_llm"], "unset_all_proxy")


if __name__ == "__main__":
    unittest.main()
