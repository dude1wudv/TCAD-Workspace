# R50-main 氧化层与边界扩展入口

`extensions.py` 独立实现原冻结设计的后续两阶段：氧化层14项，再对完整128主响应按原规则选出的两个唯一响应做匹配数值验证。它不改首段、后半、GUI或报告源码，不改原全局stages。成功终态仅为 `SIMULATION_STAGES_FINISHED_PENDING_DELIVERY`；GUI、报告和课程活动须另有真实验收。

## 固定科学范围

氧化层阶段使用原0.25µm、alpha/0°/r1和proton/0°/r1事件，4nm与6nm各先新建bit0/bit1无粒子control及neutral，再执行两事件的两位响应，共6个参考加8个响应。5nm直接引用本R50主矩阵四个对应响应。每项保持原硅入口Geant4三文件，校验实际源字节；每厚度重建几何与网格，匹配同厚度control/neutral，且拒绝复用5nm实际mesh。氧化层结果不进入长度模型评分，不增加独立事件。

边界排序从64个原事件×0/1的完整128响应构建，绝不从oxide/probe/旧100Ω/诊断中选。载入原 `numerical.py` 的完整纯函数 `boundary_ranking`，只注入原 `_number`，保持全部阈值距离、condition_id/replicate/bit排序和缺失阻断规则。选择冻结到plan，执行时再次由原档重算并逐项比对，不能换目标。

两目标各有step0.5/mesh1和step1/mesh0.7两细化，分别匹配自己的control与neutral。共享的同条件control/neutral合并为唯一case；bit不同的control绝不合并。只有原R50首段 `numerical_preregistered` 中tag、role、完整kwargs、parent、模型、原档及mesh都严格匹配的项才能复用；计划记录其准确run ID、归档与原input freeze哈希、实际mesh/contract和新增费用0。其余每项新输入独立冻结，最多12个boundary case；新增数量按实际复用清单扣除，不能预设最优共享。

全部比较保留0.5mV/0.01fC门槛及原三阈值。连续失败保存 `NUMERICAL_FAILED` 并停止，分类跨界仍保存原类别并标数值不确定。最终boundary报告对完整128个主响应逐阈值列出 `CONFIRMED_STABLE`、`CROSSING`、`FAILED_CONTINUOUS`、`PENDING_NEAR_BOUNDARY` 或 `OUTSIDE_BAND_UNREFINED`，未入选且仍靠近边界的项保持不确定，不把未复验写成已确认。

## 前置验收与接口

只有首段真实训练、test64、原参考/源隔离/预登记数值、模型预测freeze及真实测试提交时间顺序全部通过，且旧controller已退出，root才可填写：

`local_runtime/dram-see-v3/physical-revisions/r50-main-extensions-r1-acceptance.json`

字段说明如下，不代表验收已经发生：

```json
{
  "schema": "dram-see-v3-r50-main-extensions-acceptance",
  "approved": true,
  "design_sha256": "实际冻结design.json字节SHA256",
  "first_plan_sha256": "首段真实执行plan.json字节SHA256",
  "followup_plan_sha256": "后半真实执行plan.json字节SHA256",
  "test_result_sha256": "后半真实test-result.json字节SHA256",
  "prediction_freeze_sha256": "真实data/predictions/freeze.json字节SHA256",
  "source_manifest_sha256": "extensions-source-manifest.json字节SHA256",
  "accepted_utc": "实际UTC验收时间",
  "evidence": "独立源码和原档验收证据"
}
```

经过root与worker独立验收后，唯一调度者使用：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/extensions.py freeze --label r1
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/extensions.py execute --label r1
```

`freeze` 只做原档重审与不可覆盖证据冻结，不调用SSH/solver/GUI。它重算首段92档、test64与冻结模型评分，检查10物理比较和两预登记细化来源，记录128完整基线、排序、复用项、代码、真实预算规则及原global ledger原字节快照。只有匹配本次科学设计与已验收源码的计划可执行。

运行目录：`local_runtime/dram-see-v3/physical-revisions/r50-main-extensions-r1/`。其中有 `plan.json` / `plan-sha256.json`、`source-snapshot/`、`ledger-before.json`、`case-freezes/`、`status.json`、`oxide-result.json`、`boundary-result.json` 和最终 `result.json`。status包含controller PID、父PID、开始UTC、当前阶段/case、错误、所有计划case、ledger状态与真实run ID，清楚标注复用。不存在第二套成本账本；全局ledger保留全部旧行、旧失败历史和旧stages，只增加本计划新run及其合法失败追加。

新case声明 `deterministic_extension_only=true`、`new_independent_event=false`；共享项继续引用其原行，不改角色或费用。已有新尝试必须是固定顺序的连续前缀且VERIFIED，否则不再提交。FAILED、RUNNING、未知、来源变化或预算不足全部停止，不重发、不跳便宜项。每次提交前用原controller锁/preflight/runner及全局86400s预算；ordinary600s、refinement900s预留，且UTC早于 `2026-10-11T04:37:00Z`。在途正常求解不杀。

## 版本与防泄漏适配

固定 `extensions-source-manifest.json` 绑定本文件，以及后半manifest与其中首段/模型/transport的全部实际依赖，不扫描新目录，不绑定GUI/reporting等后续无关文件。本文件是唯一新增业务源码，无修改任何既有冻结源。

后半原防泄漏函数把所有0.25/0.45粒子响应都当作主测试，而合法oxide/边界也可能有这些尺寸。本模块在**独立加载的后半模块命名空间**中显式替换 `existing_test_attempts`：仍要求真实原测试64、其提交UTC和input metadata全部匹配；额外输入只能是本扩展冻结清单中的确定性角色，且逐参数核对/真实VERIFIED。它不修改原文件、不隐藏global ledger、不把额外响应纳入测试分母。原模型配置、预测值、快照原字节哈希和全部source/artifact检查仍执行。

## 报告读取接口

- `r50-main/data/oxide/results.json`：schema=`dram-see-v3-r50-main-oxide-sensitivity`，4个5nm基线、8个新厚度响应，每项 `observation.metrics`、`differences_from_5nm`、原/新classification和来源。
- `r50-main/data/numerical/boundary.json`：schema=`dram-see-v3-r50-main-numerical-validation`，4项comparisons、selection、reused_cases、continuous_passed/classification_stable，以及128项 `main_threshold_status`。
- 每comparison保留 `baseline_sources/refined_sources`、`variation`、`numerically_uncertain_thresholds_V`、`differences_V`、`deltaQ_difference_fC`、两侧分类。
- runtime阶段/result/status只在实际执行时产生；没有产物时应显示pending，不能从本实现说明推导完成。

## 开发验证

`local_runtime/dram-see-v3/r50-extensions-dev/self_check.py` 的全部输出在显著 `SYNTHETIC-*` 私有目录。最新 `self-check-02.log`：9项通过，退出0。覆盖128完整排序/tie/缺失不替代、oxide14和共享细化唯一计数、6个真实输入生成的4/6nm几何与同R50电路、旧模型/错误bit复用拒绝、近边界未确认/跨界分别标注、完整test64角色适配与非法额外输入拒绝、预算和旧账保护，以及模拟串行顺序/首项科学失败立即停止。

未做真实freeze/execute、SSH、solver、GUI或生产ledger/data写入。没有原档结果生成，模型fixture和mock状态不属于物理证据。旧首段/后半源码hash已作为自检断言保留；实际完整矩阵尚需root调度与验收，不能保证剩余预算或授权窗口内完成。
