"""Freeze and plot original r15 resource observations; never queries a live run.

freeze takes one directory listing and preserves every selected original byte.
plot only reads the explicit frozen manifest, never discovers later observations.
Plots describe sampled usage, not a completed DC result or native qualification.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sys


SCHEMA = "dram-see-v4-r15-live-observation-r1"
MANIFEST_SCHEMA = "dram-see-v4-native-usage-frozen-inputs-r1"
PATTERN = "*-d3-r15-native.json"
KIB_PER_GIB = 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value):
    if not isinstance(value, str):
        raise ValueError("UTC timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must explicitly identify UTC")
    return parsed.astimezone(timezone.utc)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": digest(raw)}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def stat_identity(path):
    result = path.stat()
    return {"bytes": result.st_size, "mtime_ns": result.st_mtime_ns}


def freeze(args):
    source = args.source_dir.resolve()
    output = args.output.resolve()
    if not source.is_dir() or output.exists():
        raise ValueError("Use an existing observation directory and a new output directory")
    parse_utc(args.native_start_utc)
    listed_at = utc_now()
    # This is the only glob in the entire program; do not refresh this list.
    selected = sorted(p for p in source.glob(PATTERN) if p.is_file())
    if not selected:
        raise ValueError("No original r15 observations found")
    output.mkdir(parents=True)
    snapshots = output / "source-snapshots"
    snapshots.mkdir()
    rows = []
    for index, original in enumerate(selected):
        row = {"input_index": index, "original_path": str(original),
               "original_name": original.name, "capture_errors": []}
        try:
            row["stat_before"] = stat_identity(original)
            raw = original.read_bytes()
            row["stat_after"] = stat_identity(original)
            target = snapshots / original.name
            with target.open("xb") as stream:
                stream.write(raw)
            row.update(snapshot=target.relative_to(output).as_posix(),
                       bytes=len(raw), sha256=digest(raw))
            row["original_sha256_after_capture"] = file_identity(original)["sha256"]
            row["stable_during_capture"] = (
                row["stat_before"] == row["stat_after"]
                and row["original_sha256_after_capture"] == row["sha256"])
            if not row["stable_during_capture"]:
                row["capture_errors"].append("source_changed_during_capture")
        except (OSError, ValueError) as exc:
            row["capture_errors"].append(type(exc).__name__ + ": " + str(exc))
        rows.append(row)
    implementation = Path(__file__).resolve()
    raw_script = implementation.read_bytes()
    with (output / "plot_native_usage.frozen.py").open("xb") as stream:
        stream.write(raw_script)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "directory_listing_observed_utc": listed_at,
        "capture_finished_utc": utc_now(),
        "source_directory": str(source), "pattern": PATTERN,
        "selection": "One sorted listing, retained without filtering; later files excluded",
        "expected_identity": {"run_id": args.run_id, "boot_id": args.boot_id,
                              "native_pid": args.pid, "native_start_ticks": args.start_ticks},
        "native_start_utc_supplied": args.native_start_utc,
        "native_start_anchor_provenance": "Explicit command argument supplied by the original-run owner; not inferred from CPU time",
        "implementation": {"original_path": str(implementation),
                           "snapshot": "plot_native_usage.frozen.py",
                           "bytes": len(raw_script), "sha256": digest(raw_script)},
        "input_count": len(rows), "inputs": rows,
        "source_read_only": True, "native_or_ssh_calls": 0,
    }
    write_json(output / "input-manifest.json", manifest)
    result = {"status": "FROZEN", "input_count": len(rows),
              "capture_issue_count": sum(bool(r["capture_errors"]) for r in rows),
              "manifest": str(output / "input-manifest.json"),
              "manifest_sha256": file_identity(output / "input-manifest.json")["sha256"],
              "first_selected": rows[0]["original_name"],
              "last_selected": rows[-1]["original_name"]}
    write_json(output / "freeze-receipt.json", dict(result, exit_code=0))
    return result


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite nonnegative numeric observation")
    return value


def kib(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\s+kB", value):
        raise ValueError("Expected original /proc '<integer> kB' value")
    return int(value.split()[0])


def extract_one(entry, raw, expected):
    row = {"input_index": entry["input_index"], "source_name": entry["original_name"],
           "source_sha256": entry.get("sha256"), "utc": None,
           "issues": [{"kind": "capture", "detail": e} for e in entry["capture_errors"]],
           "identity_checked": False, "identity_passed": False,
           "native_rss_KiB": None, "native_swap_KiB": None,
           "system_swap_free_KiB": None, "native_cpu_seconds": None,
           "previous_observation_interval_s": None}

    def issue(kind, detail):
        row["issues"].append({"kind": kind, "detail": detail})

    try:
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Observation root must be an object")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        issue("parse", type(exc).__name__ + ": " + str(exc))
        return row
    try:
        row["utc"] = parse_utc(value.get("utc")).isoformat()
    except (ValueError, TypeError) as exc:
        issue("timestamp", str(exc))
    status = value.get("status")
    usage = value.get("usage")
    if not isinstance(status, dict):
        status = {}
        issue("missing", "status object")
    if not isinstance(usage, dict):
        usage = {}
        issue("missing", "usage object")
    row["run_status"] = status.get("status")
    row["wrapper_remote_exit_code"] = status.get("remote_exit_code")
    row["status_observed_utc"] = status.get("observed_utc")
    row["log_bytes"] = status.get("log_bytes")
    row["usage_error"] = value.get("usage_error")
    if row["usage_error"] is not None:
        issue("usage_error", row["usage_error"])
    try:
        if row["utc"] is not None:
            lag = (parse_utc(row["utc"]) - parse_utc(row["status_observed_utc"])).total_seconds()
            row["status_to_record_completion_s"] = lag
            if lag < 0:
                issue("timestamp", "status timestamp follows record completion")
    except (ValueError, TypeError) as exc:
        issue("timestamp", "status timestamp: " + str(exc))

    wrapper = usage.get("wrapper_identity") or {}
    status_identity = status.get("identity") or {}
    processes = usage.get("processes")
    matches = ([p for p in processes if isinstance(p, dict) and p.get("pid") == expected["native_pid"]]
               if isinstance(processes, list) else [])
    native = matches[0] if len(matches) == 1 else {}
    proof = (usage.get("proofs") or {}).get("step-006-sdevice-process-observation.json") or {}
    checks = {
        "schema": value.get("schema") == SCHEMA,
        "status_run_id": status.get("run_id") == expected["run_id"],
        "wrapper_run_id": wrapper.get("run_id") == expected["run_id"],
        "status_identity_run_id": status_identity.get("run_id") == expected["run_id"],
        "boot_id": usage.get("boot_id") == expected["boot_id"],
        "wrapper_boot_id": wrapper.get("boot_id") == expected["boot_id"],
        "status_identity_boot_id": status_identity.get("boot_id") == expected["boot_id"],
        "wrapper_identity_agrees": all(wrapper.get(k) == status_identity.get(k) and wrapper.get(k) is not None
                                      for k in ("pid", "start_ticks")),
        "one_native_pid": len(matches) == 1,
        "native_start_ticks": native.get("start_ticks") == expected["native_start_ticks"],
        "native_name": native.get("name") == "sdevice",
        "native_executable": str(native.get("executable", "")).endswith("/bin/sdevice"),
        "original_admission": proof.get("schema") == "native-process-observation-r1"
            and proof.get("origin") == "native_pipeline" and proof.get("synthetic") is False
            and proof.get("status") == "OBSERVED",
        "original_admission_pid": proof.get("native_pid") == expected["native_pid"],
        "original_admission_start_ticks": proof.get("native_start_ticks") == expected["native_start_ticks"],
    }
    row["identity_checked"] = True
    row["identity_checks"] = checks
    row["identity_passed"] = all(checks.values())
    for name, valid in checks.items():
        if not valid:
            issue("identity", name)
    native_status = native.get("status") or {}
    memory = usage.get("memory") or {}
    raw_values = {"VmRSS": native_status.get("VmRSS"), "VmSwap": native_status.get("VmSwap"),
                  "SwapFree": memory.get("SwapFree"), "cpu_seconds": native.get("cpu_seconds")}
    row["raw_values"] = raw_values
    # Untrusted identity data remain in the row/raw snapshot, never enter a numeric series.
    if row["identity_passed"]:
        for field, raw_field, parser in (("native_rss_KiB", "VmRSS", kib),
                                         ("native_swap_KiB", "VmSwap", kib),
                                         ("system_swap_free_KiB", "SwapFree", kib),
                                         ("native_cpu_seconds", "cpu_seconds", number)):
            try:
                row[field] = parser(raw_values[raw_field])
            except (ValueError, TypeError) as exc:
                issue("metric", raw_field + ": " + str(exc))
    row["native_rss_GiB"] = None if row["native_rss_KiB"] is None else row["native_rss_KiB"] / KIB_PER_GIB
    row["native_swap_GiB"] = None if row["native_swap_KiB"] is None else row["native_swap_KiB"] / KIB_PER_GIB
    row["system_swap_free_GiB"] = None if row["system_swap_free_KiB"] is None else row["system_swap_free_KiB"] / KIB_PER_GIB
    row["native_cpu_hours"] = None if row["native_cpu_seconds"] is None else row["native_cpu_seconds"] / 3600
    return row


def plot(args):
    manifest_path = args.manifest.resolve()
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("Unknown frozen-input manifest")
    if digest(Path(__file__).read_bytes()) != manifest["implementation"]["sha256"]:
        raise ValueError("Implementation changed; replay the frozen script")
    base = manifest_path.parent
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Use a new plot output directory")
    output.mkdir(parents=True)
    rows = []
    for entry in manifest["inputs"]:
        if "snapshot" not in entry:
            rows.append(extract_one(entry, b"", manifest["expected_identity"]))
            continue
        path = (base / entry["snapshot"]).resolve()
        if base not in path.parents:
            raise ValueError("Snapshot path escapes the frozen artifact")
        raw = path.read_bytes()
        if digest(raw) != entry["sha256"] or len(raw) != entry["bytes"]:
            raise ValueError("Frozen raw snapshot hash/length mismatch: " + entry["original_name"])
        try:
            row = extract_one(entry, raw, manifest["expected_identity"])
        except (TypeError, ValueError, AttributeError, KeyError) as exc:
            # A malformed nested schema remains an explicit failure, never a dropped file.
            row = {"input_index": entry["input_index"], "source_name": entry["original_name"],
                   "source_sha256": entry["sha256"], "utc": None, "identity_passed": False,
                   "issues": [{"kind": "parse", "detail": type(exc).__name__ + ": " + str(exc)}]}
        rows.append(row)
    dated = sorted((r for r in rows if r.get("utc") is not None),
                   key=lambda r: (r["utc"], r["input_index"]))
    if not dated:
        write_json(output / "extracted-observations.json", {"rows": rows})
        raise ValueError("No original UTC values; no data points can be placed")
    for earlier, later in zip(dated, dated[1:]):
        gap = (parse_utc(later["utc"]) - parse_utc(earlier["utc"])).total_seconds()
        later["previous_observation_interval_s"] = gap
        if gap == 0:
            later["issues"].append({"kind": "timestamp", "detail": "duplicate UTC; both rows retained"})
        a, b = earlier.get("native_cpu_seconds"), later.get("native_cpu_seconds")
        if a is not None and b is not None and b < a:
            later["issues"].append({"kind": "counter", "detail": "cumulative CPU decreased; point retained"})
    issue_counts = Counter(i["kind"] for r in rows for i in r["issues"])
    latest = dated[-1]
    cutoff = latest["utc"]
    latest_status = latest.get("run_status") or "UNKNOWN"
    summary = {
        "selected_inputs": len(rows), "timestamped_inputs": len(dated),
        "identity_passed_inputs": sum(bool(r.get("identity_passed")) for r in rows),
        "inputs_with_issues": sum(bool(r["issues"]) for r in rows),
        "issues_by_kind": dict(issue_counts),
        "first_observation_utc": dated[0]["utc"], "observation_cutoff_utc": cutoff,
        "last_observed_status": latest_status,
        "last_wrapper_remote_exit_code": latest.get("wrapper_remote_exit_code"),
        "native_exit_code": None,
        "native_exit_evidence": "No native exit record is supplied by this resource-observation schema; not inferred from a log or wrapper status",
        "full_D3_DC_qualified": False,
    }
    metrics = ("native_rss_GiB", "native_swap_GiB", "system_swap_free_GiB",
               "native_cpu_seconds", "previous_observation_interval_s", "status_to_record_completion_s")
    for key in metrics:
        available = [(r.get(key), r["utc"], r["input_index"]) for r in dated if r.get(key) is not None]
        summary[key] = {"observed_count": len(available),
                        "missing_in_all_selected_count": len(rows) - len(available)}
        if available:
            lo, hi = min(available), max(available)
            summary[key].update(sample_min=lo[0], sample_max=hi[0],
                                sample_min_utc=lo[1], sample_max_utc=hi[1],
                                last_observed_value=available[-1][0])
    units = {"proc_kB": "KiB (1024 bytes), despite /proc spelling kB",
             "GiB": "original KiB / 1048576", "CPU_hours": "original process cpu_seconds / 3600",
             "UTC_axis": "top-level utc: record completion time, not an atomic simultaneous /proc sample",
             "interval_s": "difference between consecutive original record-completion UTC values; first is missing",
             "status_to_record_completion_s": "top-level utc minus status.observed_utc; diagnostic lag, not resource sample duration"}
    extracted = {"schema": "dram-see-v4-native-usage-extraction-r1", "manifest_sha256": digest(manifest_raw),
                 "expected_identity": manifest["expected_identity"], "units": units,
                 "summary": summary, "rows_in_original_manifest_order": rows,
                 "plot_policy": "Every available identity-checked numeric point is drawn as a marker; no filtering by magnitude, smoothing, joined interpolation, imputation, or extrapolation. Invalid/missing observations remain in rows and snapshots."}
    write_json(output / "extracted-observations.json", extracted)
    os.environ["MPLCONFIGDIR"] = str(output / "matplotlib-config")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 150, "savefig.dpi": 220,
                         "svg.hashsalt": digest(manifest_raw)}):
        fig, axes = plt.subplots(3, 1, figsize=(13.2, 9.0), sharex=True,
                                 gridspec_kw={"height_ratios": [2.2, 1.35, 1.1]})

        def series(ax, key, label, color, marker="o", size=9):
            points = [r for r in dated if r.get(key) is not None]
            ax.scatter([parse_utc(r["utc"]) for r in points], [r[key] for r in points],
                       s=size, color=color, marker=marker, label=label, linewidths=0)

        series(axes[0], "native_rss_GiB", "Native RSS", "#167c80", size=11)
        series(axes[0], "native_swap_GiB", "Native VmSwap", "#bd5532", size=11)
        series(axes[0], "system_swap_free_GiB", "System SwapFree (whole VM)", "#5e61a8", size=11)
        axes[0].set_ylabel("Observed memory (GiB)")
        axes[0].legend(loc="upper right", frameon=False, ncol=3)
        series(axes[1], "native_cpu_hours", "Cumulative native process CPU", "#264d70", size=10)
        axes[1].set_ylabel("Cumulative CPU (h)")
        axes[1].legend(loc="upper left", frameon=False)
        series(axes[2], "previous_observation_interval_s", "Actual interval between observations", "#607565", size=10)
        series(axes[2], "status_to_record_completion_s", "Status-to-record completion lag", "#a77730", marker="s", size=8)
        axes[2].set_ylabel("Observed interval (s)")
        axes[2].legend(loc="upper right", frameon=False, ncol=2)
        for ax in axes:
            ax.grid(True, color="#dce2e5", lw=.55)
            ax.set_axisbelow(True)
            ax.set_ylim(bottom=0)
            ax.margins(x=.012)
        lags = [r.get("status_to_record_completion_s") for r in dated
                if r.get("status_to_record_completion_s") is not None]
        if lags and min(lags) < 0:
            # Retain visible clock/collection anomalies instead of clipping them.
            axes[2].set_ylim(bottom=min(lags) - max(1, abs(min(lags)) * .05))
        axes[2].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=12, tz=timezone.utc))
        axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=timezone.utc))
        axes[2].set_xlabel("Record completion UTC | " + parse_utc(dated[0]["utc"]).strftime("%Y-%m-%d"))
        stamp = parse_utc(cutoff).strftime("%Y-%m-%d %H:%M:%SZ")
        fig.suptitle("D3 r15 native resource observations", x=.085, y=.978, ha="left", fontsize=18, weight="bold")
        fig.text(.085, .937, "Cutoff " + stamp + " | " + latest_status +
                 " | Native exit unknown | Full D3 DC unqualified", fontsize=11, color="#8d3a28")
        fig.text(.085, .909, "PID {native_pid} / start ticks {native_start_ticks} | {run_id}".format(**manifest["expected_identity"]),
                 fontsize=9, color="#4d5861")
        fig.text(.085, .055, "{} fixed inputs; {} identity-checked; {} inputs with issues. Markers are observations, with no smoothing or filled gaps.".format(
                 len(rows), summary["identity_passed_inputs"], summary["inputs_with_issues"]), fontsize=9)
        fig.text(.085, .032, "/proc kB = KiB; GiB = KiB / 1,048,576. CPU is accumulated process time, not elapsed wall time. Sample extrema are not whole-run peaks.", fontsize=8.7, color="#4d5861")
        fig.subplots_adjust(left=.085, right=.975, top=.875, bottom=.12, hspace=.17)
        metadata = {"Title": "D3 r15 native resource observations", "Description":
                    "Cutoff " + stamp + "; " + latest_status + "; native exit unknown; full D3 DC unqualified. Explicit frozen input manifest SHA256 " + digest(manifest_raw)}
        fig.savefig(output / "r15-native-usage.png", metadata=metadata)
        fig.savefig(output / "r15-native-usage.svg", metadata=dict(metadata, Date=cutoff, Creator="plot_native_usage.py"))
        plt.close(fig)
    original_checks = []
    for entry in manifest["inputs"]:
        check = {"original_path": entry["original_path"], "captured_sha256": entry.get("sha256")}
        try:
            check["after_plot_sha256"] = file_identity(entry["original_path"])["sha256"]
            check["matches_captured_bytes"] = check["after_plot_sha256"] == entry.get("sha256")
        except OSError as exc:
            check.update(matches_captured_bytes=False, error=str(exc))
        original_checks.append(check)
    write_json(output / "original-input-recheck.json", {"originals_opened_read_only": True,
               "all_original_bytes_match_capture": all(c["matches_captured_bytes"] for c in original_checks),
               "changes_are_reported_not_replaced": True, "checks": original_checks})
    receipt = {"schema": "dram-see-v4-native-usage-plot-receipt-r1", "exit_code": 0,
               "generated_utc": utc_now(), "input_manifest": str(manifest_path),
               "input_manifest_sha256": digest(manifest_raw), "implementation_sha256": digest(Path(__file__).read_bytes()),
               "summary": summary, "unit_conversions": units,
               "runtime": {"python": platform.python_version(), "matplotlib": matplotlib.__version__, "numpy": numpy.__version__},
               "originals_unchanged": all(c["matches_captured_bytes"] for c in original_checks),
               "new_files_after_listing_considered": False,
               "native_or_ssh_or_runner_or_operation_calls": 0, "tests_run": False,
               "outputs": {n: file_identity(output / n) for n in
                           ("r15-native-usage.png", "r15-native-usage.svg", "extracted-observations.json", "original-input-recheck.json")}}
    write_json(output / "plot-receipt.json", receipt)
    return {"status": "PLOTTED_WITH_RECORDED_ISSUES" if summary["inputs_with_issues"] else "PLOTTED",
            "summary": summary, "output": str(output), "originals_unchanged": receipt["originals_unchanged"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("freeze", help="Freeze one original r15 file listing and byte snapshots")
    capture.add_argument("--source-dir", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--run-id", required=True)
    capture.add_argument("--boot-id", required=True)
    capture.add_argument("--pid", type=int, required=True)
    capture.add_argument("--start-ticks", type=int, required=True)
    capture.add_argument("--native-start-utc", required=True)
    draw = commands.add_parser("plot", help="Replay only a frozen manifest; no directory rescan")
    draw.add_argument("--manifest", type=Path, required=True)
    draw.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = freeze(args) if args.command == "freeze" else plot(args)
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "exit_code": 1,
                          "error": type(exc).__name__ + ": " + str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
