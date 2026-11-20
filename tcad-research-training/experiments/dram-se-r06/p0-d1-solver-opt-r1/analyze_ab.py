"""Extract D1 solver and readout metrics and compare two runs offline."""

import argparse
from contextlib import contextmanager
import csv
from decimal import Decimal, InvalidOperation
from io import StringIO, TextIOWrapper
import json
import math
from pathlib import Path
import re
import tarfile

from reject_trace import summarize_attempts


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
NS = Decimal("1e-9")
REF_V = Decimal("0.6")
MARGIN_LIMIT_V = Decimal("1e-4")
ATTEMPT = re.compile(r"^\s*Computing BE-step from (" + NUMBER + r") s to (" + NUMBER + r") s", re.M)
ILS = re.compile(r"^\s*Linear solver(?: \(submethod\))?\s*:\s*ILS\b", re.I | re.M)
ITERATION = re.compile(r"\s*\d+(?:\s+" + NUMBER + r"){4}\s+\d+\s+(\d+)\s+" + NUMBER + r"\s*")
LOG_METRICS = ("accepted_steps", "rejected_steps", "total_assembly_s", "total_solve_s",
               "total_wall_s", "last_sim_time_ns", "max_ils_iters")


def parse_log(text):
    """Count completed BE attempts and sum the logged assembly and solve times."""
    trace = summarize_attempts(StringIO(text))
    in_table = False
    max_ils_iters = None
    has_ils = bool(ILS.search(text))
    if has_ils:
        for line in StringIO(text):
            if line.lstrip().startswith("Iteration") and "#iterative" in line:
                in_table = True
            elif in_table and (row := ITERATION.fullmatch(line)):
                max_ils_iters = max(max_ils_iters or 0, int(row[1]))
            elif line.lstrip().startswith("Finished, because") or ATTEMPT.match(line):
                in_table = False

    def timings(label):
        return [float(value) for value in re.findall(
            r"^\s*" + label + r":[ \t]*(" + NUMBER + r")[ \t]+s\b", text, re.I | re.M)]

    assembly, solve, wall = (timings(label) for label in ("Assembly time", "Solve time", "wallclock"))
    return dict(accepted_steps=trace["accepted_steps"], rejected_steps=trace["rejected_steps"],
                total_assembly_s=math.fsum(assembly) if assembly else None,
                total_solve_s=math.fsum(solve) if solve else None,
                total_wall_s=wall[-1] if wall else None, last_sim_time_ns=trace["last_accepted_ns"],
                max_ils_iters=max_ils_iters)


def circuit_rows(text):
    if text.startswith("DF-ISE text"):
        datasets = re.search(r"\bdatasets\s*=\s*\[(.*?)\]", text, re.S)
        data = re.search(r"\bData\s*\{(.*?)\}", text, re.S)
        if not datasets or not data:
            raise ValueError("Missing DF-ISE datasets or Data block")
        names = re.findall(r'"([^"]+)"', datasets[1])
        values = data[1].split()
        width = len(names)
        if not width or len(values) % width:
            raise ValueError("Malformed DF-ISE rows")
        return names, (values[i:i + width] for i in range(0, len(values), width))
    reader = csv.reader(StringIO(text))
    return next(reader, []), reader


def number(value):
    try:
        result = Decimal(str(value).replace("D", "E").replace("d", "e"))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Nonfinite numeric value {value!r}")
    return result


def parse_circuit(text, *, sample_ns=31.9, tolerance_ns=0.001):
    """Use the first closest native sample, with a default 1 ps tolerance."""
    names, rows = circuit_rows(text.lstrip("\ufeff \t\r\n"))
    names = [name.strip().lower() for name in names]
    times = [i for i, name in enumerate(names) if name in ("time", "time_s", "time_ns")]
    volts = [i for i, name in enumerate(names) if name in ("v(bl)", "v_bl_v")]
    if len(times) != 1 or len(volts) != 1:
        raise ValueError("Expected one time/time_s/time_ns column and one V(BL) column")
    time, volt = times[0], volts[0]
    scale = Decimal(1) if names[time] == "time_ns" else NS
    target, tolerance = number(sample_ns), number(tolerance_ns)
    if tolerance < 0:
        raise ValueError("Sample tolerance must be nonnegative")

    closest = None
    for row in rows:
        if not row:
            continue
        if len(row) != len(names):
            raise ValueError("Malformed circuit row")
        time_ns, v_bl = number(row[time]) / scale, number(row[volt])
        distance = abs(time_ns - target)
        if closest is None or distance < closest[0]:
            closest = distance, time_ns, v_bl
    if closest is None or closest[0] > tolerance:
        raise ValueError(f"No circuit sample within {tolerance} ns of {target} ns")
    _, time_ns, v_bl = closest
    return dict(sample_time_ns=float(time_ns), v_bl_V=float(v_bl),
                write1_margin_V=float(v_bl - REF_V), write0_margin_V=float(REF_V - v_bl))


