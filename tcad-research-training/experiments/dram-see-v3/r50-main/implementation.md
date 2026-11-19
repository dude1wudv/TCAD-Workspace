# R50-main r1 首段实现

本实现只覆盖 `references → pilot（含源隔离）→ numerical_preregistered → train`。固定 92 个串行 TCAD 调用，成功终态为 `TRAINING_FINISHED_PENDING_PREDICTION`。完整方案仍为 64 个独立事件、128 个位响应；本段只有 32 个训练事件的 64 个位响应。后续测试输入生成、实际预测冻结、测试、氧化层、边界、报告与原生图尚未实现，不因本段完成而标为完成。

`build_case.py`、`audit.py`、`metrics.py` 是原 v3 的显式独立拷贝，准确差异见对应 `.py.diff`，原/新文件哈希见 `derivation.json`。唯一物理改变是信号与物理参考两侧 `Rpre` 导通值 100→50 Ω；关断、电容、初态、物理模型、时序、粒子、阈值与审计容差保留。schema 为 `dram-see-v3-r50-main`，`physical_revision=r50-main-r1`，合同中 `physical_revision_probe_only=false`。原 100 Ω、旧版兼容桥与 probe 归档一律不能作为本版本的 parent/control/neutral；12 个单支路参考和 8 个物理双支路全部重建。`numerical.py` 只复制原始纯比较函数，不加载旧 selector 或旧数值证据。

控制器以原字节加载旧 `run.py`、`common.py` 和 `scripts/tcad.py`。显式适配仅将 `run.module` 指向本目录 builder/audit，将 design 指向本冻结设计，给每个新增全局运行行添加版本身份，在 `save` 前保护原全部行、失败历史和 `stages`，在原 preflight 前后检查授权截止。真正准备输入、runner 调用、归档审计及全局成本记账仍执行原 `run.prepare/run.record`。所有求解沿用同一个 `controller.lock`、VM、许可证及单线程 runner。任何失败、未知或未结尝试禁止重发。

## 激活验收与冻结

只有三项 probe 实际审计通过后，主代理才可独立验收并写入：

`local_runtime/dram-see-v3/physical-revisions/r50-main-r1-acceptance.json`

必须字段如下；这里是字段说明，不是已发生的验收结果：

```json
{
  "schema": "dram-see-v3-r50-main-activation-acceptance",
  "approved": true,
  "design_sha256": "实际冻结 design.json 的 SHA256",
  "probe_result_sha256": "实际 probe result.json 的 SHA256",
  "probe_run_archives": {
    "control": {"run_id": "实际 run ID", "archive_sha256": "实际 results.tar SHA256"},
    "neutral": {"run_id": "实际 run ID", "archive_sha256": "实际 results.tar SHA256"},
    "event": {"run_id": "实际 run ID", "archive_sha256": "实际 results.tar SHA256"}
  },
  "source_manifest_sha256": "source-manifest.json 原始文件字节 SHA256",
  "accepted_utc": "实际验收 UTC 时间",
  "evidence": "非空独立验收证据说明或路径"
}
```

`source-manifest.json` 固定列出本段全部实际源码依赖、显式推导来源和 plan/design。控制器核对固定列表和每份哈希，不扫描目录；后续新增模块不会破坏本段冻结，但不得修改任何已列出文件。它的哈希是文件原始字节哈希，不是 canonical JSON 哈希。验收字段绑定该哈希。运行计划自身使用 `plan-sha256.json` 内的 `sha256`，同样为完整 `plan.json` 原始字节哈希。

主代理通过独立源码验收后才执行：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/controller.py freeze --label r1
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/controller.py execute --label r1
```

`freeze` 共用原锁，读取三 probe 原档并重新审计、检查 root 验收、原 43 行和 probe 行、固定 32 个训练 Geant4 的 96 份原文件及唯一全局预算；只写不可覆盖计划、来源快照和原 ledger 快照，不准备输入或提交。`execute` 只接受已冻结计划。每个依赖输入在自己的 control 通过后才准备并单独冻结，绑定总计划哈希及实际输入哈希。已 VERIFIED 的本计划项先原档复审，再跳过；FAILED/未知不重发。仅 COLLECTED 不视为科研通过。

运行目录固定为：

`local_runtime/dram-see-v3/physical-revisions/r50-main-r1/`

其中 `status.json` 保存 `controller_pid`、`controller_parent_pid`、`controller_started_utc`、`current_case`、`current_stage`、状态/错误和完整 128 个计划槽位。`stage-index.json` 和 `stages/*.json` 仅引用唯一 run ID 和派生证据，不计费；全局 `local_runtime/dram-see-v3/ledger.json` 是唯一成本事实来源。`source-snapshot/`、`case-freezes/`、`ledger-before.json` 保留来源。匹配指标和物理/数值比较位于本目录 `data/`，不可覆盖已完成证据。原 `continuation-state` 和原 `stages` 不写入。

每个新提交前检查授权早于 `2026-10-11T04:37:00Z`、原 preflight、全局累计加预留不超过 86400 s；普通/细化/物理分别 600/900/1000 s。实际任一本段运行超过自己预留时，在下一项前停止，要求安全边界的新版本估计审核。预算不足或期限已到时保留完整计划分母，不跳项，不终止在途正常求解。

物理参考逐项核对两侧 BL、D 和所有阈值。预登记两个细化完整匹配自身 control/neutral，连续容差失败阻止训练扩大；分类跨界保留数值不确定而不替换阈值。单纯 critical 不阻止连续量。全局行如显式标记连续数值失败或未知，也禁止进入依赖训练。实际测试泄漏防护读取已存 `inputs.tar` 的真实参数 metadata，按 schema/revision/粒子/尺寸判定，不靠旧 tag 字符串。

## 开发验证和边界

`local_runtime/dram-see-v3/r50-main-dev/self_check.py` 是非物理 fixture：20 项无粒子输入构建与实际 deck 单/双 Rpre 唯一差异；步长/网格/氧化层及源字节；拒绝旧模型、probe 身份、旧 parent；原审计与数值比较函数 AST 不变；92 项固定顺序、失败停止、预算/截止/旧账保护和显式连续失败拒绝。全链控制流 fixture 的审计/runner/输入操作均为 stub，不代表真实求解或科研通过。

最新开发验证见私有 `self-check-03.log`：10 项通过。`self-check-02.log` 保留一次 mock 工具中过宽替换 `read()` 造成的测试失败，已只修正 fixture。没有真实 freeze/execute、SSH、求解、GUI、安装或 Git 操作。源码须经主代理与独立 worker 验收后才能激活。
