"""Summarize native Sentaurus backward Euler trials from a line iterator."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
import re


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
NS = Decimal("1e-9")
BE_STEP = re.compile(
    rf"^Computing BE-step from ({NUMBER}) s to ({NUMBER}) s\b"
    rf"(?:\s+\(Stepsize:\s*({NUMBER}) s\))?"
)
BOUNDARY = re.compile(
    r"^(?:Computing (?:\S+-)?step from\b|Starting solve of next problem:|"
    r"Curve trace finished\.|Sentaurus Device simulation times:)"
)
CONVERGED = re.compile(
    r"^(?:Finished, because\s+)?(?:Error smaller than 1\b|RHS smaller than\b|"
    r"\|RHS\| (?:is )?less than\b)", re.I
)
ACCEPTED = re.compile(r"^(?:(?:time[- ]?)?step|t-step) accepted\b", re.I)
T_REJECTED = re.compile(r"^(?:t-step rejection\b|(?:(?:time[- ]?)?step|t-step) rejected\b)", re.I)
TOTAL = re.compile(rf"^Total time:\s*({NUMBER})\s+s$")
ITERATION_HEADER = re.compile(r"^Iteration\s+\|Rhs\|.*\btime$")
ITERATION_ROW = re.compile(
    rf"^(\d+)\s+{NUMBER}(?:\s+{NUMBER}\s+{NUMBER}\s+{NUMBER}\s+\d+\s+\d+)?\s+{NUMBER}$"
)
CNORM_ROW = re.compile(
    rf"^([\w.-]+):\s+({NUMBER})\s+(\d+)\s+"
    rf"\(\s*({NUMBER}(?:\s*,\s*{NUMBER}){{0,2}})\s*\)\s+({NUMBER})$"
)


@dataclass
class _Trial:
    line_number: int
    start_ns: Decimal
    end_ns: Decimal
    step_ns: Decimal | None
    status: str = "incomplete"
    rejection_reason: str = "unknown"
    wall_s: Decimal | None = None
    in_timings: bool = False
    in_iterations: bool = False
    cnorm_header: bool = False
    pending_hotspots: list = field(default_factory=list)
    cnorm_iteration: int | None = None
    hotspots: list = field(default_factory=list)

    def read(self, line, line_number):
        if T_REJECTED.match(line):
            if self.rejection_reason == "unknown":
                self.rejection_reason = "t_step"
            self.status = "rejected"
        elif line.startswith("Newton didn't converge"):
            self.status = "rejected"
            self.rejection_reason = "newton"
        elif self.status != "rejected":
            if line.startswith("#iterations larger than"):
                self.status = "newton_failed"
            elif ACCEPTED.match(line):
                self.status = "accepted"
            elif self.status == "incomplete" and CONVERGED.match(line):
                self.status = "converged"

        if line == "Accumulated times:":
            self.in_timings = True
        elif self.in_timings and (total := TOTAL.fullmatch(line)):
            self.wall_s = Decimal(total[1])
            self.in_timings = False
        elif self.in_timings and not line.startswith(("Assembly time:", "Solve time:")):
            self.in_timings = False

        if ITERATION_HEADER.match(line):
            self.in_iterations = True
        elif line.startswith("Finished, because"):
            self.in_iterations = False
        elif self.in_iterations:
            self.read_cnorm(line, line_number)

    def read_cnorm(self, line, line_number):
        if line.startswith("C-norm_equation"):
            self.cnorm_header = True
        elif row := ITERATION_ROW.fullmatch(line):
            if self.cnorm_header and self.pending_hotspots:
                self.cnorm_iteration = int(row[1])
                self.hotspots = sorted(self.pending_hotspots, key=lambda item: -item["max_error"])
            self.pending_hotspots = []
            self.cnorm_header = False
        elif hotspot := CNORM_ROW.fullmatch(line):
            # Mixed-mode output can emit a Poisson row just before the header.
            self.pending_hotspots.append(dict(
                equation=hotspot[1], max_error=float(hotspot[2]), node=int(hotspot[3]),
                coordinates_um=[float(value) for value in hotspot[4].split(",")],
                value=float(hotspot[5]), line_number=line_number,
            ))


def summarize_attempts(lines, *, start_ns=None, end_ns=None, open_window=False):
    """Select trials by their printed BE target, using the archive's window convention.

    Counts include untimed trials. Wall sums cover completed trials with a
    logged per-trial Total time, or are None when coverage is absent. Zero
    rejected_wall_s denotes zero recorded rejects or a measured zero sum.
    Repeated hotspots count trials, once per equation/node per rejection,
    using each trial's last available C-norm iteration.
    """
    start = Decimal(str(start_ns)) if start_ns is not None else Decimal("-Infinity")
    end = Decimal(str(end_ns)) if end_ns is not None else Decimal("Infinity")
    if start > end:
        raise ValueError("start_ns must be at or before end_ns")

    result = dict(accepted_steps=0, rejected_steps=0, incomplete_steps=0,
                  timed_steps=0, timed_rejected_steps=0, rejected_steps_with_cnorm=0,
                  last_accepted_ns=None)
    trial = worst = None
    attempt_wall = rejected_wall = Decimal(0)
    repeated = Counter()

    def record(current, *, closed=False, next_start=None):
        nonlocal worst, attempt_wall, rejected_wall
        status = current.status
        if status == "converged" and closed and (next_start is None or next_start >= current.end_ns):
            status = "accepted"
        elif status == "newton_failed" and closed:
            status = "rejected"
            current.rejection_reason = "newton"
        elif status in ("converged", "newton_failed"):
            status = "incomplete"
        result[f"{status}_steps"] += 1

        if status == "accepted":
            result["last_accepted_ns"] = float(current.end_ns)
        elif status == "rejected" and current.hotspots:
            result["rejected_steps_with_cnorm"] += 1
            repeated.update({(item["equation"], item["node"]) for item in current.hotspots})

        if status == "incomplete" or current.wall_s is None:
            return
        result["timed_steps"] += 1
        attempt_wall += current.wall_s
        if status == "rejected":
            result["timed_rejected_steps"] += 1
            rejected_wall += current.wall_s
            if worst is None or current.wall_s > worst.wall_s:
                worst = current

    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        header = BE_STEP.match(line)
        if header:
            left, right = Decimal(header[1]) / NS, Decimal(header[2]) / NS
            if trial is not None:
                record(trial, closed=True, next_start=left)
            trial = None
            in_window = start < right < end if open_window else start <= right <= end
            if in_window:
                step = Decimal(header[3]) / NS if header[3] is not None else None
                trial = _Trial(line_number, left, right, step)
        elif trial is not None:
            if BOUNDARY.match(line):
                record(trial, closed=True)
                trial = None
            else:
                trial.read(line, line_number)
    if trial is not None:
        record(trial)

    result["attempt_wall_s"] = float(attempt_wall) if result["timed_steps"] else None
    result["rejected_wall_s"] = None
    if result["timed_rejected_steps"] or not result["rejected_steps"]:
        result["rejected_wall_s"] = float(rejected_wall)
    result["worst_rejected_attempt"] = None
    if worst is not None:
        result["worst_rejected_attempt"] = dict(
            line_number=worst.line_number, start_ns=float(worst.start_ns), end_ns=float(worst.end_ns),
            step_ns=float(worst.step_ns) if worst.step_ns is not None else None,
            wall_s=float(worst.wall_s), rejection_reason=worst.rejection_reason,
            cnorm_status="available" if worst.hotspots else "unknown",
            cnorm_iteration=worst.cnorm_iteration, cnorm_hotspots=worst.hotspots,
        )
    result["repeated_hotspots"] = [
        dict(equation=equation, node=node, rejected_steps=count)
        for (equation, node), count in sorted(repeated.items(), key=lambda item: (-item[1], item[0]))
        if count > 1
    ]
    return result
