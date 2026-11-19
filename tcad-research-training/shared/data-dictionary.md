# 共用数据字典与数据合同草案

适用课题：**AI辅助下的DRAM存储器单粒子效应评估研究**。2026-11-16 UTC。
本页分开说明“已有字段”和“下一批必须记录的字段”；不修改既有 CSV，不把待补数据填成 0。原 run/账本继续是唯一执行来源。

## 数据粒度与关联

- **事件**：一次被冻结的初级粒子事件/轨迹；同一事件的 bit0/1、细化、源缩放或更新前后重放均不增加独立事件。
- **响应**：事件 × 器件/工况 × stored_bit × 验证角色；以 response_id 关联 run_id、原输出与控制组。
- **分层统计**：物理条件 × stored_bit × 阈值；保留 planned_n、全部未决与失败。
- **划分组**：同一原事件及派生响应一起分组；超参搜索在开发数据内分组，保留冻结测试。v1/v2/v3/v4 不直接纵向拼成同质样本。

## 已有 v3 responses.csv：34 个字段

唯一来源：[冻结 responses.csv](../experiments/dram-see-v3/r50-main/data/delivery-r4/20261012T0033Z-full/responses.csv)，128 行。数值类型指解析后的类型，原 CSV 中均为文本。

| 字段 | 类型/单位 | 解释与使用约束 |
|---|---|---|
| gate_length_um / oxide_nm | number，μm / nm | 原模型几何；不是 v4 的埋栅顶深或真实 DDR5 工艺节点 |
| particle / angle_deg | string / number，deg | 粒子种类与冻结入射角；能量/位置从冻结设计补元数据，不凭文件名猜测 |
| seed / condition_id / replicate | integer / string / integer | 随机种子、物理条件、条件内重复序号；seed 单独不是跨版本全局事件主键 |
| event_label / response_id / stored_bit | string / string / integer 0或1 | 事件与响应身份；成对 bit 的独立事件计数只记一次 |
| split | enum | 原值 train、holdout、extrapolation；沿用原冻结划分 |
| step_scale / mesh_scale | number，无量纲 | 时间步/网格验证倍率，不作为独立物理样本 |
| status / ledger_state / run_id | string | measured 等数据状态、原执行状态、原运行身份；不要互相代替 |
| deltaQ_fC | number，fC | Cstore×(Vsn_signal−Vsn_control)，2.8 ns；保留符号 |
| D_mV / M_mV | number，mV | 4 ns 的有符号差分读出及按 stored_bit 定向的裕量 |
| control_M_mV / deltaM_mV | number，mV | 对照裕量；ΔM＝control_M−M，负值是裕量增加 |
| numerical | JSON object | 连续量资格、细化完成、边界跟进与数值不确定阈值；不能压成一个 success |
| raw_classification / effective_classification | JSON object | 阈值键 2.5/5.0/10.0，单位 **mV**；优先采用保留数值覆盖的 effective 值 |
| read_window / control_read_window | JSON object | 3.8–4 ns 读窗；内部 margin 用 **V**，classification_stability 的键 0.0025/0.005/0.01 也用 V |
| sources | JSON object | signal/control/neutral 各自 run_id、archive_sha256、mesh_sha256、matching_contract_sha256 |
| validation_pending | JSON array | 原版本待验项；空数组不代表新课题校准或实验验证全部完成 |
| actual_ledger_tag / owner_plan / case_freeze | string/path | 原账本、owner 计划和冻结输入索引；不得复制出第二套运行状态 |
| input_sha256 / archive_sha256 | JSON map / hex string | 输入文件名→SHA256；原输出归档 SHA256 |
| original_attempt | nullable string，按原值保留 | 原首次尝试/追溯信息；重试不覆盖失败身份 |

解析 JSON 必须保持嵌套层级；缺字段/空值记缺失，不能自动转零。单位转换：1 fC＝1e−15 C，1 mV＝1e−3 V，1 ns＝1e−9 s。

## 现有派生表

