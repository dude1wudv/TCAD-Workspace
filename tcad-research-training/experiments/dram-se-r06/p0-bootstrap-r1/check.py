"""Read-only source/log checks; never declares a scientific gate passed."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from logging_patch import VERSION, verify

HERE = Path(__file__).resolve().parent


def file_lines(path):
    with Path(path).open("rb") as stream:
        yield from stream


def log_check(path, require_unload_summary=False):
    counts = {name: 0 for name in (
        "init_detail", "init_limit", "callback_detail", "callback_limit",
        "callback_progress", "plugin_unload_summary", "warning_lines",
        "error_lines", "convergence_lines", "completion_lines")}
    callback_ids, init_ids, progress_ids = [], [], []
    summary = None
    digest = hashlib.sha256()
    lines = 0
    for raw in file_lines(path):
        digest.update(raw)
        lines += 1
        text = raw.decode("utf-8", errors="replace")
        if "R04_NODAL_INIT" in text:
            counts["init_detail"] += 1
            match = re.search(r"\bn=(\d+)", text)
            if VERSION in text and match and len(init_ids) < 5:
                init_ids.append(int(match[1]))
        if "R06_O2_INIT_LIMIT" in text:
            counts["init_limit"] += 1
        if "R04_QY_CALLBACK " in text:
            counts["callback_detail"] += 1
            match = re.search(r"\bn=(\d+)", text)
            if match and len(callback_ids) < 513:
                callback_ids.append(int(match[1]))
        if "R04_QY_TRACE_LIMIT" in text:
            counts["callback_limit"] += 1
        if "R06_O2_CALLBACK_PROGRESS" in text:
            counts["callback_progress"] += 1
            match = re.search(r"\bn=(\d+)", text)
            if (match and "callback_count_not_accepted_steps=true" in text
                    and len(progress_ids) < 55):
                progress_ids.append(int(match[1]))
        if "R06_O2_PLUGIN_UNLOAD_SUMMARY" in text:
            counts["plugin_unload_summary"] += 1
            match = re.search(r"initializations=(\d+) callbacks=(\d+) "
                              r"solver_success=unknown accepted_steps=unknown", text)
            if VERSION in text and match:
                summary = {"initializations": int(match[1]), "callbacks": int(match[2])}
        for category, pattern in (
            ("warning_lines", r"\bwarning\b"),
            ("error_lines", r"\berror\b|R04_QY_INPUT:|R04_QY_COMPUTE:"),
            ("convergence_lines", r"convergen|not converged"),
            ("completion_lines", r"job finished|finished.*sdevice|total.*cpu|wall.*time"),
        ):
            if re.search(pattern, text, re.IGNORECASE):
                counts[category] += 1
    problems = []

    def require(condition, message):
        if not condition:
            problems.append(message)

    require(0 < counts["init_detail"] <= 4 and len(init_ids) == counts["init_detail"],
            "missing new-version init marker or global init bound exceeded")
    require(len(init_ids) == len(set(init_ids)) and all(1 <= n <= 4 for n in init_ids),
            "initialization detail counters repeat or are outside the frozen range")
    require(0 < counts["callback_detail"] <= 512
            and len(callback_ids) == counts["callback_detail"],
            "missing callback details or global detail bound exceeded")
    require(len(callback_ids) == len(set(callback_ids))
            and all(1 <= n <= 512 for n in callback_ids),
            "callback detail counters repeat or are outside the frozen range")
    require(counts["init_limit"] <= 1 and counts["callback_limit"] <= 1,
            "global limit notices repeated")
    require(counts["callback_progress"] == len(progress_ids) <= 54,
            "missing semantic marker or global progress bound exceeded")
    require(len(progress_ids) == len(set(progress_ids))
            and all(n >= 1024 and n < 2**64 and n & (n - 1) == 0 for n in progress_ids),
            "progress counters repeat or are not frozen power-of-two milestones")
    require(counts["plugin_unload_summary"] <= 1, "more than one plugin-unload summary")
    if require_unload_summary:
        require(counts["plugin_unload_summary"] == 1 and summary is not None,
                "unload summary missing: check the original process stderr archive")
    if summary is not None:
        require(summary["initializations"] >= max(init_ids, default=0)
                and summary["callbacks"] >= max(callback_ids + progress_ids, default=0),
                "summary contradicts earlier callback/initialization counters")
        require(set(init_ids) == set(range(1, min(summary["initializations"], 4) + 1)),
                "initialization detail records are incomplete")
        require(set(callback_ids) == set(range(1, min(summary["callbacks"], 512) + 1)),
                "callback detail records are incomplete")
        require(counts["init_limit"] == int(summary["initializations"] >= 5)
                and counts["callback_limit"] == int(summary["callbacks"] >= 513),
                "limit notices do not match the unload counters")
        require(set(progress_ids) == {1 << k for k in range(10, 64)
                                     if (1 << k) <= summary["callbacks"]},
                "callback progress records are incomplete")
    return {
        "schema": "tcad-r06-o2-log-check-v1",
        "status": "passed_log_bounds_only" if not problems else "failed_log_bounds",
        "path": str(Path(path).resolve()), "sha256": digest.hexdigest(),
        "bytes": Path(path).stat().st_size, "lines": lines, "counts": counts,
        "plugin_unload_summary": summary, "problems": problems,
        "warning_error_counts_are_inventory_only": True,
        "native_completion_verified": False, "waveforms_verified": False,
        "source_integral_verified": False, "o2_scientific_gate_passed": False,
        "formal_plan_completed_credit": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("source", "log"))
    parser.add_argument("--log", type=Path)
    parser.add_argument("--require-unload-summary", action="store_true")
    args = parser.parse_args()
    if args.action == "source":
        result = verify(HERE)
    else:
        if args.log is None:
            parser.error("--log is required")
        result = log_check(args.log, args.require_unload_summary)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"].startswith("failed"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
