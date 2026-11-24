import datetime as dt
import unittest

from status_checker import check_public_payload, project_response_supply


class ResponseSupplyTests(unittest.TestCase):
    def test_each_case_has_one_stage_and_enqueued_requires_original_evidence(self):
        now = dt.datetime.now(dt.timezone.utc)
        case = {key: f"r06-s-lhs02-development-{key}-b0"
                for key in ("p0", "transport", "missing", "ready", "queued", "run", "reuse")}
        case["threshold"] = "r06-t-lhs02-development-shape-a-x30-b0"

        def condition(radiation, cases, qualification=None, pool_status="not_submitted"):
            return dict(profile="LHS02-development", radiation=radiation, cases=cases,
                        qualification=qualification, pool_status=pool_status)

        qualified = {"path": "/home/private/qualification"}
        rows = [
            condition("C0", {case["p0"]: {"status": "pending"}}),
            condition("C1", {case["transport"]: {"status": "pending"}}, qualified),
            condition("G0", {
                case["missing"]: {"status": "blocked", "dependency": "/home/private/material"},
                case["ready"]: {"status": "approved_waiting_queue"},
                case["queued"]: {"status": "staged"},
                case["run"]: {"status": "queued_or_run"},
                case["reuse"]: {"status": "verified_zero_reuse"},
                case["threshold"]: {"status": "pending", "block": "T", "dependency": "threshold reference"},
            }, qualified, "succeeded"),
        ]
        report = dict(schema="tcad-r06-lhs-response-supply-v1", observation_utc=now.isoformat(),
                      cases=[*rows, rows[-1]])
        job = {"id": case["queued"] + "-supply-r1"}
        run = {"id": "opaque-original-task"}
        queue = dict(schema="tcad-work-items-v1", tasks=[job, run])
        observation = dict(utc=now.isoformat(), runs=[job, run, {"id": "opaque-retry"}])
        binding = {"scientific_admission": {"case_id": case["run"]}}
        runtime = {"intents": {"opaque-original-task": binding, "opaque-retry": binding}}

        result = project_response_supply(report, observation, queue, runtime, now)
        check_public_payload(result)
        self.assertEqual(result["condition_count"], 3)
        self.assertEqual(result["case_count"], 8)
        self.assertEqual(result["counts"], dict(missing_material=1, awaiting_prerequisites=3, ready=1,
                                               enqueued=2, zero_reuse=1))
        self.assertEqual(result["prerequisites"], dict(p0=1, transport=1, threshold=1))
        self.assertEqual(sum(result["counts"].values()), result["case_count"])

        queue["tasks"].remove(run)
        self.assertEqual(project_response_supply(report, observation, queue, runtime, now)["counts"]["enqueued"], 2)
        observation["runs"] = [job]
        self.assertEqual(project_response_supply(report, observation, queue, runtime, now), {"state": "unavailable"})

    def test_old_register_is_marked_stale(self):
        now = dt.datetime.now(dt.timezone.utc)
        stamp = (now - dt.timedelta(minutes=7)).isoformat()
        report = {"schema": "tcad-r06-lhs-response-supply-v1", "observation_utc": stamp}
        result = project_response_supply(report, {"utc": now.isoformat()}, {}, {}, now)
        self.assertEqual(result["state"], "stale")
        self.assertNotIn("counts", result)
