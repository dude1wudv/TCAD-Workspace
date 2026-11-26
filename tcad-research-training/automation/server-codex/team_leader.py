"""Wake the server's maintenance lead on actionable changes in the original scheduler."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


RETRY_SECONDS = 15 * 60
RESOURCE_REASONS = (
    "admission_disk", "admission_server_disk", "admission_remote_disk", "admission_backing_disk",
    "admission_memory", "admission_host_memory", "admission_license",
)
MAINTENANCE_STAGES = (
    "find_or_extract_readout", "inspect_backup_receipt", "verify_extraction_handoff",
    "inspect_retained_result", "diagnose_or_reconcile", "unsupported_format",
)


def number(mapping, key):
    value = mapping.get(key)
    return value if type(value) is int and value >= 0 else 0


def observation_summary(observation, maintenance, policy, now, lhs_responses=()):
    scheduler = observation.get("scheduler", {})
    supply = scheduler.get("replenishment", {})
    pool = scheduler.get("pool", {})
    slots = pool.get("slots", {})
    breakdown = scheduler.get("last_decision", {}).get("blocked_breakdown", {})
    counts = maintenance.get("counts", {})
    running = number(observation, "running_count")
    blocked_ids = {row.get("id") for row in observation.get("blocked_tasks", []) if isinstance(row, dict)}
    blocked_ids.update(
        row.get("id") for row in observation.get("pending_tasks", [])
        if isinstance(row, dict) and row.get("reason") in ("scientific_gate_pending", "task_requires_revision")
    )
    runnable_ready = sum(1 for task_id in pool.get("ready_since", {}) if task_id not in blocked_ids)
    candidate_supply = sum(
        number(row, "count") for row in scheduler.get("candidate_supply_by_width", [])
        if isinstance(row, dict)
    )
    ready = max(number(supply, "ready"), runnable_ready, candidate_supply)
    free = number(slots, "free")
    limit = number(observation, "max_parallel_jobs")
    if limit:
        free = min(free, max(0, limit - number(observation, "active_count")))
    stale_after = number(scheduler, "fresh_max_age_seconds") or 60
    sampled_at = datetime.fromisoformat(observation["utc"]).timestamp() if observation else 0
    fresh = 0 <= now - sampled_at <= stale_after
    collected = {row["id"] for row in observation.get("runs", [])
                 if row.get("collected") is True and row.get("success") is True}
    released = sum(row.get('id', '').startswith('r06-') and row.get('collected') is True
                   and row.get('occupied') is False for row in observation.get('runs', []))
    lhs_zero_pairs = [f"LHS{index:02}" for index in range(1, 7)
                      if all(f"r06-p0-lhs{index:02}-hold22-readout-b{bit}-r1" in collected for bit in (0, 1))]
    d2_feedback = sorted(key for key in collected if key.startswith('r06-t-d2-narrow-fin-') and '-x10-' in key)
    lhs_halfsteps = [f'LHS{index:02}' for index in range(1, 7)
                     if all(f'r06-p0-lhs{index:02}-hold22-zero-h2-b{bit}-r1' in collected for bit in (0, 1))]
    registered_quartersteps = {run['task'] for row in lhs_responses for run in row['qualification_runs']
                               if run.get('step_ratio') == '0.25'}
    lhs_quartersteps = sorted(key for key in collected if key in registered_quartersteps
                              or (key.startswith('r06-p0-lhs') and '-hold22-zero-h4-' in key))
    lhs_eighthsteps = sorted(key for key in collected
                             if key.startswith('r06-p0-lhs') and '-hold22-zero-h8-' in key)
    d2_x30_feedback = sorted(key for key in collected if key.startswith('r06-t-d2-narrow-fin-') and '-x30-' in key)
    lhs_transport_count = sum(key.startswith(tuple(f'r06-lhs{index:02}-' for index in range(1, 7)))
                              and '-proton-' in key for key in collected)
    preparing = supply.get('preparing') is True or number(supply, 'preparing_up_to') > 0
    return {
        "observation_fresh": fresh,
        "service_enabled": policy["enabled"] is True,
        "running": running,
        "free": free,
        "ready": ready,
        "preparing": preparing,
        "supply_blocked": number(supply, "blocked_count"),
        "starved": fresh and free > 0 and ready == 0 and not preparing,
        "quarantined": number(slots, "quarantined"),
        "resources_blocked": [key for key in RESOURCE_REASONS if number(breakdown, key)],
        "remote_uncertain": observation.get("discovery_uncertain") is True,
        "queue_complete": observation.get("queue_complete") is True,
        "r06_released_runs": released,
        "lhs04_zero_pair_collected": 'LHS04' in lhs_zero_pairs,
        "lhs_zero_pairs_collected": lhs_zero_pairs,
        "d2_threshold_feedback_collected": d2_feedback,
        "lhs_halfstep_pairs_collected": lhs_halfsteps,
        "lhs_quartersteps_collected": lhs_quartersteps,
        "lhs_eighthsteps_collected": lhs_eighthsteps,
        "d2_x30_feedback_collected": d2_x30_feedback,
        "lhs_transport_collected": lhs_transport_count,
        "repair_planner_offline": scheduler.get("planner", {}).get("offline") is True,
        "repair_requests": sum(
            isinstance(row.get("id"), str) and row["id"].startswith("r06-")
            for row in observation.get("repair_requests", [])
        ),
        "maintenance": {key: number(counts, key) for key in MAINTENANCE_STAGES},
    }


def trigger(summary):
    event = {
        key: summary[key] for key in (
            "observation_fresh", "service_enabled", "starved", "quarantined", "resources_blocked",
            "remote_uncertain", "queue_complete", "lhs04_zero_pair_collected", "lhs_zero_pairs_collected",
            "d2_threshold_feedback_collected", "lhs_transport_collected",
            "repair_planner_offline", "repair_requests",
        )
    }
    for key in ('lhs_halfstep_pairs_collected', 'lhs_quartersteps_collected',
                'lhs_eighthsteps_collected', 'd2_x30_feedback_collected', 'r06_released_runs',
                'r06_reviewed_responses'):
        if summary.get(key):
            event[key] = summary[key]
    return event


def has_actionable_event(event):
    return any((
        not event.get("observation_fresh", True),
        not event.get("service_enabled", True),
        bool(event.get("starved")),
        bool(event.get("quarantined")),
        bool(event.get("resources_blocked")),
        bool(event.get("remote_uncertain")),
        bool(event.get("repair_planner_offline")),
        bool(event.get("repair_requests")),
        bool(event.get("lhs04_zero_pair_collected")),
        bool(event.get("lhs_zero_pairs_collected")),
        bool(event.get("d2_threshold_feedback_collected")),
        bool(event.get('lhs_halfstep_pairs_collected')),
        bool(event.get('lhs_quartersteps_collected')),
        bool(event.get('lhs_eighthsteps_collected')),
        bool(event.get('d2_x30_feedback_collected')),
        bool(event.get("lhs_transport_collected")),
        bool(event.get("queue_complete")),
        bool(event.get("r06_released_runs")),
        bool(event.get("r06_reviewed_responses")),
    ))


def load_optional(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def run(args):
    release = Path(args.release).resolve()
    sys.path.insert(0, str(release))
    import controller

    policy = controller.policy_at(args.policy)
    state = Path(args.state)
    runtime = Path(policy["state_dir"])
    now = time.time()
    response_register = Path(policy["workspace"]) / (
        "local_runtime/server-codex/r06-lhs-response-supply-r1/response-status.json"
    )
    summary = observation_summary(
        load_optional(runtime / "observation.json"),
        load_optional(Path(args.maintenance_summary)), policy, now,
        load_optional(response_register).get("cases", ()),
    )
    decisions = Path(policy['workspace']) / 'plans/dram-se-ddr5-lpddr5/r06-gate/results/case-acceptance'
    summary['r06_reviewed_responses'] = sum(1 for _ in decisions.glob('r06-*.json'))
    if args.inspect:
        print(json.dumps(summary, ensure_ascii=False))
        return
    checkpoint_path = state / "leader.json"
    checkpoint = load_optional(checkpoint_path)
    prompt_path = Path(__file__).with_name("team-leader.md")
    event = trigger(summary)
    if not args.force:
        if not has_actionable_event(event):
            if (checkpoint.get("event") != event
                    or any(key in checkpoint for key in ("error", "retry_at", "next_review"))):
                updated = {key: value for key, value in checkpoint.items()
                           if key not in ("error", "retry_at", "next_review")}
                updated["event"] = event
                controller.write_json(checkpoint_path, updated)
            return
        if now < checkpoint.get("retry_at", 0):
            return
        if event == checkpoint.get("event") and "error" not in checkpoint:
            return
    env = controller.prepare_codex(
        {**policy, "state_dir": str(state), "planner_mode": controller.REPAIR_MODE},
        controller.route_at(policy), cycle=state,
    )
    report_path = state / "leader-report.json"
    report_path.unlink(missing_ok=True)
    prompt = prompt_path.read_text(encoding="utf-8")
    context = {"summary": summary, "workspace": policy["workspace"], "policy": str(args.policy),
               "controller": str(release / "controller.py"), "runner_python": policy["runner_python"]}
    if args.observe:
        prompt += "\n本轮为上线验收。只执行 `id -u` 和只读服务检查，以报告记录实测 UID 与服务状态。\n"
    command = [
        policy["codex_binary"], "exec", "--cd", str(state), "--skip-git-repo-check",
        "--sandbox", "danger-full-access", "-c", 'approval_policy="never"',
        "-c", 'shell_environment_policy.set.PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"',
        "--json", "--color", "never", "--output-schema", str(release / "report.schema.json"),
        "--output-last-message", str(report_path), "-",
    ]
    result = {"event": event, "utc": datetime.now(timezone.utc).isoformat()}
    try:
        with (state / "leader-events.jsonl").open("wb") as events:
            subprocess.run(
                command, input=prompt + "\n" + json.dumps(context, ensure_ascii=False),
                text=True, encoding="utf-8", stdout=events, cwd=state, env=env,
                timeout=None, check=True,
            )
        report = controller.validate_report(load_optional(report_path))
        result.update(report=report)
    except (OSError, ValueError, subprocess.SubprocessError, controller.Refused) as error:
        result.update(error=type(error).__name__, retry_at=time.time() + RETRY_SECONDS)
        controller.write_json(checkpoint_path, result)
        raise
    controller.write_json(checkpoint_path, result)
    print("Maintenance lead reviewed the scheduler summary")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("policy", "release", "state", "maintenance-summary"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--observe", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
