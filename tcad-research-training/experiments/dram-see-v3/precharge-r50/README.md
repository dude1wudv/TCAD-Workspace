# 50 Ω 独立电路修订探针

此目录是获准三项探针的独立实现，不改变原100 Ω v3、原128槽位、FAILED或训练。唯一物理变化为预充导通电阻100→50 Ω；原器件、几何、源、时序、电容、10 µV预充门槛和全部其他审计容差保留。`schema=dram-see-v3-precharge-r50`、`physical_revision=r50-probe-v1`，完整matching/model均显式记录50 Ω与新的CIRCUIT。结果始终 `physical_revision_probe_only=true`，不能进入原训练/评分。

## 实现与差异

- `build_case.py`：独立复制和显式适配；仅允许L=0.18 µm、5 nm、bit0/neutral、step=mesh=1，以及指定seed202610303事件。旧100 Ω、legacy、其他位/尺寸和physical双支路均拒绝。事件必须从新R50、完整通过原门槛的control保存点续算。
- `audit.py`：独立新schema审计；原工程完成、完整输入、初始化、预充、4 ns终点、源积分、KCL/BE、四端闭合仍执行。无旧schema桥接。通过状态为 `R50_NUMERICAL_CONTRACT_PASSED`，与原v3身份分离。
- `metrics.py`：只接收本修订的完整审计bundle；同样使用完整条件和实际网格匹配、有符号ΔQ及原三个阈值。
- `inspection.py`：原组件检查的显式R50适配；保持raw_audit_state与diagnostic/probe身份分离。控制器只导出完整通过数据或精确已收集的预充单项失败诊断。
- `controller.py`：在隔离加载的原run模块上显式映射R50 builder/audit，复用原prepare/record、真实runner、锁、preflight和总ledger/预算。save适配器只给新探针行加明确身份，并验证全部旧行/stages/失败前缀不变；preflight适配器在前后检查提交期限。

`derivation.json` 绑定被复制原源码、派生源码及各 `.diff` 的SHA-256。`.diff` 是精确unified diff，不能把新deck称为旧100 Ω契约通过。复现派生过程的开发脚本位于 `local_runtime/dram-see-v3/r50-dev/derive_modules.py`；正式冻结之后不得执行该开发脚本覆盖源码。

## 控制器入口

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/precharge-r50/controller.py freeze --label r1
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/precharge-r50/controller.py execute --label r1
```

开发期间未调用这两个入口。主代理先验收独立验证结果再冻结/调度。

固定顺序和新tag：`v3-r50-probe-r1-control` → `v3-r50-probe-r1-neutral` → `v3-r50-probe-r1-event`。每项最多提交一次；所有失败和未结状态均停止，不存在自动重试路径。已VERIFIED项只能核对输入/来源、重审并跳过。控制失败或中性失败不提交事件；控制失败还保守停止整个剩余批次。

授权来源为 `local_runtime/dram-see-v3/autonomy-authorization.json` 及原提案，绑定原43行ledger快照、原失败事件Geant4三文件字节、原失败/control/neutral归档、设计、全部源代码和差异证据。最大3次新求解、每次900 s预留、本探针2700 s及原总86400 s双检查。提交前按UTC检查 `[2026-10-10T16:37:00Z, 2026-10-11T04:37:00Z)`；到期不终止正常求解，只禁止新提交。

计划/状态目录：`local_runtime/dram-see-v3/physical-revisions/precharge-r50-r1/`。包含 `plan.json`、`plan-sha256.json`（`{"sha256": ...}`）、`source-snapshot/`、`case-freezes/`、`audits/`、`status.json`；成功结束生成 `result.json` 和三侧完整原始预充CSV。status包含controller_pid、controller_parent_pid、controller_started_utc、current_case、state、reason与实际ledger状态。它不覆盖主continuation-state或原训练stage。

若最后事件科学审计失败，仍保持FAILED并停止。仅在runner/SSH均0、原档COLLECTED、完整结束、精确预充超限且其他独立检查全部通过时，可保存 `failed-event-diagnostics.json`；其中ΔQ/D/M/ΔM及分类明确是失败诊断值，不伪造通过的metrics bundle。其他失败只保留原始档和错误，停止后由主代理只读核对。

## 结论范围与开发证据

即使三项raw审计均通过，也只有这个固定事件及匹配参考的局部R50结果；物理双支路、数值敏感性和全矩阵验证尚未建立。100→50 Ω比较标为电路参数敏感性，原100 Ω数值仍带科学失败身份，不能充当同模型可替换样本。

7项开发检查通过，退出0：授权/期限边界、生成control/neutral完整契约、只有Rpre改变的deck比较、100 Ω参数/deck/parent拒绝、原守恒等关键函数AST一致、ledger保护/显式adapter、双预算及不可覆盖CSV。证据见 `local_runtime/dram-see-v3/r50-dev/self-check-03.log`。这些是构建和逻辑检查，不是新TCAD结果；真实冻结/调度、断连和恢复由独立validation_worker验收后交主代理执行。
