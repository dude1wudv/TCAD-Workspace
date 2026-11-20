"""Read-only public projection of the research plan and original run evidence.

The plan owns case identity. A retry is another attempt of the same case.
Codex progress annotations never affect execution or acceptance counts.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
from pathlib import Path


def read_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Invalid research input")
    return data


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def public_id(value):
    if isinstance(value, str) and len(value) <= 96 and (
        re.fullmatch(r"(?:m1-r05|R05|r(?!04-)[0-9]{2,}|BENCH)-[A-Za-z0-9_-]{1,88}", value)
        or re.fullmatch(r"DEV-P[0-9]{3}-C[0-9]{2}-E[0-9]+-B[01]", value)
    ):
        return value
    return None


def runtime_intents(runtime):
    intents = (runtime or {}).get("intents", {})
    if not isinstance(intents, dict) or any(not isinstance(item, dict) for item in intents.values()):
        raise ValueError("Invalid research input")
    return intents


def admission(intent):
    value = intent.get("scientific_admission", {})
    if not isinstance(value, dict):
        raise ValueError("Invalid research input")
    return value


def sealed_case_id(value):
    return isinstance(value, str) and re.match(r"r[0-9]{2,}-(?:hr|hp|holdout)(?:-|$)", value, re.I) is not None


def sealed_intent(intent):
    scientific = admission(intent)
    coordinates = scientific.get("scientific_object", {})
    return (
        scientific.get("scope") == "holdout_evaluation"
        or sealed_case_id(scientific.get("case_id"))
        or isinstance(coordinates, dict) and coordinates.get("block") in {"HR", "HP"}
        or scientific.get("scope") == "transport_pool" and "training_freeze" in scientific
    )


def intent_case_id(intent, fallback=None):
    """An admission, including one without a case, overrides legacy task metadata."""
    if "scientific_admission" in intent:
        scientific = admission(intent)
        if scientific.get("scope") == "p0_diagnostic":
            return None
        return public_id(scientific.get("case_id"))
    return public_id(fallback)


def development_alias(task_id):
    if not isinstance(task_id, str):
        return None
    parts = task_id.split("-")
    values = [next((part[len(prefix):] for part in parts if re.fullmatch(pattern, part)), None)
              for prefix, pattern in (("p", r"p\d{3}"), ("c", r"c\d{2}"), ("event", r"event\d+"), ("b", r"b[01]"))]
    return "DEV-P{}-C{}-E{}-B{}".format(*values) if all(value is not None for value in values) else None


def short_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) else None


PARAMETERS = {
    "Lg_relative", "Wfin_relative", "Tox_relative", "NA_relative", "ND_relative",
    "Lg_scale", "Wfin_scale", "Tox_scale", "NA_scale", "ND_scale",
    "energy_MeV", "theta_deg", "phi_deg", "temperature_K", "stored_bit",
    "requested_threads", "numerical_threads", "grid_points", "research_samples",
}
ACCEPTANCE_RECORD_MAX_BYTES = 1024 * 1024
ACCEPTANCE_EVIDENCE_MAX_BYTES = 4 * 1024 * 1024
ACCEPTANCE_MAX_EVIDENCE = 16
RESEARCH_CACHE_MAX_BYTES = 8 * 1024 * 1024
_PARAMETER_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,40}\Z")
_PRIVATE_PARAMETER = re.compile(
    r"password|passwd|token|api_?key|secret|credential|authorization|bearer|license|"
    r"private|path|directory|filename|url|hostname|sha256|hash|digest|seed|label|holdout|"
    r"(?:^|_)(?:key|ip|address|id|accepted|eligible)(?:_|$)", re.I,
)
_PARAMETER_ENUMS = {
    "particle": {"proton", "neutron", "heavy_ion", "ion", "electron", "alpha"},
    "polarity": {"n", "p", "nmos", "pmos"},
    "mode": {"nominal", "baseline", "control", "response"},
}


def finite_number(value):
    return type(value) in (int, float) and abs(value) <= sys.float_info.max


def parameters(value, *, plan=False):
    if not isinstance(value, dict):
        return {}
    result = {key: number for key, number in value.items() if key in PARAMETERS and finite_number(number)}
    for key in ("Lg", "Wfin", "Tox", "NA", "ND"):
        item = value.get(key)
        if isinstance(item, dict) and (
            item.get("representation") == "baseline_multiplier" and item.get("unit") == "1"
            or item.get("unit") == "baseline_multiplier"
        ):
            number = item.get("value")
            if finite_number(number):
                result[key + "_relative"] = number
    depth = value.get("Hjc")
    if isinstance(depth, dict) and depth.get("unit") == "nm":
        number = depth.get("value")
        if finite_number(number):
            result["Hjc_nm"] = number
    if plan:
        for key, item in value.items():
            if len(result) == 64:
                break
            if (key in result or not isinstance(key, str) or not _PARAMETER_KEY.fullmatch(key)
                    or _PRIVATE_PARAMETER.search(key)):
                continue
            if finite_number(item) or isinstance(item, str) and item in _PARAMETER_ENUMS.get(key, ()):
                result[key] = item
    return result


def optional_snapshot(path):
    try:
        path = Path(path)
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        value = read_bounded_json(path, RESEARCH_CACHE_MAX_BYTES)
    except (OSError, TypeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def load_stats_snapshot(path):
    """Read a qualified statistics snapshot without allowing it to affect execution."""
    value = optional_snapshot(path) or {}
    schema, count = value.get("schema"), value.get("statistics_eligible_cases")
    if (not isinstance(schema, str) or not re.fullmatch(r"tcad-(?:r[0-9]{2,}-)?statistics-snapshot-v1", schema)
            or type(count) is not int or count < 0 or not valid_sha256(value.get("plan_sha256"))
            or not all(valid_sha256(item) for key, item in value.items() if key.endswith("_sha256"))):
        return None
    return {"connected": True, "status": "connected", "statistics_eligible_cases": count,
            "plan_sha256": value["plan_sha256"]}


def load_cached_research(path):
    value = optional_snapshot(path)
    if not isinstance(value, dict) or not isinstance(value.get("research"), dict):
        return None, None
    saved_at = timestamp(value.get("saved_at"))
    if saved_at is None:
        return None, None
    return value["research"], saved_at


def save_cached_research(path, research):
    if not isinstance(research, dict):
        raise ValueError("Invalid research cache")
    destination = Path(path)
    payload = json.dumps({"saved_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                          "research": research}, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if len(payload) > RESEARCH_CACHE_MAX_BYTES:
        raise ValueError("Research cache exceeds size limit")
    fd, temporary = tempfile.mkstemp(prefix="." + destination.name + ".", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def case_run_ids(case):
    values = case.get("run_ids", [])
    if not isinstance(values, list):
        raise ValueError("Invalid research input")
    return [value for value in values if isinstance(value, str)]


def is_archived(manifest):
    return manifest.get("collection_verified") is True and manifest.get("state") in {"COLLECTED", "FAILED_COLLECTED"}


def failed_unlaunched(observation):
    return observation.get("terminal_reconciled") is True and str(observation.get("status")).lower() == "failed_unlaunched"


def execution(manifest, observation, fresh):
    """Only original collection proof can establish completion."""
    collected = is_archived(manifest)
    tools = manifest.get("tool_exit_codes")
    solved = (
        collected and manifest.get("state") == "COLLECTED"
        and type(manifest.get("remote_exit_code")) is int and manifest["remote_exit_code"] == 0
        and type(manifest.get("collection_exit_code")) is int and manifest["collection_exit_code"] == 0
        and isinstance(tools, dict) and bool(tools)
        and all(type(code) is int and code == 0 for code in tools.values())
    )
    if solved:
        return "solved"
    if collected:
        return "failed"
    if failed_unlaunched(observation):
        return "failed"
    if fresh and str(observation.get("status")).lower() == "running":
        return "running"
    return "pending"


def acceptance_verified(case, linked, manifests, plan_path):
    """Require a traceable acceptance record for this exact collected input/result."""
    reference = case.get("acceptance_evidence")
    if case.get("accepted") is not True or not isinstance(reference, str) or not reference:
        return False
    path = Path(reference)
    if not path.is_absolute():
        path = plan_path.parent / path
    record = read_object(path)
    key = record.get("run_id")
    if record.get("status") != "accepted" or record.get("case_id") != case.get("case_id") or key not in linked:
        return False
    manifest = manifests.get(key, {})
    if execution(manifest, {}, False) != "solved":
        return False
    return all(isinstance(record.get(field), str) and re.fullmatch(r"[0-9a-f]{64}", record[field])
               and record[field] == manifest.get(field) for field in ("input_sha256", "results_sha256"))


def private_evidence_path(reference, plan_path):
    """Allow native absolute workspace paths or plan-relative paths, without links."""
    if not isinstance(reference, str) or not reference or "\x00" in reference or ".." in re.split(r"[/\\]", reference):
        raise ValueError("Invalid private acceptance path")
    plan_directory = plan_path.absolute().parent
    workspace = plan_directory.parent.parent if plan_directory.parent.name == "plans" else plan_directory
    path = Path(reference)
    if not path.is_absolute():
        # A Windows drive is not a relative path on a POSIX deployment.
        if re.match(r"^[A-Za-z]:|^\\\\", reference) and path.anchor == "":
            raise ValueError("Invalid private acceptance path")
        path = plan_directory / path
    path = path.absolute()
    try:
        path.relative_to(workspace)
    except ValueError:
        raise ValueError("Private acceptance path is outside the workspace") from None
    try:
        for component in (path,) + tuple(path.parents):
            try:
                info = component.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Private acceptance links are forbidden")
        if path.exists() and not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("Private acceptance requires regular files")
    except OSError:
        raise ValueError("Private acceptance file cannot be inspected") from None
    return path


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate private acceptance field")
        value[key] = item
    return value


def reject_json_constant(value):
    raise ValueError("Non-finite JSON constant is forbidden")


def parse_finite_float(value):
    number = float(value)
    return number if math.isfinite(number) else reject_json_constant(value)


def read_bounded_json(path, limit):
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except FileNotFoundError:
        raise
    except OSError:
        raise ValueError("Private acceptance record cannot be read") from None
    if len(data) > limit:
        raise ValueError("Private acceptance record exceeds size limit")
    try:
        return json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=unique_object,
            parse_constant=reject_json_constant,
            parse_float=parse_finite_float,
        )
    except (UnicodeError, ValueError):
        raise ValueError("Invalid private acceptance record") from None


def hash_bounded_file(path, limit):
    try:
        if path.stat().st_size > limit:
            raise ValueError("Private acceptance evidence exceeds size limit")
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += len(chunk)
                if total > limit:
                    raise ValueError("Private acceptance evidence exceeds size limit")
                digest.update(chunk)
        return digest.hexdigest()
    except ValueError:
        raise
    except OSError:
        raise ValueError("Private acceptance evidence cannot be read") from None


def gate_acceptance_verified(case, linked, manifests, plan_path, gate_dir):
    """Verify external evidence without modifying or trusting frozen plan flags."""
    identity = case["case_id"]
    record_path = private_evidence_path(
        "{}/case-acceptance/{}.json".format(gate_dir, identity), plan_path,
    )
    try:
        record = read_bounded_json(record_path, ACCEPTANCE_RECORD_MAX_BYTES)
    except FileNotFoundError:
        return False
    except ValueError:
        raise ValueError("Invalid private acceptance record") from None
    if not isinstance(record, dict):
        raise ValueError("Invalid private acceptance record")
    run_id = record.get("run_id")
    if (
        not (isinstance(record.get("schema"), str)
             and re.fullmatch(r"tcad-[A-Za-z0-9_-]+-case-acceptance-v1", record["schema"]))
        or record.get("status") != "accepted" or record.get("case_id") != identity
        or not isinstance(run_id, str) or run_id not in linked
    ):
        return False
    manifest = manifests.get(run_id, {})
    if manifest.get("run_id") != run_id or execution(manifest, {}, False) != "solved":
        return False
    inputs = record.get("input_sha256")
    digest = record.get("results_sha256")
    if (
        not isinstance(inputs, dict) or not inputs
        or any(not isinstance(name, str) or not name or not valid_sha256(value) for name, value in inputs.items())
        or inputs != manifest.get("input_sha256")
        or not valid_sha256(digest) or digest != manifest.get("results_sha256")
    ):
        return False
    return private_evidence_verified(record.get("evidence"), plan_path, "Private acceptance")


def valid_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def private_evidence_verified(evidence, plan_path, label):
    if not isinstance(evidence, list) or not evidence:
        return False
    if len(evidence) > ACCEPTANCE_MAX_EVIDENCE:
        raise ValueError("{} evidence list exceeds size limit".format(label))
    for reference in evidence:
        if (
            not isinstance(reference, dict) or not valid_sha256(reference.get("sha256"))
            or not isinstance(reference.get("path"), str) or not reference["path"]
        ):
            return False
        path = private_evidence_path(reference["path"], plan_path)
        if not path.exists():
            return False
        actual = hash_bounded_file(path, ACCEPTANCE_EVIDENCE_MAX_BYTES)
        if actual.lower() != reference["sha256"].lower():
            return False
    return True


def z_baseline_reuse_verified(case, manifests, p0_admissions, plan_path, plan_sha256, timing_contract, gate_dir):
    """Validate an explicit full-WHR P0-to-Z reuse binding without exposing it."""
    identity = case["case_id"]
    record_path = private_evidence_path(
        "{}/z-baseline-reuse/{}.json".format(gate_dir, identity), plan_path,
    )
    try:
        record = read_bounded_json(record_path, ACCEPTANCE_RECORD_MAX_BYTES)
    except FileNotFoundError:
        return None
    except ValueError:
        raise ValueError("Invalid private Z baseline reuse record") from None
    if not isinstance(record, dict):
        raise ValueError("Invalid private Z baseline reuse record")

    run_id = record.get("run_id")
    if (
        not (isinstance(record.get("schema"), str)
             and re.fullmatch(r"tcad-[A-Za-z0-9_-]+-z-baseline-reuse-v1", record["schema"]))
        or record.get("status") != "validated"
        or record.get("case_id") != identity
        or not isinstance(run_id, str)
        or run_id not in p0_admissions
    ):
        return None

    admission = p0_admissions[run_id]
    if (
        admission.get("scope") != "p0_diagnostic"
        or record.get("recipe_id") != "zero_whr"
        or admission.get("recipe_id") not in (None, "zero_whr")
        or admission.get("profile_id") not in (None, case.get("profile_id"))
        or record.get("profile_id") != case.get("profile_id")
        or record.get("stored_bit") != case.get("stored_bit")
        or record.get("plan_sha256") != plan_sha256
        or record.get("run_kind") != "full_whr_baseline"
        or record.get("is_prefix") is not False
    ):
        return None

    manifest = manifests.get(run_id, {})
    if manifest.get("run_id") != run_id or execution(manifest, {}, False) != "solved":
        return None

    timing = record.get("timing_contract")
    if not isinstance(timing, dict):
        return None
    if (
        timing.get("deck_timing_version") != case.get("deck_timing_version")
        or timing.get("deck_timing_version") != timing_contract.get("deck_timing_version")
        or timing.get("hold_window_ns") != timing_contract.get("hold_window_ns")
        or not valid_sha256(timing.get("timing_sha256"))
    ):
        return None

    qualification = record.get("profile_qualification")
    if not isinstance(qualification, dict) or (
        qualification.get("status") != "passed"
        or qualification.get("profile_id") != case.get("profile_id")
        or set(qualification.get("qualified_bits", [])) != {0, 1}
    ):
        return None

    inputs = record.get("input_sha256")
    digest = record.get("results_sha256")
    if (
        not isinstance(inputs, dict) or not inputs
        or any(not isinstance(name, str) or not name or not valid_sha256(value)
               for name, value in inputs.items())
        or inputs != manifest.get("input_sha256")
        or not valid_sha256(digest)
        or digest != manifest.get("results_sha256")
    ):
        return None
    if not private_evidence_verified(record.get("evidence"), plan_path, "Private Z reuse"):
        return None
    return run_id


COUNT_FIELDS = ("planned", "archived", "solved", "accepted", "running", "failed", "remaining")
LEGACY_COHORTS = ("core", "reserve", "control")
LEGACY_CASE_PREFIXES = ("m1-r05-", "r05-", "R05-")
SEALED_BLOCKS = {"HR", "HP"}
NON_FORMAL_KINDS = {"benchmark", "performance_probe", "diagnostic", "p0_diagnostic"}
DIAGNOSTIC_SCOPE = "p0_diagnostic"


def empty_counts():
    return dict.fromkeys(COUNT_FIELDS, 0)


def add_state(count, state, accepted=False, archived=False):
    count["planned"] += 1
    count["archived"] += int(archived)
    count["solved"] += int(state == "solved")
    count["accepted"] += int(accepted)
    count["running"] += int(state == "running")
    count["failed"] += int(state == "failed")
    count["remaining"] += int(not accepted)


def observation_fresh(observation, now):
    observed_at = timestamp(observation.get("utc"))
    threshold = observation.get("fresh_max_age_seconds", 180)
    threshold = threshold if type(threshold) is int and 30 <= threshold <= 180 else 180
    current = now or dt.datetime.now(dt.timezone.utc)
    fresh = bool(observed_at and -60 <= (
        current - dt.datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    ).total_seconds() <= threshold)
    return observed_at, fresh


def is_zero(case):
    return (case.get("block") or case.get("cohort")) == "Z" or case.get("kind") == "zero"


def case_is_sealed(case):
    # Shared zero controls include profile qualification without exposing profile parameters.
    return case.get("sealed") is True or (
        bool(case.get("holdout")) and not (is_zero(case) and case.get("holdout") == "profile")
    )


def plan_blocks(plan, cases):
    blocks = {}
    for block, case in cases:
        blocks.setdefault(block, []).append(case)

    declared = plan.get("blocks", [])
    if not isinstance(declared, list) or any(not isinstance(item, dict) for item in declared):
        raise ValueError("Invalid research blocks")
    # Use the declared order where available, retaining blocks described only by cases.
    order = dict.fromkeys(short_id(item.get("id")) for item in declared)
    order.update(dict.fromkeys(blocks))
    blocks = {block: blocks[block] for block in order if block in blocks}
    explicit = {item["id"]: item["sealed"] for item in declared
                if short_id(item.get("id")) and type(item.get("sealed")) is bool}
    specified = plan.get("sealed_blocks")
    if specified is not None:
        if not isinstance(specified, list) or any(not short_id(block) for block in specified):
            raise ValueError("Invalid sealed research blocks")
        explicit.update({block: True for block in specified})
    sealed_blocks = {
        block for block, members in blocks.items()
        if explicit.get(block, all(case_is_sealed(case) for case in members) or block in SEALED_BLOCKS)
    }
    sealed_ids = {
        case["case_id"] for block, members in blocks.items() for case in members
        if block in sealed_blocks or case_is_sealed(case)
    }
    return blocks, sealed_blocks, sealed_ids


def plan_budget(plan, blocks, cases, profiles, radiations, stats_snapshot):
    expected = {
        "total_cases": len(cases),
        "zero_cases": sum(is_zero(case) for case in cases),
        "profile_count": len(profiles),
        "radiation_count": len(radiations),
        "statistics_intent_cases": sum(case.get("statistics_intent") is True for case in cases),
    }
    declared = plan.get("budget", {})
    if not isinstance(declared, dict):
        raise ValueError("Invalid research plan budget")
    for key, actual in expected.items():
        if key in declared and (type(declared[key]) is not int or declared[key] != actual):
            raise ValueError("Invalid research plan budget")
    block_sizes = {block: len(items) for block, items in blocks.items()}
    if "block_case_counts" in declared:
        sizes = declared["block_case_counts"]
        if not isinstance(sizes, dict) or sizes != block_sizes or any(type(value) is not int for value in sizes.values()):
            raise ValueError("Invalid research plan budget")
    eligible = (stats_snapshot or {}).get("statistics_eligible_cases")
    connected = ((stats_snapshot or {}).get("connected") is True
                 and type(eligible) is int and 0 <= eligible <= len(cases))
    return {
        **{key: declared.get(key, value) for key, value in expected.items()},
        "statistics_eligible_cases": eligible if connected else 0,
        "manifest_eligible_cases": sum(case.get("statistics_eligible") is True for case in cases),
    }, "connected" if connected else "not_connected"


def diagnostic_bucket(scope):
    if scope in (None, "", DIAGNOSTIC_SCOPE):
        return "P0"
    return scope if isinstance(scope, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,32}", scope) else "P0"


def diagnostic_scope(scope):
    return isinstance(scope, str) and scope.endswith("_diagnostic")


def build_research(plan_path: Path, manifests: dict, observation: dict, progress: list, now=None,
                   runtime=None, work_items=None, scheduler=None, stats_snapshot=None):
    plan = read_object(plan_path)
    if not plan:
        return {"schema_version": 1, "available": False, "progress": [], "cases": [], "conditions": [], "profiles": []}
    cases, profiles, radiations, conditions = (plan.get(key, []) for key in ("cases", "profiles", "radiations", "conditions"))
    if (plan.get("schema_version") != 1 or "cases" not in plan
            or any(not isinstance(items, list) or any(not isinstance(item, dict) for item in items)
                   for items in (cases, profiles, radiations, conditions))):
        raise ValueError("Invalid research input")
    for items in (profiles, radiations):
        identities = {short_id(item.get("id")) for item in items}
        if None in identities or len(identities) != len(items):
            raise ValueError("Invalid research parameter identities")
    revision = plan.get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"r[0-9]{1,8}\.[0-9]{1,8}", revision):
        raise ValueError("Invalid research revision")
    slug = revision.replace(".", "")
    gate_dir = plan.get("gate_dir", f"{slug}-gate/results")
    if not isinstance(gate_dir, str) or not gate_dir:
        raise ValueError("Invalid research gate path")
    gate_dir = gate_dir.rstrip("/\\")

    legacy = bool(conditions and cases) and all(
        "block" not in case and case.get("cohort") in LEGACY_COHORTS
        and str(case.get("case_id")).startswith(LEGACY_CASE_PREFIXES) for case in cases
    )
    seen = {}
    for case in cases:
        identity = case.get("case_id")
        block = short_id(case.get("block") or case.get("cohort"))
        if not public_id(identity) or identity in seen or block is None or (
            not identity.startswith(slug + "-") and not legacy
        ):
            raise ValueError("Invalid research input")
        seen[identity] = (block, case)
    blocks, sealed_blocks, sealed_ids = plan_blocks(plan, seen.values())
    counts = {block: empty_counts() for block in (LEGACY_COHORTS if legacy else blocks)}
    pairs = {block: set() for block in counts}
    observed_at, fresh = observation_fresh(observation, now)
    runs = {item.get("run_id"): item for item in observation.get("runs", []) if isinstance(item, dict)}
    intents = runtime_intents(runtime)
    bindings, runtime_identities, p0_admissions = {}, {}, {}
    excluded_runs = set()
    private_runs = {key for identity in sealed_ids for key in case_run_ids(seen[identity][1])}
    diagnostics, diagnostic_run_tasks = {}, {}
    for task_id, intent in intents.items():
        scientific = admission(intent)
        scope = scientific.get("scope")
        run_id = intent.get("run_id")
        identity = intent_case_id(intent)
        if isinstance(run_id, str):
            if "scientific_admission" in intent:
                runtime_identities[run_id] = identity
            if sealed_intent(intent) or identity in sealed_ids:
                private_runs.add(run_id)
        if diagnostic_scope(scope) and not sealed_intent(intent) and identity not in sealed_ids:
            diagnostics[task_id] = (diagnostic_bucket(scope), run_id, False, None)
            if isinstance(run_id, str):
                diagnostic_run_tasks[run_id] = task_id
                excluded_runs.add(run_id)
                if scope == DIAGNOSTIC_SCOPE:
                    p0_admissions[run_id] = scientific
        elif identity in seen and isinstance(run_id, str):
            bindings.setdefault(identity, set()).add(run_id)

    for task in (work_items or {}).get("tasks", []):
        if not isinstance(task, dict):
            raise ValueError("Invalid research input")
        intent = intents.get(task.get("id"), {})
        identity = intent_case_id(intent, task.get("case_id"))
        if identity in seen and isinstance(intent.get("run_id"), str):
            bindings.setdefault(identity, set()).add(intent["run_id"])

    reuse_run_cases = {}
    timing_contract = plan.get("timing_contract")
    stats_snapshot = stats_snapshot if isinstance(stats_snapshot, dict) else None
    plan_sha256 = None
    if stats_snapshot or (p0_admissions and isinstance(timing_contract, dict)):
        plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    if stats_snapshot and str(stats_snapshot.get("plan_sha256")).lower() != plan_sha256:
        stats_snapshot = None
    budget, statistics_snapshot_status = plan_budget(plan, blocks, cases, profiles, radiations, stats_snapshot)
    if p0_admissions and isinstance(timing_contract, dict):
        for identity, (_, case) in seen.items():
            if not is_zero(case):
                continue
            run_id = z_baseline_reuse_verified(
                case, manifests, p0_admissions, plan_path, plan_sha256, timing_contract, gate_dir,
            )
            if run_id is None:
                continue
            if run_id in reuse_run_cases:
                raise ValueError("A P0 run cannot be reused for multiple Z cases")
            reuse_run_cases[run_id] = identity
            excluded_runs.discard(run_id)
            bindings.setdefault(identity, set()).add(run_id)

    for key, item in list(manifests.items()) + list(runs.items()):
        if item.get("kind") in NON_FORMAL_KINDS and key not in reuse_run_cases:
            excluded_runs.add(key)
        identity = runtime_identities.get(key, public_id(item.get("case_id")))
        if identity in sealed_ids or item.get("sealed") is True or item.get("holdout") or sealed_case_id(item.get("case_id")):
            private_runs.add(key)
        if identity in seen and key not in excluded_runs:
            bindings.setdefault(identity, set()).add(key)

    # Scheduler IDs may match work-item IDs directly or be associated privately by the manifest reader.
    scheduler_runs = {item["_scheduler_task_id"]: run_id for run_id, item in manifests.items()
                      if isinstance(item.get("_scheduler_task_id"), str)}
    running = set()
    diagnostics_from_scheduler = set()
    for task in (scheduler or {}).get("tasks", []):
        if not isinstance(task, dict) or task.get("kind") in {"sealed", "unmatched", "benchmark", "performance_probe"}:
            continue
        task_id = short_id(task.get("id"))
        run_id = scheduler_runs.get(task_id, task.get("run_id"))
        intent = intents.get(task_id, {})
        if not isinstance(run_id, str):
            run_id = intent.get("run_id")
        run_id = run_id if isinstance(run_id, str) else None
        tagged_case = public_id(task.get("case_id"))
        identity = runtime_identities.get(run_id, intent_case_id(intent, tagged_case))
        scientific = admission(intent)
        task_admission = task.get("scientific_admission")
        scope = scientific.get("scope") or (task_admission.get("scope") if isinstance(task_admission, dict) else None) or task.get("scope")
        task_running = task.get("state") == "running" and not scheduler.get("observation_stale")
        if (identity in sealed_ids or tagged_case in sealed_ids or run_id in private_runs
                or task.get("sealed") is True or task.get("holdout") or scope == "holdout_evaluation"):
            continue
        if task.get("kind") in {"diagnostic", "p0_diagnostic"} or diagnostic_scope(scope):
            if task_id is None:
                continue
            key = task_id if task_id in diagnostics else diagnostic_run_tasks.get(run_id, task_id)
            bucket, previous_run, was_running, scheduler_state = diagnostics.get(
                key, (diagnostic_bucket(scope), run_id, False, None))
            if key not in diagnostics:
                diagnostics_from_scheduler.add(bucket)
            task_state = task.get("state") if task.get("state") in {
                "running", "collecting", "uncollected", "completed", "failed", "pending", "unknown",
            } else None
            diagnostics[key] = (bucket, previous_run or run_id, was_running or task_running,
                                task_state or scheduler_state)
        elif task_running and identity in seen and run_id not in excluded_runs:
            running.add(identity)

    public_diagnostics = {"P0": {key: 0 for key in COUNT_FIELDS if key not in {"accepted", "remaining"}}}
    for bucket, run_id, scheduler_running, scheduler_state in diagnostics.values():
        count = public_diagnostics.setdefault(bucket, dict.fromkeys(public_diagnostics["P0"], 0))
        archived = is_archived(manifests.get(run_id, {}))
        state = execution(manifests.get(run_id, {}), runs.get(run_id, {}), fresh)
        if scheduler_state in {"collecting", "uncollected", "completed", "failed"} and state == "running":
            state = "pending"
        if scheduler_running and state == "pending":
            state = "running"
            diagnostics_from_scheduler.add(bucket)
        count["planned"] += 1
        count["archived"] += int(archived)
        if state in ("running", "solved", "failed"):
            count[state] += 1

    public_cases = []
    for identity, (block, case) in seen.items():
        linked = (set(case_run_ids(case)) | bindings.get(identity, set())) - excluded_runs
        linked = {key for key in linked if (
            reuse_run_cases[key] == identity if key in reuse_run_cases else runtime_identities.get(key, identity) == identity
        )}
        states = [execution(manifests.get(key, {}), runs.get(key, {}), fresh) for key in linked]
        state = next((value for value in ("solved", "running", "failed") if value in states
                      or value == "running" and identity in running), "pending")
        accepted = state == "solved" and (
            gate_acceptance_verified(case, linked, manifests, plan_path, gate_dir)
            or legacy and acceptance_verified(case, linked, manifests, plan_path)
        )
        add_state(counts[block], state, accepted,
                  archived=any(is_archived(manifests.get(key, {})) for key in linked))
        if identity in sealed_ids:
            continue
        kind = "control" if is_zero(case) or case.get("kind") == "control" else "response"
        pair = short_id(case.get("pair_id"))
        if pair and kind == "response":
            pairs[block].add(pair)
        primary_index = case.get("sample_index", case.get("primary_index"))
        row = {
            "case_id": identity, "cohort": block, "kind": kind,
            "profile_id": short_id(case.get("profile_id")), "condition_id": short_id(case.get("condition_id")),
            "stored_bit": case.get("stored_bit") if type(case.get("stored_bit")) is int and case["stored_bit"] in (0, 1) else None,
            "primary_index": primary_index if type(primary_index) is int else None,
            "pair_id": pair, "state": "accepted" if accepted else state,
            "attempts": max(len(states), int(identity in running)),
        }
        if not legacy:
            row.update(block=block, radiation_id=short_id(case.get("radiation_id")),
                       statistics_intent=case.get("statistics_intent") is True, statistics_eligible=False)
        public_cases.append(row)

    private_profiles = {item["id"] for item in profiles if case_is_sealed(item)
                        or item.get("partition") in ("profile_holdout", "holdout", "sealed")}
    private_radiations = {item["id"] for item in radiations if case_is_sealed(item)
                          or item.get("role") in ("radiation_holdout", "holdout", "sealed")}
    public_profiles = [
        {"id": item["id"], **({} if legacy else {"sealed": item["id"] in private_profiles}),
         "parameters": {} if item["id"] in private_profiles else parameters(item.get("parameters"), plan=True)}
        for item in profiles
    ]
    public_radiations = []
    for item in radiations:
        sealed = item["id"] in private_radiations
        nested = item.get("parameters")
        values = {key: value for key, value in item.items() if not isinstance(value, str)}
        if isinstance(nested, dict):
            values.update(nested)
        public_radiations.append({"id": item["id"], "sealed": sealed,
                                  "parameters": {} if sealed else parameters(values, plan=True)})
    public_conditions = []
    for item in conditions:
        identity = short_id(item.get("id"))
        profile, radiation = short_id(item.get("profile_id")), short_id(item.get("radiation_id"))
        if (not identity or case_is_sealed(item) or profile in private_profiles or radiation in private_radiations):
            continue
        selected = [case for case in public_cases if case["condition_id"] == identity]
        cohort = item.get("block") or item.get("cohort")
        nested = item.get("parameters")
        public_conditions.append({
            "id": identity, "profile_id": profile, "radiation_id": radiation,
            "cohort": cohort if cohort in counts else None,
            "parameters": parameters({**item, **(nested if isinstance(nested, dict) else {})}, plan=True),
            "planned": len(selected), "solved": sum(case["state"] in {"solved", "accepted"} for case in selected),
            "accepted": sum(case["state"] == "accepted" for case in selected),
            "running": sum(case["state"] == "running" for case in selected),
        })

    development_ids = {development_alias(item.get("id")) for key, item in runs.items() if key not in private_runs} - {None}
    public_progress = [entry for entry in progress if entry.get("case_id") not in sealed_ids and (
        entry.get("case_id") in seen or entry.get("case_id") in development_ids
        or str(entry.get("case_id", "")).startswith("BENCH-")
    )]
    result = {
        "schema_version": 1, "available": True, "revision": revision,
        "updated_at": timestamp(plan.get("updated_at")), "observed_at": observed_at, "observation_stale": not fresh,
        "counts": counts, "conditions": public_conditions, "profiles": public_profiles, "cases": public_cases,
        "progress": public_progress, "acceptance_basis": "original_collection_and_scientific_evidence",
    }
    if legacy:
        for block in counts:
            counts[block]["pairs"] = len(pairs[block])
    else:
        result.update(
            totals={key: sum(count[key] for count in counts.values()) for key in COUNT_FIELDS},
            budget=budget, blocks=[{"id": block, "sealed": block in sealed_blocks, **count}
                                   for block, count in counts.items()],
            diagnostics={bucket: {**count, "included_in_formal_plan": False,
                                  "count_basis": "runtime_intents_and_scheduler" if bucket in diagnostics_from_scheduler
                                  else "runtime_intents"} for bucket, count in public_diagnostics.items()},
            radiations=public_radiations, statistics_basis="external_qualified_snapshot_required",
            statistics_snapshot_status=statistics_snapshot_status,
        )
    return result
