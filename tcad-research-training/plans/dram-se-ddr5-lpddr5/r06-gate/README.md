# r0.6 提交前准入

`contract.json` 在部署时由 `<SERVER_CONFIG_DIR>/policy.json` 的 `scientific_gate.contract` 固定 SHA。它绑定清单、执行授权和抽样校验器。原 Runtime 对新提案先检查准入，建立 intent 前再检查，并把准入文件及 contract 的 SHA 存入新 intent；已有 intent 继续原身份对账。旧 task 归一化与 task_digest 不变。

**该校验器核验执行方科学决定的状态、来源和哈希绑定，不从 exit0 自动推出科学通过。** 不在本目录放置示范 `passed` 文件。未知、缺失、失败、陈旧或被修改的证据均拒绝新提交。

## P0 诊断

模型可以在 `p0-admissions/<task_id>.json` 独占新增准入文件，不能覆盖已提交版本。任务 ID 必须 `r06-p0-` 开头；项目用新目录；全量 `input_sha256` 与提交时实际输入完全一致。诊断不领取396个正式槽位或统计资格。

准入文件采用 `tcad-r06-p0-admission-v1`，固定 `plan_id=dram-se-ddr5-lpddr5`、`revision=r0.6`、`owner=server-codex`、`scope=p0_diagnostic`。另包含：

- `task_id/backend/project/input_sha256/created_at`；
- `formal_case_id=null`、`statistics_eligible=false`、`budget_account=p0_diagnostics`；
- `profile_id`、明确的 `purpose`、`recipe_id`；
- `diagnostic_plan: {path, sha256}`。

诊断计划采用 `tcad-r06-diagnostic-plan-v1`，绑定相同 `recipe_id/profile_id`，含 `frozen_before_submission=true` 和非空 `acceptance_criteria`。允许的配方：

| recipe_id | 机器检查的范围 |
|---|---|
| `pmi_build` | 仅原Geant4 operation后端的单核编译任务；task.sh精确匹配固定启动器，CMI脚本、新日志源码及两份物理头文件由contract固定SHA，禁止附加输入或求解 |
| `geometry_dc` | 不含 nodal 粒子源；deck 不含 Optics/HeavyIon/PMIPath |
| `zero_whr` | 明确 nodal 源，header 的记录数及分配数都为0；瞬态不超过35ns |
| `prefix_repeatability`、`logging_short_probe`、`logging_long_pair`、`timing_sensitivity` | 仅D0、每个诊断只绑定一个primary、非空且有SHA的 `event_provenance`；瞬态不超过35ns |

TCAD配方用原r4的2数值线程/核心，只允许原生工具。P0 总数和粒子诊断数均无固定上限。旧版契约仍可携带 `max_p0_tasks` 和 `max_p0_particle_tasks`，准入检查忽略这两个字段。每项诊断仍须符合配方和证据要求，修复沿原谱系并受控制器的修复次数限制。新增配方须经维护修订。13个profile的zero可在共同门禁通过前准备和检查，留出zero仍须隔离。

`pmi_build` 沿原单核operation profile在空闲池执行，计入全局最多4个活动任务，并单独记入P0诊断成本。编译返回 `compiled_only`。随后经原生ELF及输入验签才能物化TCAD探针，O2科学验收仍须核查对应证据。

## 正式开发、输运和留出

`production-admissions/<task_id>.json` 采用 `tcad-r06-production-admission-v1`，同样绑定任务、项目、完整输入与创建时间，并包含清单SHA及 `p0_gate` 引用。

P0科学gate采用 `tcad-r06-p0-scientific-gate-v1`，身份字段同上。必须有：

- 与contract一致的 `manifest_sha256`、`p1_authorized=true`；
- `numerics/logging/timing/source_integral` 各自 `status=passed` 和非空 `evidence: [{path,sha256}]`；
- `source_integral.relative_error` 为有限非负数且 `<1e-9`；
- `deck_timing_version`、`source_time_ns`；
- `profiles[profile_id]` 的 `status=passed/evidence` 与 `qualified_bits=[0,1]`。

只要求目标profile合格，另一profile失败不会误伤此分支。P0共同版本失败则拒绝所有依赖该版本的正式粒子任务。

响应的 `scope=development_production`；`case_id/profile_id/radiation_id/stored_bit/block` 必须匹配冻结清单。同一正式case只允许一个提交谱系，修复必须显式沿原case的lineage继续，且与直接父intent保持同一科研对象（case、profile、radiation、状态、事件及选择绑定）；不能用B的成功满足A的依赖，也不能新task重复领取同一位置。AL修复保持原始获取规则和具体事件，不因数值失败换另一个事件；输入技术修复仍须另建目录和完整哈希。

自然统计用途还要提供完整frame和抽样selection的引用、所选event ID及 `case_draw_map` 引用。后者采用 `tcad-r06-cell-case-binding-v1`，固定身份、`block/profile_id/radiation_id/manifest_sha256/selection_sha256`，以及该单元**全部** `case_draws: [{case_id,event_id,stored_bit}]`。清单配额必须与selection的q及b0_count完全相等，R用simple_random，S/HR/HP用stratified；case与draw一一对应，配对状态使用同事件。该单元首次提交后固定mapping SHA，后续不能换抽样。原 `r06_sampling.py` 会重放抽样和概率；准入仍不会预先授予标签统计资格。

Geant4采用独立的 `scope=transport_pool`，以免“生成frame前反而要求frame已存在”形成死锁。绑定目标profile/radiation及 `pool_request`，后者采用 `tcad-r06-transport-request-v1`，含 `profile_id/crn_group_id/radiation_id`、整数seed、`primary_count=100000`、正的 `source_area_cm2`、`uniform_source_area_sampling=true` 和 `retain_zero_deposition_primaries=true`。扩大到1000000还须 `expansion_need` 的passed证据。实际原生request、engine和task必须与此冻结请求一致，由执行方审查并保留证据。

HR/HP响应用 `scope=holdout_evaluation`；留出输运及响应额外绑定 `training_freeze`。冻结文件采用 `tcad-r06-training-freeze-v1`，有 `frozen=true/holdout_used_for_training=false` 和 `model/preprocessing/split/calibration/acquisition` 各自路径及SHA。首次解封的提交intent固定唯一freeze SHA，后续HR/HP必须匹配，换开发版本须明确新研究修订。冻结是开发侧完成后的独立评价边界，不授权用留出回调模型。

AL仍占原82个动态槽位和清单规定的b1状态，不能改成b0。响应准入须给 `acquisition`，采用 `tcad-r06-al-acquisition-v1`，绑定case/profile/radiation/state，`holdout_used=false`；固定 `development_snapshot/candidate_model/selection_rule/event_provenance/response_context` 五份引用、具体 `event_id/transport_run_id` 和完整 `response_input_sha256`。profile和radiation只能来自开发集合。AL不具有总体自然事件统计资格。

## 检查与版本维护

在服务器项目根目录检查已入队但未提交的任务，不启动求解：

```bash
python3.12 -B automation/server-codex/r06_gate.py \
  --policy <SERVER_CONFIG_DIR>/policy.json --task-id <r06-task-id>
```

返回 `scientific_gate_pending` 时按具体原因补证据，不放宽状态或改旧run。改变候选22ns、清单、抽样校验器或执行授权时须同步固定新contract及readiness/policy，经正常控制器维护交接加载；不在运行中悄改已固定文件。用户已授权这类必要维护，不把技术交接误写成需要用户再次批准计划。

