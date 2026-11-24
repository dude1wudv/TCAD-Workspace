"""Check the frozen writing package, then create its manifest and a ZIP.

This script performs no simulation or remote operation. Existing archives are
never overwritten. It does not refresh source snapshots or the live ledger.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-name", default="dram-report-writing-20261011.zip")
    args = parser.parse_args()
    if Path(args.archive_name).name != args.archive_name or not args.archive_name.endswith(".zip"):
        raise ValueError("Archive name must be a plain ZIP filename")
    archive = HERE.parent / args.archive_name
    if archive.exists():
        raise FileExistsError(f"Refusing to overwrite existing archive: {archive}")
    sources = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    source_results = []
    for row in sources["source_records"]:
        copy_path = (ROOT / row["copy_path"]).resolve()
        if not copy_path.is_relative_to(HERE):
            raise ValueError("Source copy escaped the writing package")
        if sha(copy_path) != row["sha256"]:
            raise ValueError(f"Source copy hash mismatch: {row['copy_path']}")
        source_results.append({"source_path": row["source_path"], "copy_sha256_verified": True})
    for row in sources["outputs"]:
        target = (HERE / row["path"]).resolve()
        if not target.is_relative_to(HERE) or sha(target) != row["sha256"]:
            raise ValueError(f"Evidence output hash mismatch: {row['path']}")
    if sha(HERE / "prepare_evidence.py") != sources["generator"]["sha256"]:
        raise ValueError("Evidence generator changed since its recorded rebuild")
    document_qa = json.loads((HERE / "qa/document-qa.json").read_text(encoding="utf-8-sig"))
    visual_qa = json.loads((HERE / "qa/visual-review.json").read_text(encoding="utf-8-sig"))
    for row in document_qa["documents"]:
        if not row["automated_checks_pass"] or sha(HERE / (row["document"] + ".pdf")) != row["pdf_sha256"]:
            raise ValueError("PDF changed or automated QA failed")
        if row["pages"] != visual_qa["documents"][row["document"]]["page_count"]:
            raise ValueError("Page count differs from the visual review")
    if visual_qa["result"] != "passed":
        raise ValueError("Visual review is not complete")
    protected = []
    for row in sources["source_records"]:
        if row["source_path"] in ("reports/paper/report.tex", "reports/paper/report.pdf"):
            same = sha(ROOT / row["source_path"]) == row["sha256"]
            if not same:
                raise ValueError("Earlier manuscript differs from its captured source")
            protected.append({"path": row["source_path"], "sha256": row["sha256"], "unchanged": same})
    files = []
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and path.name != "delivery-manifest.json" and "__pycache__" not in path.parts:
            files.append({"path": path.relative_to(HERE).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    manifest = {"schema": "dram-stage-writing-delivery-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
                "stage_only": True, "solver_rerun": False, "source_count": len(source_results),
                "source_copies_verified": source_results, "evidence_outputs_verified": len(sources["outputs"]),
                "protected_earlier_manuscripts": protected, "documents": document_qa["documents"],
                "visual_review": visual_qa, "manifest_excludes_itself": True, "files": files}
    (HERE / "delivery-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=9) as output:
        for row in files:
            output.write(HERE / row["path"], arcname="final/" + row["path"])
        output.write(HERE / "delivery-manifest.json", arcname="final/delivery-manifest.json")
    with ZipFile(archive) as output:
        if output.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
    digest = sha(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "sha256": digest,
                      "files": len(files) + 1, "source_copies_verified": len(source_results),
                      "evidence_outputs_verified": len(sources["outputs"]), "zip_crc_check": "passed"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