def compare_metrics(baseline, candidate, *, stored_bit=1):
    """Report candidate-minus-baseline changes and test the signed margin."""
    if stored_bit not in (0, 1):
        raise ValueError("Stored bit must be 0 or 1")
    margin = f"write{stored_bit}_margin_V"
    delta_margin = number(candidate[margin]) - number(baseline[margin])
    delta = {key: candidate[key] - baseline[key] for key in LOG_METRICS
             if baseline.get(key) is not None and candidate.get(key) is not None}
    result = dict(stored_bit=stored_bit, delta_metrics=delta, delta_margin_V=float(delta_margin),
                  margin_limit_V=float(MARGIN_LIMIT_V), margin_pass=abs(delta_margin) < MARGIN_LIMIT_V)
    if "rejection_window" in baseline or "rejection_window" in candidate:
        left, right = baseline.get("rejection_window"), candidate.get("rejection_window")
        if (not left or not right or left["bounds_ns"] != right["bounds_ns"] or
                left["window_kind"] != right["window_kind"]):
            raise ValueError("A/B rejection windows must have the same bounds")
        if baseline.get("sample_time_ns") is None or baseline["sample_time_ns"] != candidate.get("sample_time_ns"):
            raise ValueError("A/B margins must use the same native readout time")
        start, end = left["bounds_ns"]
        for metrics, window in ((baseline, left), (candidate, right)):
            first, last = metrics.get("first_attempt_ns"), metrics.get("last_sim_time_ns")
            if first is None or first > start or last is None or last < end:
                raise ValueError("Both native logs must span the requested rejection window")
            if not window["accepted_steps"] or window["incomplete_steps"]:
                raise ValueError("Window has no accepted steps or contains an unfinished attempt")
        result["delta_window_rejected_steps"] = right["rejected_steps"] - left["rejected_steps"]
        timed = all(window["timed_steps"] == window["accepted_steps"] + window["rejected_steps"]
                    for window in (left, right))
        for key in ("attempt_wall_s", "rejected_wall_s"):
            result[f"delta_window_{key}"] = (right[key] - left[key] if timed and
                                             left[key] is not None and right[key] is not None else None)
        result["readout_sign_preserved"] = number(candidate[margin]).compare(0) == number(baseline[margin]).compare(0)
    return result


def diagnose(lines, bounds, open_window=False):
    if bounds is None:
        if open_window:
            raise ValueError("--open-window requires --window-ns")
        return summarize_attempts(lines)
    start, end = (number(value) for value in bounds)
    if not 0 <= start < end:
        raise ValueError("Expected 0 <= start < end in ns")
    summary = summarize_attempts(lines, start_ns=start, end_ns=end, open_window=open_window)
    return {**summary, "bounds_ns": [float(start), float(end)], "window_kind": "open" if open_window else "closed"}


@contextmanager
def native_text(path, member):
    if path.suffix.lower() == ".tar":
        with tarfile.open(path, "r:") as archive:
            matches = [entry for entry in archive if entry.isfile() and Path(entry.name).name == member]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one {member} in {path}; found {len(matches)}")
            with TextIOWrapper(archive.extractfile(matches[0]), encoding="utf-8") as stream:
                yield stream
    else:
        with path.open(encoding="utf-8") as stream:
            yield stream


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    trace = modes.add_parser("diagnose", help="Locate rejected native BE steps without a waveform")
    trace.add_argument("log", type=Path)
    extract = modes.add_parser("extract", help="Print metrics JSON from native results")
    extract.add_argument("log", type=Path)
    extract.add_argument("circuit", type=Path, nargs="?", help="DF-ISE or CSV readout waveform")
    extract.add_argument("--sample-ns", type=float, default=31.9)
    extract.add_argument("--tolerance-ns", type=float, default=0.001)
    for mode in (trace, extract):
        mode.add_argument("--window-ns", nargs=2, metavar=("START", "END"), type=Decimal)
        mode.add_argument("--open-window", action="store_true", help="Exclude both printed target boundaries")
    compare = modes.add_parser("compare", help="Compare baseline and candidate metrics JSON")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--stored-bit", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    if args.mode == "diagnose":
        with native_text(args.log, "transient_des.log") as stream:
            result = diagnose(stream, args.window_ns, args.open_window)
    elif args.mode == "extract":
        with native_text(args.log, "transient_des.log") as stream:
            text = stream.read()
        result = parse_log(text)
        if args.window_ns is not None or args.open_window:
            first = ATTEMPT.search(text)
            result["first_attempt_ns"] = float(Decimal(first[1]) / NS) if first else None
            result["rejection_window"] = diagnose(StringIO(text), args.window_ns, args.open_window)
        if args.circuit is not None:
            with native_text(args.circuit, "circuit.plt") as stream:
                result.update(parse_circuit(stream.read(), sample_ns=args.sample_ns, tolerance_ns=args.tolerance_ns))
    else:
        result = compare_metrics(json.loads(args.baseline.read_bytes()), json.loads(args.candidate.read_bytes()),
                                 stored_bit=args.stored_bit)
    print(json.dumps(result, indent=2, allow_nan=False))
    return int(args.mode == "compare" and not (result["margin_pass"] and result.get("readout_sign_preserved", True)))


if __name__ == "__main__":
    raise SystemExit(main())
