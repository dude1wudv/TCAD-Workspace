"""Build and render the two rewritten documents using existing local tools.

Writes only inside this documents directory. No simulation modules are loaded.
"""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ASSETS = HERE.parent / "assets"
XELATEX = Path(r"C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe")
BIBTEX = XELATEX.with_name("bibtex.exe")
POPLER = Path(r"C:\Users\sun\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe")


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    args = parser.parse_args()
    if not args.tag.replace("-", "").isalnum():
        raise ValueError("Simple unique build tag required")
    out = HERE / "qa" / args.tag
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["TEXINPUTS"] = (REPO / "local_runtime/report-writing-20261010/tex-deps/pgf/base/tex").as_posix() + "//;"
    # No parent recursive TeX search path: it can shadow system color.cfg.
    env.pop("BIBINPUTS", None)
    commands = []

    def run(argv, log):
        started = datetime.now(timezone.utc).isoformat()
        with log.open("wb") as stream:
            process = subprocess.run([str(x) for x in argv], cwd=HERE, env=env, stdout=stream, stderr=subprocess.STDOUT)
        commands.append({"argv": [str(x) for x in argv], "cwd": str(HERE),
                         "TEXINPUTS": env["TEXINPUTS"], "started_utc": started,
                         "finished_utc": datetime.now(timezone.utc).isoformat(),
                         "actual_exit_code": process.returncode, "log": log.relative_to(HERE).as_posix()})
        (out / "commands.json").write_text(json.dumps(commands, ensure_ascii=False, indent=2), encoding="utf-8")
        if process.returncode:
            raise RuntimeError(f"Command failed ({process.returncode}): {log}")

    for name in ("course-report", "research-paper"):
        for index in range(1, 5):
            if index == 2:
                argv = [BIBTEX, out / name]
            else:
                argv = [XELATEX, "--disable-installer", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                        f"-output-directory={out}", HERE / f"{name}.tex"]
            run(argv, out / f"{name}-pass-{index}.log")
    documents = []
    for name in ("course-report", "research-paper"):
        final = HERE / f"{name}.pdf"
        shutil.copyfile(out / f"{name}.pdf", final)
        renders = out / name
        renders.mkdir()
        run([POPLER, "-png", "-r", "144", final, renders / "page"], out / f"{name}-render.log")
        pages = len(PdfReader(final).pages)
        images = {p.relative_to(HERE).as_posix(): digest(p) for p in sorted(renders.glob("page-*.png"))}
        assert len(images) == pages
        documents.append({"pdf": final.name, "sha256": digest(final), "pages": pages, "images": images})
    source = [*HERE.glob("*.tex"), HERE / "build_documents.py", ASSETS / "references.bib"]
    source += list((ASSETS / "tables").glob("*.tex"))
    source += list((ASSETS / "figures").glob("*.png")) + list((ASSETS / "figures").glob("*.pdf"))
    (out / "render-manifest.json").write_text(json.dumps({
        "schema": "dram-see-mentor-rewrite-document-render", "utc": datetime.now(timezone.utc).isoformat(),
        "documents": documents, "renderer": "Poppler pdftoppm", "dpi": 144,
        "commands": "commands.json", "source_sha256": {os.path.relpath(p, HERE).replace("\\", "/"): digest(p) for p in source},
        "new_science_runs": 0, "visual_review": "PENDING"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"build": str(out), "documents": [{k: v for k, v in d.items() if k != "images"} for d in documents]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
