"""Progress checks for the Sentaurus transient log tail."""
from __future__ import annotations

from decimal import Decimal
import re


NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
BE_STEP = re.compile(
    rf"^Computing BE-step from ({NUMBER}) s to {NUMBER} s \(Stepsize: ({NUMBER}) s\)"
)
REJECTION = "Newton didn't converge, trying again with smaller timestep"
WALL_SECONDS = {"1": 28800, "2": 21600}


def parse_transient_progress(log_text: str) -> dict:
    sim_time_ns = stepsize_s = None
    rejections = 0
    for line in log_text.splitlines():
        line = line.strip()
        if line.startswith("Finished, because"):
            rejections = 0
        elif line.startswith(REJECTION):
            rejections += 1
        else:
            step = BE_STEP.match(line)
            if step:
                # The left endpoint has been reached; the right is still a trial.
                sim_time_ns = float(Decimal(step[1]).scaleb(9))
                stepsize_s = float(step[2])
    return {"sim_time_ns": sim_time_ns, "stepsize_s": stepsize_s,
            "consecutive_rejections": rejections}


def in_exempt_window(sim_time_ns: float | None, exempt_windows_ns: list[list[float]]) -> bool:
    return sim_time_ns is not None and any(
        start <= sim_time_ns <= end for start, end in exempt_windows_ns
    )


def evaluate_watchdog(policy_cfg: dict, intent: dict, progress: dict, now: float, width: int) -> dict:
    metrics = dict(progress)
    reason = None
    if policy_cfg.get("enabled") is True:
        start = intent.get("started_at", intent.get("submission_intent_at"))
        elapsed = now - start if start is not None else None
        max_wall = policy_cfg.get("max_wall_seconds_by_width", {}).get(str(width), WALL_SECONDS.get(str(width)))
        sim_time = progress["sim_time_ns"]
        stepsize = progress["stepsize_s"]
        windows = policy_cfg.get("exempt_windows_ns", [])
        exempt = in_exempt_window(sim_time, windows)
        metrics.update(elapsed_seconds=elapsed, in_exempt_window=exempt, rate_ns_per_hour=None)

        if max_wall is not None and elapsed is not None and elapsed > max_wall:
            reason = "wall_time_exceeded"
        elif (not exempt and progress["consecutive_rejections"] >= policy_cfg.get("max_consecutive_rejections", 40)
              and stepsize is not None and stepsize < policy_cfg.get("min_stepsize_s", 1e-13)):
            reason = "consecutive_rejections_stalled"
        elif sim_time is not None and (sim_time > 0 or exempt):
            anchor = intent.get("watchdog_anchor")
            if anchor is None or exempt != in_exempt_window(anchor["sim_time_ns"], windows):
                intent["watchdog_anchor"] = {"time": now, "sim_time_ns": sim_time}
            elif not exempt:
                duration = now - anchor["time"]
                advance = sim_time - anchor["sim_time_ns"]
                stall_window = policy_cfg.get("stall_window_seconds", 2700)
                min_rate = policy_cfg.get("min_progress_ns_per_hour", 0.05)
                if duration >= stall_window:
                    rate = advance / (duration / 3600.0)
                    metrics["rate_ns_per_hour"] = rate
                    if rate < min_rate:
                        reason = "low_progress_rate"
                if reason is None and advance >= min_rate * (stall_window / 3600.0):
                    intent["watchdog_anchor"] = {"time": now, "sim_time_ns": sim_time}
    return {"triggered": reason is not None, "reason": reason, "metrics": metrics}
