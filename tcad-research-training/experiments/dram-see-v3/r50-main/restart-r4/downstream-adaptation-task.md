# r4 下游实施契约（新对话接手）

主调度对话：`01a12b91-0d8c-7303-8837-63079827af41`。本文件是待实施任务，不是已验收源码或求解完成证明。

只读调查已完成：`local_runtime/dram-see-v3/downstream-audit-20261011-newchat/audit.md`，SHA256 `60028a02beea732c474ba88d5c6f72da1e9923a93f4d9a49a0d9c2cd42f08b36`。主代理检查了旧扩展 prerequisites、原 boundary_ranking、原预测核验和旧交付 fit_models 路径，采纳其版本化方案。调查没有重审全部原档；真实激活仍需完整门槛。

测试正常运行期间可以派发一个独立实现代理准备以下新目录，不能访问 SSH、VM、GUI 或启动任何控制器。不要重新调查整个项目。每个文件只允许一个写入者，子代理不再派发。

- 新业务代码唯一范围：`experiments/dram-see-v3/r50-main/downstream-r4/`；源证据适配层、扩展入口、只读交付入口、明确 manifest、说明和聚焦测试。不得修改 r1/r2/r3/r4 冻结依赖、模型、预测、原报告快照或全局账本。
- 开发/隔离验证输出：`local_runtime/dram-see-v3/downstream-r4-development/`。不得创建真实 extension plan/status 或把合成数据混入真实运行索引。
- 先实现共享来源适配与扩展；交付入口依赖该明确接口。四 alias 按调查表固定，canonical/actual/run_id/owner_plan/case_freeze/inputs/archive hashes 全部可追溯。原FAILED及未知退出码保留，逻辑视图不能写回账本。
- 新真实扩展目录预定 `local_runtime/dram-see-v3/physical-revisions/r50-main-extensions-r4/`。只有 root 在测试64、真实完整评分/原档重审、控制器和VM空闲、新源独立验收后才冻结和执行。
- 固定14氧化层、完整128边界排序/两个目标/匹配细化/准确复用及原科学阈值不变；未知extra输入仍须拒绝。无限授权只取消资源上限，原/失败/重试/验证费用继续在唯一全局账本累计。
- 原预测继续绑定r2f，测试结果绑定r4；检查冻结系数和预测可以调用 predict_inputs，不重新运行 fit_models，不重新生成模型或预测。保留r4首次评分，最终数值状态评分另输出。
- 实现后由同一 validation_worker 独立验收必要行为和失败路径；worker只写获准测试/验证目录。主代理再审关键差异、真实源证据及适用边界后验收。开发测试通过不授权激活，也不代表科学完成。

真实顺序：测试64/评分 → 全128及参考门槛重审 → 新扩展验收/冻结/串行执行 → 两原定GUI对象的4张原生/窗口PNG逐张查看 → 新交付快照 → 更新课程报告/论文新版本、生成并逐页核验真实PPT和代理课程材料。已有 `reports/final/` 是19/64测试时的历史快照，保留并复用其结构，不冒称最终版。

人类学生操作、教师审核、试讲、答辩和考核继续按未发生记录。全部代理工作验收完成后才暂停唯一心跳。

## 2026-10-11T15:40Z 当前文件所有权与接口

- `downstream_audit`：独占新目录的 `provenance.py`、`extensions.py`、`implementation.md`、`source-manifest.json` 和扩展开发测试；日志在 `downstream-r4-development/`。不写 delivery 四文件。
- `downstream_delivery`：独占 `delivery.py`、`test_delivery.py`、`delivery-implementation.md`、`delivery-source-manifest.json`；日志在 `downstream-r4-delivery-development/`。不写共享层/扩展或其manifest。共享manifest不包含delivery文件，避免循环；delivery manifest等共享源码稳定后绑定实际hash。
- root：唯一求解调度、源审阅/整合与真实验收。独立validation_worker尚未派发，须等源码稳定；开发完成不等于根验收或扩展激活。代理不能启动SSH/VM/GUI/solver，不能改原始来源。

共享API由扩展实现代理落实：`provenance.Session(extension_plan: Path | None = None)`；`validate_chain()`，`observation(canonical_response_id)`，`prerequisites()`，`check_prediction()`，`stable()`。`Session.ledger`保持完整原账本只读快照。观察返回canonical/actual/run_id/owner_plan/case_freeze/inputs/archive及原observation；prerequisites返回files、128 baseline、原selection、response_sources、四aliases、original_failures、raw_submission_index、分别独立的first/training/prediction/test计划hash、训练审计hash、test_result/prediction_freeze hash、原评分与测试observations。首次完整实际prerequisites只在测试64完成且账本稳定后由root执行。

最终可编辑文稿及真实PPT预定新目录 `reports/final-r4/`。旧 `reports/final/` 的18页课程报告、12页论文和19/64固定快照继续原样保留，后续复用结构、用真实最终证据更新新版本。当前并未创建最终文稿或PPT。
