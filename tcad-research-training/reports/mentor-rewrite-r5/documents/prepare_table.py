"""Format accepted score cells; no fitting, recomputation, or source edits."""
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
score = json.loads((HERE.parent / "assets/data/snapshot/final-numerical-prediction-scores.json").read_text(encoding="utf-8"))["scores"]
rows = []
for item in score:
    if item["model"] != "ridge":
        continue
    baseline = next(x for x in score if x["model"] == "training_mean" and all(x[k] == item[k] for k in ("split", "stored_bit", "target")))
    label = "留出" if item["split"] == "holdout" else "外推"
    target = r"$\Delta Q$/fC" if item["target"] == "deltaQ_fC" else r"$\Delta M$/mV"
    assert item["valid_n"] == 16 and baseline["valid_n"] == 16
    rows.append(" & ".join([label, str(item["stored_bit"]), target] + [f"{x:.4f}" for x in (baseline["RMSE"], item["MAE"], item["RMSE"], item["max_absolute_error"])]) + r"\\")
tex = r"""\begin{tabular}{lllr rrr}
\toprule
集合 & 位 & 目标 & 基准RMSE & 岭回归MAE & RMSE & 最大\\
\midrule
""" + "\n".join(rows) + "\n" + r"\bottomrule\end{tabular}" + "\n"
(HERE / "score-table.tex").write_text(tex, encoding="utf-8")
print("Eight fixed score rows formatted; no source or model modified.")
