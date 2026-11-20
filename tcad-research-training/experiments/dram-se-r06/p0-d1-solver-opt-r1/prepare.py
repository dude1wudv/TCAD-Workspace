"""Freeze a D1 solver variant from an existing mixed-mode project."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
from shutil import copyfile


HERE = Path(__file__).resolve().parent
VARIANTS = {"pardiso_damped_r12": "ParDiSo", "ils2_damped_r12": "ILS(set=2)"}
SOLVER_ONLY = {"pardiso_only": "ParDiSo", "ils2_only": "ILS(set=2)"}
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
IGNORED = re.compile(r'"(?:\\.|[^"\\])*"|^[ \t]*\*[^\r\n]*|#[^\r\n]*', re.M)
TRANSIENT = re.compile(r"\bTransient\s*\(")
READ = r'\bSet\s*\(\s*rdrive\s*\.\s*"resistance"\s*=\s*' + NUMBER + r"\s*\)"
FINAL_PLOT = r'\bPlot\s*\(\s*FilePrefix\s*=\s*"final"\s+Time\s*=\s*\([^()]*\)\s*\)'
NS = Decimal("1e-9")
TIME_EPSILON = Decimal("1e-12")  # ns, for float literals emitted by the source builder


def masked(text, *, keep_strings=False):
    return IGNORED.sub(
        lambda match: match[0] if keep_strings and match[0].startswith('"')
        else re.sub(r"[^\r\n]", " ", match[0]), text)


def closing(code, start, left, right):
    depth = 0
    for match in re.finditer(f"[{re.escape(left + right)}]", code[start:]):
        depth += 1 if match[0] == left else -1
        if depth == 0:
            return start + match.start()
    raise ValueError(f"Unclosed {left} in device.cmd")


def block(source, name):
    code = masked(source)
    for match in re.finditer(r"\b" + name + r"\s*\{", code):
        prefix = code[:match.start()]
        if prefix.count("{") == prefix.count("}"):
            return match.end(), closing(code, match.end() - 1, "{", "}")
    raise ValueError(f"Missing global {name} block")


def setting(text, name, value, pattern=NUMBER):
    matches = list(re.finditer(r"\b" + name + r"\s*=\s*" + pattern, masked(text)))
    if len(matches) > 1:
        raise ValueError(f"Multiple {name} settings")
    if matches:
        match = matches[0]
        return text[:match.start()] + f"{name}={value}" + text[match.end():]
    return f" {name}={value}" + text


def transients(solve):
    code = masked(solve)
    cursor = 0
    while match := TRANSIENT.search(code, cursor):
        args_end = closing(code, match.end() - 1, "(", ")")
        body_start = args_end + 1
        while body_start < len(code) and code[body_start].isspace():
            body_start += 1
        if body_start == len(code) or code[body_start] != "{":
            raise ValueError("Missing Transient body")
        cursor = closing(code, body_start, "{", "}") + 1
        args = code[match.end():args_end]
        times = [re.search(r"\b" + name + r"\s*=\s*(" + NUMBER + ")", args)
                 for name in ("InitialTime", "FinalTime")]
        if any(value is None for value in times):
            raise ValueError("Missing Transient time bounds")
        yield match.start(), cursor, body_start, *(Decimal(value[1]) / NS for value in times)


def near(left, right):
    return abs(left - right) <= TIME_EPSILON


def time_token(ns):
    return f"{ns.normalize():f}e-9"


def checkpoint_name(ns):
    return "hold_" + format(ns.normalize(), "f").replace(".", "p") + "ns"


def checkpoint_segment(solve, ns):
    for start, _, body, first, last in transients(solve):
        if near(first, ns) or first < ns < last and not near(last, ns):
            return start, body
    raise ValueError(f"No Transient continues from {ns} ns")


def replace_command(text, pattern, replacement):
    match = re.search(pattern, masked(text, keep_strings=True))
    if match:
        return text[:match.start()] + replacement + text[match.end():]
    return text


def release_initial_nodes(source, skipped):
    released = re.findall(r"\bUnset\s*\(\s*(\w+)\s*\)", masked(skipped))
    if not released:
        return source
    start, stop = block(source, "System")
    system = source[start:stop]
    for node in released:
        # The checkpoint already holds the state after this initialization clamp was released.
        system = replace_command(system, r"\bSet\s*\(\s*" + node + r"\s*=\s*" + NUMBER + r"\s*\)", "")
    return source[:start] + system + source[stop:]


def transform_deck(source: str, *, submethod: str = "ParDiSo", threads: int = 2,
                   iterations: int = 25, not_damped: int = 8, rhs_min: str | None = "1e-10",
                   rdrive_read_ohm: str = "1e12", end_ns: float | None = 32.1,
                   save_checkpoint_ns: float | None = None, load_checkpoint: str | None = None) -> str:
    """Preserve the D1 deck and edit its global solver settings and Solve schedule."""
    start, stop = block(source, "Math")
    math = source[start:stop]
    for key, value in (("Number_Of_Threads", threads), ("Iterations", iterations), ("NotDamped", not_damped)):
        math = setting(math, key, value)
    math = setting(math, "SubMethod", submethod, r"\w+(?:\s*\([^()]*\))?")
    if rhs_min is not None:
        math = setting(math, "RHSMin", rhs_min)
    source = source[:start] + math + source[stop:]

    start, stop = block(source, "Solve")
    solve = source[start:stop]
    if len(re.findall(READ, masked(solve, keep_strings=True))) != 1:
        raise ValueError("Expected one D1 read-drive Set command")
    solve = replace_command(solve, READ, f'Set(rdrive."resistance"={rdrive_read_ohm})')

    if load_checkpoint is not None:
        match = re.fullmatch(r"(?:[\w-]+/)*hold_(\d+(?:p\d+)?)ns", load_checkpoint)
        if not match:
            raise ValueError("Expected a checkpoint prefix such as hold_21p9ns")
        ns = Decimal(match[1].replace("p", "."))
        head, body = checkpoint_segment(solve, ns)
        removed_setup = solve[:head]
        solve = (f'\n Load(FilePrefix="{load_checkpoint}")\n '
                 + setting(solve[head:body], "InitialTime", time_token(ns)) + solve[body:])

    if end_ns is not None:
        ns = Decimal(str(end_ns))
        for head, tail, body, first, last in transients(solve):
            if ns < first or near(ns, first):
                raise ValueError(f"No Transient ends at {ns} ns")
            if ns < last or near(ns, last):
                segment = setting(solve[head:body], "FinalTime", time_token(ns)) + solve[body:tail]
                plot = f'Plot(FilePrefix="final" Time=({time_token(ns)}))'
                if re.search(FINAL_PLOT, masked(segment, keep_strings=True)):
                    segment = replace_command(segment, FINAL_PLOT, plot)
                else:
                    segment = segment[:-1].rstrip() + "\n  " + plot + "\n }"
                solve = solve[:head] + segment + "\n"
                break

    if save_checkpoint_ns is not None:
        ns = Decimal(str(save_checkpoint_ns))
        save = f'Save(FilePrefix="{checkpoint_name(ns)}")'
        for head, tail, body, first, last in transients(solve):
            if near(ns, last):
                solve = solve[:tail] + "\n " + save + solve[tail:]
                break
            if first < ns < last and not near(ns, first):
                args = solve[head:body]
                first_body = replace_command(solve[body:tail], FINAL_PLOT, "")
                first_half = setting(args, "FinalTime", time_token(ns)) + first_body
                second_half = setting(args, "InitialTime", time_token(ns)) + solve[body:tail]
                solve = solve[:head] + first_half + "\n " + save + "\n " + second_half + solve[tail:]
                break
        else:
            raise ValueError(f"No Transient reaches checkpoint at {ns} ns")

    result = source[:start] + solve + source[stop:]
    return release_initial_nodes(result, removed_setup) if load_checkpoint is not None else result


def checkpoint_files(prefix):
    return [prefix + "_access_des.sav", prefix + "_circuit_des.sav"]


def freeze_project(project, variant, *, end_ns=argparse.SUPPRESS, save_checkpoint_ns=None, load_checkpoint=None):
    name = variant
    if save_checkpoint_ns is not None:
        name += "_save_" + checkpoint_name(Decimal(str(save_checkpoint_ns)))
    if load_checkpoint is not None:
        name += "_load_" + Path(load_checkpoint).name
    target = HERE / "inputs" / name
    source = (project / "device.cmd").read_bytes().decode("utf-8")
    spec = json.loads((project / "project.json").read_bytes())
    if variant in SOLVER_ONLY:
        if end_ns != argparse.SUPPRESS or save_checkpoint_ns is not None or load_checkpoint is not None:
            raise ValueError("A solver-only comparison preserves the baseline time range and checkpoint")
        start, stop = block(source, "Math")
        pattern = r"\bSubMethod\s*=\s*(\w+(?:\s*\([^()]*\))?)"
        matches = list(re.finditer(pattern, masked(source[start:stop]), re.I))
        if len(matches) != 1:
            raise ValueError("Expected one explicit global SubMethod for the solver-only comparison")
        match = matches[0]
        method = SOLVER_ONLY[variant]
        if re.sub(r"\s+", "", match[1]).casefold() == method.casefold():
            raise ValueError("Baseline already uses the requested SubMethod")
        deck = source[:start + match.start(1)] + method + source[start + match.end(1):]
    else:
        deck = transform_deck(source, submethod=VARIANTS[variant],
                              end_ns=32.1 if end_ns == argparse.SUPPRESS else end_ns,
                              save_checkpoint_ns=save_checkpoint_ns, load_checkpoint=load_checkpoint)
        spec.update(native_threads=2, native_cores=2)
    spec["name"] = name
    checkpoint_inputs = checkpoint_files(load_checkpoint) if load_checkpoint is not None else []
    for path in checkpoint_inputs:
        if not (project / path).is_file():
            raise FileNotFoundError(project / path)
    generated = {path for step in spec.get("steps", []) for path in step.get("outputs", [])}
    for step in spec.get("steps", []):
        if step.get("tool") != "sdevice" or "device.cmd" not in step.get("args", []):
            continue
        outputs = step.get("outputs", [])
        if load_checkpoint is not None:
            outputs = [path for path in outputs if not path.startswith("initial_") and path not in checkpoint_inputs]
        if save_checkpoint_ns is not None:
            prefix = checkpoint_name(Decimal(str(save_checkpoint_ns)))
            outputs = list(dict.fromkeys(outputs + checkpoint_files(prefix)))
        step["outputs"] = outputs

    inputs = [path.relative_to(project) for path in sorted(project.rglob("*")) if path.is_file()]
    target.mkdir(parents=True)
    for path in inputs:
        if path.as_posix() in {"device.cmd", "project.json"} or (
                path.as_posix() in generated and path.as_posix() not in checkpoint_inputs):
            continue
        output = target / path
        output.parent.mkdir(parents=True, exist_ok=True)
        copyfile(project / path, output)
    (target / "device.cmd").write_bytes(deck.encode("utf-8"))
    (target / "project.json").write_bytes((json.dumps(spec, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Input project directory")
    parser.add_argument("--variant", required=True, choices=(*VARIANTS, *SOLVER_ONLY))
    parser.add_argument("--end-ns", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--save-checkpoint-ns", type=float)
    parser.add_argument("--load-checkpoint", help="Checkpoint file prefix relative to the input project")
    args = parser.parse_args()
    target = freeze_project(**vars(args))
    print(json.dumps({"project": target.as_posix(), "variant": args.variant, "frozen": True, "queued": False}))


if __name__ == "__main__":
    main()
