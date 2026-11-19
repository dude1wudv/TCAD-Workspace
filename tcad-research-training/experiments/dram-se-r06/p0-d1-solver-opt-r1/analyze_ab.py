"""Extract D1 solver and readout metrics and compare two runs offline."""

import argparse
import csv
from decimal import Decimal, InvalidOperation
from io import StringIO
from itertools import chain
import json
import math
from pathlib import Path
import re


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
NS = Decimal("1e-9")
REF_V = Decimal("0.6")
MARGIN_LIMIT_V = Decimal("1e-4")
ATTEMPT = re.compile(r"^\s*Computing BE-step from " + NUMBER + r" s to (" + NUMBER + r") s")
CONVERGED = re.compile(
    r"^\s*(?:Error smaller than 1\b|RHS smaller than\b|"
    r"(?:Finished, because )?\|RHS\| (?:is )?less than\b|(?:time )?step accepted\b)", re.I)
REJECTED = re.compile(
    r"^\s*(?:Newton didn.t converge\b|(?:time )?step rejected\b|#iterations larger than\b)", re.I)
ILS = re.compile(r"^\s*Linear solver(?: \(submethod\))?\s*:\s*ILS\b", re.I | re.M)
ITERATION = re.compile(r"\s*\d+(?:\s+" + NUMBER + r"){4}\s+\d+\s+(\d+)\s+" + NUMBER + r"\s*")
LOG_METRICS = ("accepted_steps", "rejected_steps", "total_assembly_s", "total_solve_s",
               "total_wall_s", "last_sim_time_ns", "max_ils_iters")


def parse_log(text):
    """Count completed BE attempts and sum the logged assembly and solve times."""
    accepted = rejected = 0
    last_ns = None
    endpoint = status = None
    in_table = False
    max_ils_iters = None
    has_ils = bool(ILS.search(text))
    for line in chain(text.splitlines(), ("Starting solve of next problem:",)):
        attempt = ATTEMPT.match(line)
        if attempt or line.strip() == "Starting solve of next problem:":
            if status == "accepted":
                accepted += 1
                last_ns = float(endpoint / NS)
            elif status == "rejected":
                rejected += 1
            endpoint = Decimal(attempt[1]) if attempt else None
            status = None

        if endpoint is not None:
            if REJECTED.match(line):
                status = "rejected"
            elif status is None and CONVERGED.match(line):
                status = "accepted"

        if has_ils:
            if line.lstrip().startswith("Iteration") and "#iterative" in line:
                in_table = True
            elif in_table and (row := ITERATION.fullmatch(line)):
                max_ils_iters = max(max_ils_iters or 0, int(row[1]))
            elif line.lstrip().startswith("Finished, because") or attempt:
                in_table = False

    def timings(label):
        return [float(value) for value in re.findall(
            r"^\s*" + label + r":[ \t]*(" + NUMBER + r")[ \t]+s\b", text, re.I | re.M)]

    assembly, solve, wall = (timings(label) for label in ("Assembly time", "Solve time", "wallclock"))
    return dict(accepted_steps=accepted, rejected_steps=rejected,
                total_assembly_s=math.fsum(assembly) if assembly else None,
                total_solve_s=math.fsum(solve) if solve else None,
                total_wall_s=wall[-1] if wall else None, last_sim_time_ns=last_ns,
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
    return dict(stored_bit=stored_bit, delta_metrics=delta, delta_margin_V=float(delta_margin),
                margin_limit_V=float(MARGIN_LIMIT_V), margin_pass=abs(delta_margin) < MARGIN_LIMIT_V)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    extract = modes.add_parser("extract", help="Print metrics JSON from native results")
    extract.add_argument("log", type=Path)
    extract.add_argument("circuit", type=Path, nargs="?", help="DF-ISE or CSV readout waveform")
    extract.add_argument("--sample-ns", type=float, default=31.9)
    extract.add_argument("--tolerance-ns", type=float, default=0.001)
    compare = modes.add_parser("compare", help="Compare baseline and candidate metrics JSON")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--stored-bit", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    if args.mode == "extract":
        result = parse_log(args.log.read_text(encoding="utf-8"))
        if args.circuit is not None:
            result.update(parse_circuit(args.circuit.read_text(encoding="utf-8"),
                                        sample_ns=args.sample_ns, tolerance_ns=args.tolerance_ns))
    else:
        result = compare_metrics(json.loads(args.baseline.read_bytes()), json.loads(args.candidate.read_bytes()),
                                 stored_bit=args.stored_bit)
    print(json.dumps(result, indent=2, allow_nan=False))
    return int(args.mode == "compare" and not result["margin_pass"])


if __name__ == "__main__":
    raise SystemExit(main())
