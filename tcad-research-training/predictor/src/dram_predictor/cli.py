"""Explicit offline commands; preparation never starts fitting or simulation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .config import Config
from .data import DataError, Snapshot, read_json, write_json


def parser():
    result = argparse.ArgumentParser(prog="dram-predictor",
        description="Offline r0.4 DRAM R/A/F pipeline. No solver, SSH, service or queue control.")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("inspect", "prepare", "ingest", "import-r04"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument("--out", type=Path, required=name in {"prepare", "ingest", "import-r04"})
    command = commands.add_parser("train",
        help="dry preparation by default; --execute explicitly requests fitting")
    command.add_argument("manifest", type=Path)
    command.add_argument("--prepared", type=Path, help="directory containing frozen splits.json")
    command.add_argument("--out", type=Path)
    command.add_argument("--config", type=Path, help="Config JSON or selected.json from search")
    command.add_argument("--stage", choices=("cv", "search", "final", "ablations"), default="cv")
    command.add_argument("--execute", action="store_true", help="explicitly perform the requested fit")
    for name in ("predict-f", "predict-r"):
        command = commands.add_parser(name)
        command.add_argument("artifact", type=Path)
        command.add_argument("inputs", type=Path)
        command.add_argument("--out", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "import-r04":
            from .r04_transport import build_transport_snapshot
            result = build_transport_snapshot(args.manifest, args.out)
        elif args.command == "ingest":
            from .ingest import build_snapshot
            result = {"manifest": str(build_snapshot(args.manifest, args.out)),
                      "training_started": False}
        elif args.command in {"predict-f", "predict-r"}:
            if args.out.exists():
                raise DataError("Prediction output already exists; preserve the frozen result")
            payload = read_json(args.inputs)
            if args.command == "predict-f":
                from .f_training import FArtifact
                from .aggregation import mix_cross_sections, rate_from_flux
                model = FArtifact.load(args.artifact)
                predictions = model.predict(payload["conditions"])
                weights = payload.get("state_weights")
                result = {"predictions": predictions, "sigma_unit": "cm2/bit",
                          "model_derived": True, "training_started": False}
                sigma = [r["sigma_cm2_per_bit"] for r in predictions]
                if weights is not None and all(all(v is not None for v in row) for row in sigma):
                    result["mixed_sigma_cm2_per_bit"] = [mix_cross_sections(s, weights) for s in sigma]
                    result["rate_errors_per_bit_second"] = rate_from_flux(
                        sigma, weights, payload.get("integrated_flux_by_bin"))
            else:
                from .r_training import RArtifact
                result = {"predictions": RArtifact.load(args.artifact).predict_samples(payload["samples"]),
                          "training_started": False}
            write_json(args.out, result)
        else:
            from .pipeline import prepare, readiness, frozen_folds, cross_validate, run_search, fit_final
            snapshot = Snapshot.load(args.manifest)
            if args.command == "inspect":
                result = readiness(snapshot)
                if args.out:
                    if args.out.exists():
                        raise DataError("Inspect output already exists")
                    write_json(args.out, result)
            elif args.command == "prepare":
                result = prepare(snapshot, args.out)
            elif not args.execute:
                result = {**readiness(snapshot), "requested_stage": args.stage,
                          "message": "Dry preparation only. No optimizer or solver was started."}
            else:
                if not args.prepared or not args.out:
                    raise DataError("Execution requires --prepared and a new --out directory")
                split_path = args.prepared / "splits.json"
                frozen_folds(snapshot.view(snapshot.development_conditions), split_path)
                values = read_json(args.config) if args.config else {}
                config = Config.from_dict(values.get("config", values))
                if args.stage == "search":
                    result = run_search(snapshot, config, args.out, split_path=split_path)
                elif args.stage == "final":
                    result = fit_final(snapshot, config, args.out)
                elif args.stage == "ablations":
                    from .baselines import ablations
                    args.out.mkdir(parents=True, exist_ok=False)
                    result = ablations(snapshot, config, split_path=split_path,
                                       cache_dir=args.out / "cache")
                    write_json(args.out / "ablations.json", result)
                else:
                    args.out.mkdir(parents=True, exist_ok=False)
                    result = cross_validate(snapshot, config, cache_dir=args.out / "cache",
                                            split_path=split_path)
                    write_json(args.out / "development_cv.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (DataError, ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
