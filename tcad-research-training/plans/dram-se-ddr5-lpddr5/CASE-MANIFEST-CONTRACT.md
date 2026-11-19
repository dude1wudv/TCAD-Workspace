# 首月逐例计划清单契约 r0.5

清单固定为本目录 `month-one-cases-r05.json`，顶层 `schema_version: 1`、`revision: "r0.5"`。本文先定义字段与语义，再由 `scripts/build_month_one_case_manifest.py` 生成并校验清单。唯一科学预算来源为 [BUDGET-REDUCTION-20261117.md](BUDGET-REDUCTION-20261117.md)；清单保存所用文件的 SHA-256。其他文档只提供已有来源分组和接口约定，不提供第二套科学预算。

这是逐例**计划**，不是执行队列、任务数据库或 runtime ledger。全部 case 的 `status` 为 `planned`；已有 r04 结果及性能 probe 均不映射为 r0.5 成果。`accepted: false` 表示尚未验收，不表示计算失败或未翻转。

## 1. Web 最小接口与扩展字段

| 层级 | 字段与类型 | 约定 |
|---|---|---|
| 顶层 | `schema_version: integer`，`revision: string`，`updated_at: string` | 固定 `1`、`r0.5`；时间为带 `Z` 的 UTC ISO 8601 |
| 顶层 | `profiles: array`，`radiations: array`，`conditions: array`，`cases: array` | 分别为 6、4、18、444 条；`radiations` 是扩展字段 |
| 顶层 | `status: string`，`scientific_budget_source: object`，`budget: object` | `planned`；来源路径、修订和文件哈希；预算是计划数量 |
| 顶层 | `integration: object`，`sampling_contract: object`，`split_contract: object` | 引用已有接口，声明统计和隔离规则，不持久化运行进度 |
| profile | `id: string`，`label: string`，`parameters: object` | ID 保留预算原名，如 `D0-nominal`；只记录相对倍率 |
| profile | `partition: string`，`parameter_baseline_sha256: null`，`baseline_context: object` | 开发或器件留出；尚无实际输入基准哈希；未落实的几何、工作条件保持 null |
| condition | `id: string`，`profile_id: string`，`radiation_id: string` | 稳定 ASCII ID；引用本清单已有 profile、radiation |
| condition | `cohort: "core" \| "reserve"` | 仅 18 个辐照工况；无粒子对照不增加工况数 |
| condition | `energy_MeV: number`，`theta_deg: number`，`phi_deg: number` | 单位由字段名及 `units` 对象同时声明；能量 MeV，角度 deg |
| condition | `budget_tier: string`，`split: string`，`holdout: string \| null` | budget_tier 等于 cohort；划分见第 4 节 |
| case | `case_id: string`，`condition_id: string \| null`，`profile_id: string` | 444 个唯一 ASCII case_id；control 的 condition_id 为 null |
| case | `cohort: "core" \| "reserve" \| "control"`，`kind: "response" \| "control"` | 与 Web 最小接口兼容 |
| case | `primary_index: integer \| null`，`stored_bit: 0 \| 1`，`pair_id: string \| null` | response 的 index 为 0–11；control 的 index、pair_id 为 null |
| case | `run_ids: array`，`accepted: boolean`，`acceptance_evidence: null` | 初始固定 `[]`、`false`、`null`；空数组表示未绑定实际运行 |
| case | `status: "planned"`，`task_id: null`，`parameter_baseline_sha256: null` | 不猜实际 task/run 映射及参数基准哈希 |
| case | `budget_tier: "core" \| "reserve" \| "reusable_zero"`，`selection_mechanism: string` | 与 cohort/kind 联合校验；抽样机制见第 3 节 |
| case | `parameters: object`，`split: string`，`holdout: string \| null` | 包含该例相对器件参数和有单位的辐照量，保持配对一致 |
| case | `primary_provenance: object`，`selection_record: null` | 实际 transport、event、seed、关联组等均未绑定 |
| case | `control_case_id: string \| null`，`reusable_for_condition_ids: array` | response 引用同 profile、同 stored_bit 的唯一 zero；control 列出可复用工况 |
| case | `control_pair_id: string \| null`，`training_eligible: boolean`，`native_random_statistics_eligible: boolean` | control_pair_id 仅用于对照的 b0/b1 配对；不混入主响应 216 pairs |
| case | `codex_progress_ref: null`，`scientific_label: null` | 只留外部进展引用接口；本清单不保存运行态或推测标签 |

