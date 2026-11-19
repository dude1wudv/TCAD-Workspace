# R50 Main Post-Training Audit

审计时间：2026-10-11（只读核验）。本文件只记录证据，不改变业务代码、账本、状态或任何求解输入。

## 结论

`restart-r2e` 的 `controller.stderr.log` 报错发生在 16 个剩余训练求解全部输出 `VERIFIED` 之后。16 行 stdout 对应固定 canonical train 前缀 `l035 proton` 的 16 个 bit 响应，最后一行是 `20261011T073430Z-v3-r50-main-l035-proton-a30-s202610414-b1-40085e22`，随后 controller 在 `run_remaining_training()` 的最终 reconciliation 检查处抛出：

```text
ValueError: Training reconciliation did not cover 64 canonical responses
```

这是控制器计数缺陷：`old_plan().planned_cases` 中 `stage == train` 只有 56 项；其余 8 个 pilot 响应不在该循环中，但最终代码仍要求 `len(completed) == 64`。因此该异常不能作为新的 solver 科学失败，也不能导致任何训练响应重跑。

## 账本独立计数

来源：`local_runtime/dram-see-v3/ledger.json`，SHA256 `fbb5d34d5249c2eb363565c9684d689aec9f5a0d2d6a9b206b27bccd43cb8486`。

- canonical 训练响应标签：64 行；其中 63 行 `VERIFIED`，1 行原始 `FAILED`。
- 原始失败标签：`v3-r50-main-l035-alpha-a30-s202610394-b1`，失败类别为 `ENGINEERING_EVIDENCE_INCOMPLETE`，保留原行不改。
- retry alias：`v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1`，`VERIFIED`，`retry_of` 精确指向原始失败标签，solver 成本 `585.68 s`。
- 采用 alias 后，逻辑 canonical training 响应为 64/64 VERIFIED；这不改变原始 FAILED 行，也不增加独立事件或响应槽位。
- canonical 原始行 solver 成本合计 `28369.87 s`（包含原失败行）；retry alias 另计 `585.68 s`。

独立计数脚本使用的 canonical 标签规则：

```text
^v3-r50-main-l(018|025|035|045)-(alpha|proton)-a(0|30)-s[0-9]+-b[01]$
```

## 归档完整性

逐行检查上述 64 个 canonical 行加 1 个 retry 行：

- `local_runtime/runs/<run_id>/`：65/65 目录存在，均有非空 `manifest.json`、`console.log`、`results.tar`，且 `results.tar` 可正常读取。
- `experiments/dram-see-v3/r50-main/data/tcad/<run_id>/` 或 `restart-r2e/data/tcad/<run_id>/`：64 个 `VERIFIED` 逻辑响应均有非空 `summary.json`、`device.csv`、`circuit.csv`、`circuit-raw.csv`。
- 原始 FAILED run 的归档仍保留在 `local_runtime/runs/20261011T031239Z-v3-r50-main-l035-alpha-a30-s202610394-b1-cf1ee732/`；其 `results.tar` SHA256 为 `20a2ed9655b556e7c6ff09622bf50aa492192903169e00a11a0ae01673f4d6b7`，与 `local_runtime/dram-see-v3/recoveries/20261011T0331Z-r50-main-r1/settlement-decision.json` 一致。
- retry run 的可审计归档为 `local_runtime/runs/20261011T044502Z-v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1-15d9f5f5/`，对应导出数据位于 `experiments/dram-see-v3/r50-main/restart-r2e/data/tcad/`。

## r2e 运行证据

- controller：`experiments/dram-see-v3/r50-main/restart-r2e/controller.py`，SHA256 `783afbdc8c6bdc6515c3cb5642afee2bb5b5af7f47cd664f6b779e4087ac67d7`。
- source manifest：`experiments/dram-see-v3/r50-main/restart-r2e/source-manifest.json`，SHA256 `bc5b24e806c43d536efdccb8a11f9fa092c1b30a3b8e800898766f78ecc7e5b0`。
- plan：`local_runtime/dram-see-v3/physical-revisions/r50-main-restart-r2e/plan.json`，SHA256 `a114556a58798435500889a07812734ee7d2ada302cef09d72d5b8a0f30992b7`。
- launch：`local_runtime/dram-see-v3/restart-launches/r2e/launch.json`。
- r2e stdout：16 行，全部 `state=VERIFIED`；SHA256 `9850487c862a693fe92e8c06e60a96356cdc9fa2c6e0f00e3df3e2b32e7f32d8`。
- r2e stderr：12 行 Python traceback；SHA256 `9066c2d8c38abf33e601f68548fecc75e771cb76bfbac322ffbe5a7ea06e82e5`。

代码顺序证据在 `controller.py:335-387`：每个 `ORIG.C.record()` 完成并返回 VERIFIED 后追加 `completed`，循环结束才执行错误的 `len(completed) != 64` 检查；因此 traceback 的时序位于所有 16 个 solver 输出之后。

## 允许继续 prediction 的前置条件

可以安全进入 prediction 的数据前置条件已经满足：64 个逻辑 canonical training 响应均有 VERIFIED 结果，retry alias 的 lineage 和原始 FAILED 行均保留，65 次 attempt 的原始归档均可读取。继续前必须由新的后续控制器/冻结计划完成以下审计：

1. 冻结不可变 alias map：canonical failed tag → retry tag/run，包含 `retry_of`、同 event/bit/seed/物理合同、`supersedes_failed=false`。
2. 写入独立 prediction acceptance，绑定本审计、当前 global ledger SHA、r2e source/plan SHA 和 alias-map SHA；不得把 r2e 的错误 `status.json`（仍为 `RETRY_SUBMITTING`）当作完成依据。
3. 重新审计 64 canonical response IDs、32 independent events、128 response slots 与实际数据路径；prediction 输入只能来自真实归档，不能使用 synthetic fixture。
4. 在任何 test solver 提交前，先实际生成并冻结四模型和 64 个逐位 prediction，记录生成时间、ledger SHA、source manifest SHA 和输入哈希；test64 必须检查 prediction freeze 的时间先后。
5. 恢复真实 prediction freeze 检查；r2e 中的 `ORIG.C.check_prediction_freeze = lambda: None` 仅是训练段临时旁路，不能沿用到 test/oxide/boundary。

## 未验证范围

- 未运行 prediction、test64、oxide、boundary、native GUI 或最终报告/PPT。
- 未修改 r2e controller 的 reconciliation 缺陷；活动源码和账本保持原样。
- 未独立复核每个物理量的科学阈值，只检查 ledger 状态、归档存在性和 lineage/时序证据。
- 当前 `physical-revisions/r50-main-restart-r2e/status.json` 的 `RETRY_SUBMITTING`/`retry_row=RUNNING` 语义陈旧，不能单独用于判断训练完成。