| 表 | 行数/粒度 | 关键字段及约束 |
|---|---|---|
| statistics.csv | 96，条件×bit×阈值 | planned_n、valid、correct、criterion_error、critical、numerically_uncertain、failed、missing、unresolved、point_bounds、Wilson 区间及零错误上界；valid 不等于确定分类数 |
| prediction-residuals.csv | 256，测试响应×目标×模型 | split、stored_bit、target、model、observed/prediction 及 residual_prediction_minus_observed；分组先于评分 |
| prediction-scores.csv | 16，划分×bit×目标×模型 | valid_n、MAE、RMSE、max_absolute_error；ΔM 用 mV，ΔQ 用 fC，不混合平均 |
| extension-cases.csv | 22，验证身份 | 18 新求解、4 reused；不作为新独立事件增加样本量 |

上述文件均位于同一[冻结目录](../experiments/dram-see-v3/r50-main/data/delivery-r4/20261012T0033Z-full/)。字段映射需对照实际表头，不能按本页简写替换原表头。

## v4 下一批数据合同：先沿原接口映射，再冻结

权威约束：[interface-contract.md](../experiments/dram-see-v4/interface-contract.md)。以下为汇总/训练出口的**必备信息草案**，不是已建成的数据集或要求改动正在运行的输入。原字段已有时保留并映射。数值主表优先 SI 单位，展示时另转 mV/fC/ns。

| 信息组 | 必备字段/类型 | 来源、空值与准入要求 |
|---|---|---|
| 版本与身份 | schema_version、generation、device_id、condition_id、event_id、response_id、run_id；string | 关联原冻结与实际输出；不得把不同物理版本伪装为重复 |
| 器件与工况 | geometry_id、buried_gate_top_depth_nm、VDD_V、temperature_K、stored_bit、timing_id | 从冻结输入取；g80表示埋栅顶深，参数未知标 null/未交接 |
| 粒子与采样 | particle、energy_MeV、angle_deg、incident_position、position_unit、seed、primary_event_index、sampling_contract_id | 保留能量/空间分母；无沉积事件仍保留；不能只导出有响应的事件 |
| 输运与源 | deposited_energy、deposited_energy_unit、source_kind、source_role、source_contract_sha256、transport_run_id | 源角色包括 main/zero/half/split/h2/dt2；真实 LET/能量沉积须有定义和出处，不自行换算未知材料值 |
| 匹配对照 | control_run_id、neutral_reference_id、mesh_sha256、matching_contract_sha256 | 信号/对照/参考按原合同精确匹配；无匹配则不进入正式响应训练 |
| 观测窗口 | source_window_s、hold_window_s、read_window_s、evaluation_time_s | 数组/number；只在真实覆盖范围插值，不外推，单点与读窗结论分别存储 |
| 连续响应 | Vsn_signal_V、Vsn_control_V、Qsn_signal_C、Qsn_control_C、deltaVsn_V、deltaQsn_C、margin_V、control_margin_V、delta_margin_V | 电荷依原元件/端口定义；常电容且板极条件相同才可用 CΔV 替代 ΔQ |
| 电流与守恒 | current_orientation、current_trace_ref、integrated_noncap_charge_C、kcl_residual_C、kcl_tolerance | 流入为正；明确非电容分量，避免重复计入电容电流 |
| 数值与源资格 | accepted_dt_max_s、source_integral_error、frame_expected/actual、mesh_check、dt_check、pmi_dynamic_check、qualification_status | 实际接受步/实际帧/实际加载证据；不以配置值或编译成功替代 |
| 标签与原因 | threshold_V、criterion_label、persistent_flip_label、qualification_reason、missing_reason | 未测持久性填 unknown；failed/missing/critical/numerically_uncertain 单独保留 |
| 模型与划分 | feature_contract_id、group_id、split、model_version、fit_eligible、test_frozen_at | 训练白名单由资格决定；同事件/配对/细化不能分到训练和测试两侧 |
| 来源与成本 | input_sha256、archive_sha256、analysis_sha256、wall_s、cpu_s、peak_memory_bytes、disk_growth_bytes、reuse_of | 数据与成本可回溯；失败、等待、重试另记录，不因不合格而删除 |

字段完整性、单位、身份唯一性、匹配合同、时间覆盖、数值有限性、分组隔离与资格白名单均通过，才形成一个可训练快照。缺导师物理参数不阻塞接口整理，但该批只能标“代表模型”，不能标“真实 DDR5 校准”。

导师实验的器件/批次、粒子能谱、注量、通量、受测容量、错误 bit 与事件计数、测试时长、重复次数和读出判据仍未交接；使用[单独资料清单](mentor-materials-request.md)，不在本表猜填。
