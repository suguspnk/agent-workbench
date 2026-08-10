from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "skills/orchestrate-task/scripts/route_subagent.py"
REPLAY_PATH = ROOT / "skills/orchestrate-task/tests/routing-cases.json"
SPEC = importlib.util.spec_from_file_location("agent_workbench_router", ROUTER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load route_subagent.py")
ROUTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTER)


class RouteSubagentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))

    def test_replay_expectations(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                actual = ROUTER.route(case["card"])
                for key, expected in case["expected"].items():
                    self.assertEqual(actual[key], expected)

    def test_every_role_is_reachable(self) -> None:
        reached = {ROUTER.route(case["card"])["primary_role"] for case in self.cases}
        self.assertEqual(reached, set(ROUTER.ROLE_PROFILE))

    def test_routing_is_deterministic(self) -> None:
        card = self.cases[0]["card"]
        self.assertEqual(ROUTER.route(card), ROUTER.route(dict(reversed(list(card.items())))))

    def test_missing_field_is_rejected(self) -> None:
        card = dict(self.cases[0]["card"])
        card.pop("impact")
        with self.assertRaisesRegex(ROUTER.RoutingError, "missing routing fields: impact"):
            ROUTER.route(card)

    def test_unknown_field_is_rejected(self) -> None:
        card = dict(self.cases[0]["card"], urgency="high")
        with self.assertRaisesRegex(ROUTER.RoutingError, "unknown routing fields: urgency"):
            ROUTER.route(card)

    def test_invalid_enum_is_rejected(self) -> None:
        card = dict(self.cases[0]["card"], impact="urgent")
        with self.assertRaisesRegex(ROUTER.RoutingError, "impact must be one of"):
            ROUTER.route(card)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ROUTER.RoutingError, "duplicate JSON key: impact"):
            ROUTER.parse_json('{"impact": "reversible", "impact": "user-visible"}')


if __name__ == "__main__":
    unittest.main()
