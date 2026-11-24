"""Read-only manuscript checks; optionally write a QA result in local_runtime.

This checks document structure, sources, citations and compiled text. It never
imports a solver, reads connection settings, or changes an experiment artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOCS = ("course-report", "research-paper")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expand(path: Path, visited: set[Path] | None = None) -> str:
    visited = set() if visited is None else visited
    path = path.resolve()
    if path in visited:
        return ""
    if not path.is_relative_to(HERE):
        raise ValueError(f"Document include escaped report directory: {path}")
    visited.add(path)
    text = path.read_text(encoding="utf-8-sig")
    def include(match: re.Match) -> str:
        name = match.group(1)
        child = HERE / name
        if not child.suffix:
            child = child.with_suffix(".tex")
        return "\n" + expand(child, visited)
    return re.sub(r"\\(?:input|include)\{([^}]+)\}", include, text)


def check_document(name: str) -> dict:
    visited: set[Path] = set()
    source = expand(HERE / f"{name}.tex", visited)
    source = re.sub(r"(?m)(?<!\\)%.*$", "", source)
    labels = re.findall(r"\\label\{([^}]+)\}", source)
    refs = re.findall(r"\\(?:ref|eqref|pageref|autoref)\{([^}]+)\}", source)
    cites = set()
    for group in re.findall(r"\\cite(?:p|t)?(?:\[[^]]*\])*\{([^}]+)\}", source):
        cites.update(x.strip() for x in group.split(","))
    bibliography = (HERE / "references.bib").read_text(encoding="utf-8")
    bibkeys = set(re.findall(r"@\w+\s*\{\s*([^,]+),", bibliography))
    graphics = re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", source)
    missing_figures = []
    for graphic in graphics:
        paths = [HERE / graphic, HERE / "figures" / graphic]
        if not any(p.is_file() for p in paths):
            missing_figures.append(graphic)
    tex_log = ROOT / "local_runtime/report-final-20261011/build" / f"{name}.log"
    log = tex_log.read_text(encoding="utf-8", errors="replace") if tex_log.exists() else ""
    pdf = HERE / f"{name}.pdf"
    built_pdf = tex_log.with_suffix(".pdf")
    all_inputs = set(visited) | {HERE / "references.bib"}
    for graphic in graphics:
        all_inputs.update(p for p in (HERE / graphic, HERE / "figures" / graphic) if p.is_file())
    newer_inputs = sorted(p.relative_to(HERE).as_posix() for p in all_inputs
                          if pdf.is_file() and p.stat().st_mtime_ns > pdf.stat().st_mtime_ns)
    result = {
        "document": name,
        "included_files": sorted(p.relative_to(HERE).as_posix() for p in visited),
        "chinese_characters_in_expanded_source": len(re.findall(r"[\u4e00-\u9fff]", source)),
        "sections": re.findall(r"\\section\*?\{([^}]+)\}", source),
        "citations": sorted(cites),
        "missing_citations": sorted(cites - bibkeys),
        "uncited_bibliography_entries_not_emitted_by_bibtex": sorted(bibkeys - cites),
        "undefined_labels": sorted(set(refs) - set(labels)),
        "duplicate_labels": sorted({x for x in labels if labels.count(x) > 1}),
        "missing_figures": missing_figures,
        "unfinished_authoring_markers": re.findall(r"\b(?:TODO|FIXME|XXX)\b|\[VERIFY\]", source),
        "pdf_exists": pdf.is_file(),
        "pdf_sha256": sha(pdf) if pdf.is_file() else None,
        "inputs_newer_than_pdf": newer_inputs,
        "copied_pdf_matches_build": (pdf.is_file() and built_pdf.is_file()
                                     and sha(pdf) == sha(built_pdf)),
        "tex_log_exists": tex_log.exists(),
        "overfull_boxes": re.findall(r"Overfull[^\n]+", log),
        "missing_glyphs": re.findall(r"Missing character[^\n]+", log),
        "unresolved_tex_warnings": [line for line in log.splitlines() if
            ("undefined" in line.lower() or "rerun" in line.lower()) and "Warning" in line],
    }
    if pdf.is_file():
        try:
            import pymupdf as fitz
        except ImportError:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf))
            texts = [page.extract_text() or "" for page in reader.pages]
        else:
            with fitz.open(pdf) as document:
                texts = [page.get_text() for page in document]
        result["pages"] = len(texts)
        result["page_text_characters"] = [len(t.strip()) for t in texts]
        result["replacement_character_count"] = sum(t.count("\ufffd") for t in texts)
        result["pdf_stage_scope_present"] = any("阶段" in t for t in texts[:2])
    blocking_keys = ("missing_citations", "undefined_labels", "duplicate_labels",
                     "missing_figures", "unfinished_authoring_markers", "missing_glyphs",
                     "unresolved_tex_warnings", "overfull_boxes", "inputs_newer_than_pdf")
    result["automated_checks_pass"] = (result["pdf_exists"] and result["tex_log_exists"]
                                       and result["copied_pdf_matches_build"]
                                       and not any(result[k] for k in blocking_keys))
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"schema": "dram-report-document-qa-v1",
              "documents": [check_document(name) for name in DOCS],
              "visual_review": "separate manual inspection required",
              "solver_rerun": False}
    if args.output:
        target = args.output.resolve()
        allowed = (ROOT / "local_runtime/report-final-20261011").resolve()
        if not target.is_relative_to(allowed):
            raise ValueError("QA output must stay in the dedicated local_runtime directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not all(d["automated_checks_pass"] for d in result["documents"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
