# r4 只读交付适配（实现完成，待独立验收与真实激活）

本文件说明新 `delivery.py` 与 `test_delivery.py`。既有 r1/r2/r3/r4 冻结源码、模型、预测、历史失败、全局账本及 `reports/final/` 未修改。软件fixture不属于科学结果。

## 接口与边界

- 共享 `provenance.Session(extension_plan=...)`：`validate_chain()`、`prerequisites()`、`check_prediction()`、`bundle(actual_tag)`、`stable()`；`ledger` 是完整只读快照。需要全128来源/原观测、固定四alias、真实owner plan/case-freeze及input/archive SHA。
- 共享 `extensions.review(session, plan_path)`：须原档重算，返回 `state=VERIFIED`、`plan`、`oxide`、`boundary`、`cases`、`files`；cases每行含tag/run_id/state/raw_reviewed/reused/role/stage/new_independent_event。不以状态文件替代审计。
- 不调用旧delivery的 `main/prediction/tests/collect`；它的 `prediction()` 含重新拟合，当前禁止。仅复用其原native机器核验、固定pure接口及最终数值评分函数。两个native目标仍由r1拥有。
- 旧reporting只接受由四alias构造的独立内存128槽用于统计；不把该视图写回全局账本。完整原账本、失败log/FAILED行、实际提交索引单独保存。费用从完整原账本唯一累计，未知退出码不变。
- 原r4评分在真实新快照中逐字节复制，最终数值证据评分另写；只核冻结hash及固定系数predict_inputs，从不重训练或重写freeze。
- 固定64独立事件、128响应、每层N=4、三阈值、14氧化层case、全128边界排序与不确定状态沿用原函数。缺失/连续失败/分类跨界各自保留；分类临界和跨界不自动否定连续量评分。

## collect门槛与输出

正式入口仅接受 `physical-revisions/r50-main-extensions-r4/plan.json`，需要显式root原生PNG目视记录。64测试、完整上游原档、原评分、14oxide、四项boundary连续比较、完整128×三阈值表、两个目标四张真实PNG机器核验与root真实目视、所有已结成本通过后才返回快照。无SSH/VM/solver/GUI调度行为。

正式输出必须是 `experiments/dram-see-v3/r50-main/data/delivery-r4/<独占新目录>`；软件fixture只允许 `local_runtime/dram-see-v3/downstream-r4-delivery-development/`。任何已有目录拒绝覆盖；写入前后重新核验输入稳定。未生成最后的snapshot-manifest表示写入未完整成功，不可作为最终快照。

命令（仅供root满足前置门槛后执行，本开发任务未执行）：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -X utf8 -B experiments/dram-see-v3/r50-main/downstream-r4/delivery.py --visual-review <真实root目视JSON> --snapshot experiments/dram-see-v3/r50-main/data/delivery-r4/<新时间戳>
```

新快照生成DATA PLOT并保留来源，但图件仍需要主代理实际逐图检查。课程Markdown覆盖可行性、设计/步骤/进度、方法/AI披露、只读演示、答辩提纲与可复现索引；不冒充PPT或实际学生/教师活动。最终课程报告/论文/PPT由root另写 `reports/final-r4/` 并使用相应技能逐页验收。旧19/64报告快照保留。

## 验证状态

必要合成测试覆盖四alias与原FAILED保全、未知/非零退出拒绝、来源错配、128槽/分层N、全成本/重复费用/缺项、连续失败与分类跨界评分、全128不确定表、原生目视缺失、扩展缺失、输出独占、课程活动诚实标注。

开发命令 `local_runtime/vdmos-analysis-venv/Scripts/python.exe -X utf8 -B experiments/dram-see-v3/r50-main/downstream-r4/test_delivery.py` 的18项测试通过，退出0。证据目录 `local_runtime/dram-see-v3/downstream-r4-delivery-development/tests-20261011T155441126450Z/`；其中完整collect仅在内存隔离fixture中调用，未打开真实ledger/run/plan/native。另对既有冻结映射验收包和源码哈希进行了只读复核，没有运行映射命令或实际学生演示。

`delivery-source-manifest.json` 仅在共享源码稳定后创建，绑定旧delivery、demo传递依赖及共享source-manifest的真实SHA，且绑定本入口/测试/说明；清单不递归包含自身，不形成共享↔delivery循环。源码清单不是独立激活验收；真实完整collect、原生截图与目视、最终文稿/PPT尚未执行。
