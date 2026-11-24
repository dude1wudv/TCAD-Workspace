"""Read-only document-package verification. Never imports a simulation controller.

Run with the existing bundled Python. JSON is emitted on stdout; this program
does not create or update files and does not regenerate any report or slide.
"""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
import zipfile

from pypdf import PdfReader
import pdfplumber

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def check(condition, reason):
    if not condition:
        raise AssertionError(reason)


def main():
    result = {"schema": "dram-see-v3-final-r4-package-verification", "utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Document and slide fidelity, source hashes, preserved snapshot and rendering bindings; no new scientific simulation or native PowerPoint execution.",
              "new_solver_calls": 0, "writes": 0}
    sources = read(HERE / "sources.json")["sources"]
    for name, expected in sources.items():
        check(digest(ROOT / name) == expected, f"Changed source: {name}")
    result["bound_source_hashes_checked"] = len(sources)
    snapshot = HERE / "data/snapshot"
    binding = read(HERE / "data/snapshot-binding.json")
    check(digest(snapshot / "snapshot-manifest.json") == binding["source_manifest_sha256"], "Snapshot manifest")
    sm = read(snapshot / "snapshot-manifest.json")
    for name, expected in sm["files_sha256"].items():
        check(digest(snapshot / name) == expected, f"Snapshot byte change: {name}")
    result["snapshot_outputs_checked"] = len(sm["files_sha256"])
    summary = read(snapshot / "summary.json")
    check(summary["synthetic_fixture"] is False, "Synthetic fixture forbidden")
    check(summary["planned_independent_events"] == 64 and summary["measured_main_responses"] == 128, "Scientific denominator")
    check(len(summary["responses"]) == 128 and len(summary["aliases"]) == 4, "Main responses or aliases")
    check(digest(snapshot / "original-r4-prediction-scores.json") == digest(snapshot / "final-numerical-prediction-scores.json"), "Reported score equality no longer holds")
    result["science_snapshot"] = {"events": 64, "responses": 128, "aliases": 4, "score_files_preserved_separately": True}

    pdf_binding = read(HERE / "qa/pdf-r3/render-manifest.json")
    result["pdfs"] = []
    for item in pdf_binding["documents"]:
        pdf = ROOT / item["pdf"]
        check(digest(pdf) == item["pdf_sha256"], f"PDF changed: {pdf.name}")
        reader = PdfReader(pdf)
        check(len(reader.pages) == item["pages"] == len(item["images"]), "Page counts")
        check(item["actual_exit_code"] == 0, "PDF render did not succeed")
        for image, expected in item["images"].items():
            check(digest(HERE / image) == expected, f"PDF render changed: {image}")
        # pdfminer/pdfplumber resolves the embedded Fandol CID fonts; pypdf
        # correctly counts pages but does not map their CJK CID text here.
        with pdfplumber.open(pdf) as document:
            extracted = "\n".join(page.extract_text() or "" for page in document.pages)
        # PDF glyph positioning may insert spaces inside an English word.
        normalized = "".join(extracted.split())
        check("96" in normalized and "128" in normalized and "FAILED" in normalized, "PDF content markers")
        check("??" not in extracted, "Unresolved PDF citation or reference")
        check(len(re.findall(r"[\u4e00-\u9fff]", extracted)) > 4000, "Chinese text extraction")
        result["pdfs"].append({"file": pdf.name, "sha256": digest(pdf), "pages": len(reader.pages),
                               "extracted_characters": len(extracted), "chinese_characters": len(re.findall(r"[\u4e00-\u9fff]", extracted))})
    commands = read(HERE / "qa/tex-r3/commands.json")
    check(len(commands) == 8 and all(c["exit_code"] == 0 for c in commands), "TeX build exits")
    for name in ("course-report", "research-paper"):
        log = (HERE / f"qa/tex-r3/{name}-pass-4.log").read_text(encoding="utf-8", errors="replace")
        check(not re.search(r"Overfull|undefined|LaTeX Warning", log), f"Final-pass warnings: {name}")
    result["tex_commands_exit_codes"] = [c["exit_code"] for c in commands]

    ppt_binding = read(HERE / "qa/ppt-r4/render-manifest.json")
    ppt = ROOT / ppt_binding["pptx"]
    check(digest(ppt) == ppt_binding["pptx_sha256"], "PPT changed")
    check(digest(ROOT / ppt_binding["build_script"]) == ppt_binding["build_script_sha256"], "PPT authoring source changed")
    for item in ppt_binding["images"]:
        check(digest(HERE / item["image"]) == item["sha256"], "PPT render changed")
    receipt = read(HERE / "qa/ppt-r4/validation.json")
    check(receipt["finalSha256"] == digest(ppt), "Finalizer source binding")
    check(receipt["packageIntegrity"]["status"] == "pass" and receipt["presentationLayout"]["findingCount"] == 0, "PPT validation")
    check(receipt["firstPartyImport"]["passed"] and receipt["nativeQuantitativeCharts"]["report"]["passed"], "PPT import/chart validation")

    def text_nodes(root):
        return "".join(t.text or "" for t in root.findall(".//a:t", NS))

    with zipfile.ZipFile(ppt) as z:
        names = z.namelist()
        slide_names = [n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        note_names = [n for n in names if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)]
        chart_names = [n for n in names if re.fullmatch(r"ppt/slides/charts/chart\d+\.xml", n)]
        workbooks = [n for n in names if n.startswith("ppt/embeddings/") and n.endswith(".xlsx")]
        check(len(slide_names) == 16 and len(note_names) == 16 and len(chart_names) == 3 and len(workbooks) == 3, "PPT component counts")
        for name in note_names:
            check(binding["source_manifest_sha256"] in text_nodes(ET.fromstring(z.read(name))), "Missing slide source note")
        tables = {}
        for i in range(1, 17):
            root = ET.fromstring(z.read(f"ppt/slides/slide{i}.xml"))
            for tbl in root.findall(".//a:tbl", NS):
                check(i not in tables, "Unexpected second table")
                tables[i] = [[text_nodes(cell) for cell in row.findall("a:tc", NS)] for row in tbl.findall("a:tr", NS)]
        check(sorted(tables) == [4, 8, 10, 11, 13, 16], "Native table owners")
        matrix = tables[4]
        check([int(row[2]) for row in matrix[1:]] == [32, 16, 16, 64], "Displayed event allocation")
        check([int(row[3]) for row in matrix[1:]] == [64, 32, 32, 128], "Displayed response allocation")
        check(sum(int(row[2]) for row in matrix[1:4]) == int(matrix[4][2]), "Event sum")
        check(sum(int(row[3]) for row in matrix[1:4]) == int(matrix[4][3]), "Response sum")
        score = summary["final_numerical_prediction_scores"]["scores"]

        def find(split, bit, target, model="ridge"):
            return next(x for x in score if (x["split"], x["stored_bit"], x["target"], x["model"]) == (split, bit, target, model))

        for row, split in zip(tables[8][1:], ["holdout", "extrapolation"]):
            check(row[1:] == [f'{find(split, b, "deltaQ_fC")["RMSE"]:.4f}' for b in (0, 1)], "Slide 8 score table")
        ridge = [x for x in score if x["model"] == "ridge"]
        check(len(tables[13][1:]) == len(ridge) == 8, "Slide 13 ridge rows")
        for row, item in zip(tables[13][1:], ridge):
            check(row[0] == ("留出" if item["split"] == "holdout" else "外推") and row[1] == f'b{item["stored_bit"]}', "Ridge labels")
            check(row[3:] == [str(item["valid_n"])] + [f'{item[k]:.4f}' for k in ("MAE", "RMSE", "max_absolute_error")], "Ridge numeric cells")
        for row, item in zip(tables[10][1:], summary["numerical_boundary"]["comparisons"]):
            check(row[0] == f'{item["event"]["seed"]} / b{item["stored_bit"]}', "Boundary identity")
            check(row[2] == f'{max(abs(v) for v in item["differences_V"].values()) * 1000:.6f}', "Boundary numeric cell")
            check(row[3] == ("通过" if item["continuous_passed"] else "失败"), "Boundary pass cell")
            check(row[4] == ("稳定" if item["classification_stable"] else "5 mV 跨界"), "Boundary crossing cell")
        check(tables[11][4][1] == f'{summary["budget"]["accounted_solver_s"]:.2f} s ≈ {summary["budget"]["accounted_solver_s"] / 3600:.4f} h', "Budget display")
        classes = ["correct", "criterion_error", "critical", "numerically_uncertain"]
        counts = [Counter(r["effective_classification"][t] for r in summary["responses"]) for t in ("2.5", "5.0", "10.0")]
        expected_charts = [
            [[c[k] for c in counts] for k in classes],
            [[find(a, b, "deltaM_mV", model)["RMSE"] for a, b in (("holdout", 0), ("holdout", 1), ("extrapolation", 0), ("extrapolation", 1))] for model in ("training_mean", "ridge")],
            [[0 if n == 5 else next(x["differences_from_5nm"]["deltaM_V"] * 1000 for x in summary["oxide"]["responses"] if x["event"]["particle"] == particle and x["stored_bit"] == bit and x["oxide_nm"] == n) for n in (4, 5, 6)] for particle, bit in (("alpha", 0), ("alpha", 1), ("proton", 0), ("proton", 1))]
        ]
        for i, expected in enumerate(expected_charts, 1):
            root = ET.fromstring(z.read(f"ppt/slides/charts/chart{i}.xml"))
            actual = [[float(v.text) for v in ser.findall("c:val//c:pt/c:v", NS)] for ser in root.findall(".//c:ser", NS)]
            rounded = [[float(f"{v:.6f}") for v in row] for row in expected]
            check(actual == rounded, f"Chart {i} differs from snapshot at display precision")
        media_hashes = {sha256(z.read(n)).hexdigest() for n in names if n.startswith("ppt/media/")}
        for name in ("native-physical-window.png", "native-event-window.png"):
            check(digest(HERE / "figures" / name) in media_hashes, "Native screenshot bytes not preserved in PPT")
    result["ppt"] = {"file": ppt.name, "sha256": digest(ppt), "slides": 16, "notes": 16, "native_tables": 6,
                     "native_charts": 3, "embedded_xlsx": 3, "source_numeric_points_checked": 32,
                     "editable_chart_precision_decimals": 6, "source_full_precision_unchanged": True,
                     "table_checks": ["matrix column sums", "ridge RMSE", "all ridge error rows", "all boundary rows", "total cost"],
                     "native_screenshot_bytes_preserved": 2, "native_powerpoint_open_verified": False}
    expected_reviews = {"root-pdf-visual-review.json": "a3ca00844a92ab2a51547e7230a698afe253237d097feaec77ad09ee47693bc6",
                        "root-ppt-visual-review.json": "5830c39ff1d8e281998e405e60d991602bd4cee0330a58f9ff70f3ffaf3f8f37"}
    for name, expected in expected_reviews.items():
        check(digest(HERE / "qa" / name) == expected, "Root visual review receipt changed")
    result["root_visual_receipts_checked"] = len(expected_reviews)
    link_count = 0
    deferred_generated_links = []
    for md in [HERE / "README.md", HERE / "QA.md", *(HERE / "materials").glob("*.md")]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", md.read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "#")):
                continue
            target = target.split("#", 1)[0]
            # These two outputs depend on this initial verification. The final
            # verification after sealing checks them with no deferral.
            resolved = (md.parent / target).resolve()
            if resolved in (HERE / "delivery-manifest.json", HERE / "qa/package-verification.json") and not resolved.exists():
                deferred_generated_links.append(resolved.relative_to(HERE).as_posix())
                continue
            check(resolved.exists(), f"Broken document link: {md.name}: {target}")
            link_count += 1
    result["local_markdown_links_checked"] = link_count
    result["deferred_self_generated_links_before_sealing"] = sorted(set(deferred_generated_links))
    if (HERE / "delivery-manifest.json").exists():
        manifest = read(HERE / "delivery-manifest.json")
        for name, expected in manifest["files_sha256"].items():
            check(digest(HERE / name) == expected, f"Final package changed: {name}")
        result["delivery_manifest_files_checked"] = len(manifest["files_sha256"])
    result["state"] = "PASSED"
    return result


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