未指定的扩展字段由生成器明确输出；消费方应按 `schema_version` 读取所需字段，并容忍扩展键。文件编码为 UTF-8，缺失值使用 JSON `null`，不使用空字符串或数值 0 代替未知量。

## 2. 参数、单位和身份

`Lg/Wfin/Tox/NA/ND` 均使用以下对象，`value` 是相对同名基准参数或剖面的无量纲倍率：

```json
{
  "value": 1.0,
  "unit": "1",
  "representation": "baseline_multiplier",
  "absolute_value": null,
  "absolute_unit": null
}
```

不得把相对 NA/ND 写成绝对浓度，不填写无来源的 nm、cm^-3 或 Web 示例 14/8/6。`Lg/Wfin/Tox` 的绝对长度、NA/ND 的区域和绝对剖面、器件外形长宽、有效沟道、结区几何及工作条件，需要由后续版本化参数基准解析；本清单的 `parameter_baseline_sha256`、`baseline_context` 对应字段保持 null。未变化字段固定为同一基准，不代表绝对值已知。预算来源 SHA 是文档来源证据，不能替代输入参数基准 SHA。

response 的 `parameters.energy/theta/phi` 分别为 `{value: number, unit: "MeV" | "deg"}`。control 仍保留同名量的单位，但 `value: null`、`particle: null`，表示无入射源，不能解读为一个 0 MeV 质子。

ID 不依赖数组顺序、时间、task_id 或 run_id：

- condition：`m1-r05-d0-c0`，profile/组合缩写均小写 ASCII。
- response pair：`m1-r05-d0-c0-p00`；case：`m1-r05-d0-c0-p00-b0` 或 `...-b1`。
- control：`m1-r05-d0-zero-b0` 或 `...-b1`；`control_pair_id: "m1-r05-d0-zero"`，`pair_id: null`。

`primary_index` 是**计划抽样位置**，不是已发生的 Geant4 event ID。任何真实来源复用或修复不生成一个新的独立事件身份；由原运行账本保留实际谱系，按来源关联分组去重。

## 3. 预算与抽样

| 层 | 工况数 | primary 配对组 | b0/b1 响应 |
|---|---:|---:|---:|
| 核心 core | 16 | 192 | 384 |
| 备用 reserve | 2 | 24 | 48 |
| 可复用无粒子对照 reusable_zero | 不计辐照工况 | 不计主响应 pair | 12 |
| 合计 | 18 | 216 个计划主响应 pair | 444 条 case |

每工况 `primary_index=0..5` 的 `selection_mechanism: "random"`，`6..11` 为 `"enriched"`。两类各 6 个计划 primary；同一 primary 的 b0/b1 使用同一个 pair_id、抽样机制和来源，不是两个独立事件。增强与随机选择应在同工况内不重复；具体 seed、入选事件、增强规则和纳入概率目前均为 null，不伪造已完成的抽样记录。

随机池必须保留已发射 primary 的完整分母，包括零沉积事件；增强样本不能直接作为无权总体截面统计。`native_random_statistics_eligible` 仅表示随机子集的计划用途，不表示已取得科学有效标签。来源复用后，216 个计划配对组不保证为 216 个独立入射事件。

control 的 `selection_mechanism: "no_particle_control"`、`budget_tier: "reusable_zero"`，按 profile 和 stored_bit 复用，是读出对照，不是“未翻转”负样本；`scientific_label` 为 null，训练与随机事件统计资格均为 false。每个 profile 恰好两条 control，不按能量、方向重复计数。

备用保留在清单中，但只有预算规定的“核心按期完成、没有待修复长任务且资源余量允许”成立时才由现有调度者决定入队。写入计划本身不触发提交。

## 4. split 与封存

| profile × radiation | cohort | split | holdout | 工况 |
|---|---|---|---|---:|
| D0–D3 × C0,C1 | core | `development` | null | 8 |
| D0–D3 × C2 | core | `domain_holdout` | `domain` | 4 |
| D0,D1 × C3 | core | `high_energy_holdout` | `high_energy` | 2 |
| H0,H1 × C0 | core | `device_holdout` | `device` | 2 |
| H0,H1 × C1 | reserve | `device_holdout` | `device` | 2 |

D0–D3 对照使用 `split: "development_control"`、`holdout: null`；H0/H1 对照使用 `split: "device_holdout"`、`holdout: "device"`，同 profile 封存。已知开发 profile 的域/高能测试可以引用同一个事先定义的 zero 对照；不能将测试 primary、响应标签或由其导出的量用于训练。

配对两状态、同源复用、修复和细化跟随 connected provenance 分组。`primary_provenance.connected_group_id`、`cv_fold` 目前为 null；计划 split 已确定不代表真实来源分组已绑定。若后续映射暴露跨 split 来源关联冲突，按真实关联处理并记录，不能按 case_id 假定独立或静默跨集共享。开发侧训练折、预处理、机理及概率校准沿用已有分组约定；最终留出不参与训练、调参、主动选点和模型选择。

## 5. 与运行和 Codex 进展的连接

沿用 [现有执行接口](../../automation/server-codex/README.md) 的 task/run 和原 runner manifest/归档账本；研究摘要字段参考 [HANDOFF.md 第 7 节](HANDOFF.md#7-状态和报告)。只通过稳定 `case_id` 及未来有证据的 `task_id/run_ids` 做外部连接，不在此文件复制队列、锁、槽位、重试状态或进度数据库。

`codex_progress_ref` 目前为 null；外部接口落实后可解析为引用，进展数据的 `progress/use_scope/uncertainty/next_action` 由原接口提供。本任务不猜 URL，不读取运行态，不将 fresh Web probe observation 写入清单。

未来消费视图只有在实际任务、原生 run、输入基准哈希与验收证据逐一对应时才能显示执行/验收状态；本次交付所有映射未绑定、所有 case planned。旧 r04 或 multicore probe 可以独立展示为历史/性能证据，不得填充新 r0.5 case 的完成率。

## 6. 生成与校验

从项目根目录执行：

```powershell
python -X utf8 -B scripts/build_month_one_case_manifest.py
python -X utf8 -B scripts/build_month_one_case_manifest.py --check
```

默认只生成指定 JSON 文件；`--check` 只读且校验来源文档 SHA、完整参数矩阵、唯一 ID、外键、216 个恰含 b0/b1 的主响应 pair、每工况 6+6 抽样、384/48/12 分层、16/2 工况和留出隔离。对照恰好为六个 profile 各 b0/b1，引用均匹配 profile 与状态。

校验还要求所有 case 的 `task_id`、参数基准哈希、科学标签、验收证据、实际 primary 来源和进展引用保持 null，`run_ids=[]`、`accepted=false`、`status=planned`。重复生成保持 ID 和计划内容稳定；`updated_at` 记录本清单实际生成时间。生成器不访问网络、运行账本或仿真程序。

生成器源文件显式声明 UTF-8；JSON 文本读写均使用 `encoding="utf-8", errors="strict"`，输出无 BOM、换行 LF。预算文档仅按原始字节计算 SHA，不经文本转码。Python 直接写入 JSON，控制台摘要使用 ASCII 转义，不经 PowerShell 管道或默认 cp936/ANSI 编码重写文件；PowerShell 查看原文时使用 `Get-Content -Encoding utf8`。上传/部署时保持文件原字节，并让读取端按 UTF-8 解码。中文 label 示例为“开发基准”“开发：短沟道”“器件留出：高施主”；控制台乱码不能单独作为源文件损坏的证据。

## 7. r0.6 独立执行契约（2026-11-17）

以上第1–6节继续描述原r0.5，不能将H2塞回旧18工况表。r0.6由独立`month-one-cases-r06.json`和`build_r06_case_manifest.py`定义，396个planned槽位；H0长栅长外推、H1/H2逐轴范围内稀疏组合留出，不声明联合凸包内插值。

新授权、真实抽样概率、统计用途与实际资格、原队列对接及P0自动放行统一见`EXECUTION-AUTHORIZATION-r06-20261117.md`。旧r0.5原始清单和已提交任务不改写为r0.6。
