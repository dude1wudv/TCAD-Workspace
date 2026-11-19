# BCAT 全事件输入适配与二维 PMI 候选

本轮交付严格的原事件适配器和可由原 operation 执行的编译输入。没有运行新的 Geant4 事件、CMI/GCC 编译或 TCAD。`native_source_qualified=false`、`pmi_r12_fixed=false` 保持为假。原 `kernel.py` 等封存文件未改。

## 当前接口

`bcat_native_adapter.py::audit(operation, epoch_s, build=BUILD)` 只读原 operation、归档及实际收集文件，返回 `binding` 和 `sources`。`sources` 包含 request 的全部事件，按原 `event_id` 排序，零 Si 沉积事件也保留。`build_package` 写入新的不可覆盖目录；`verify(package)` 重新读取原 operation 并重算完整包，不仅比较已写摘要。

```powershell
# 仅在原 BCAT 事件 operation 真实完成并收集后执行；这里不代填不存在的事件目录。
python -B experiments/dram-see-v4/continuous/projection2d/bcat_native_adapter.py build --operation <原事件operation目录> --epoch <已冻结源epoch_s> --output <projection-implementation下新目录>
python -B experiments/dram-see-v4/continuous/projection2d/bcat_native_adapter.py verify --package <上一步新目录>
```

默认编译身份固定为原 `cgoal-bcat-build-20261017t043911z`。adapter 核对原编译/事件 v2 receipt 与 archive、输入 manifest、二进制和源文件字节、实际导出单位、材料探针/几何重叠检查、完整事件/track/step/birth/material-energy 分母与原祖先关联。列名和顺序取自该已编译 C++ 原文，拒绝 planar geometry 和自动坐标置换。输出保留所有原 step 的 xyz、时间、track/parent/step/birth 标识及各材料能量账；不会删掉低响应或晚源事件。

当前几何限定于已编译的 S2：gate 80 nm、SN 87 nm、active width 20 nm。物理条件拒绝只属于 `adapter_stage=development_only`。此接口尚未实现最终评分阶段的自动准入，不构成永久留出禁令；以后应在真实冻结预测先于评分的证据绑定后增加独立阶段入口，不伪造 `approved`、不重标训练样本、不设人工签字门。本轮没有读取最终留出响应。

## 二维表示与单位

已封存核将每个原 Si step 的电离沉积分配为沿真实 `u∈[0,1]` 的均匀分段源，xyz 与 t 使用同一个 u；再施加原空间 Gaussian `w=0.03 um` 和时间 Gaussian `sigma=2 ps`。这属于明确的连续重建，不把离散点直接当成体积剂量。零长度/零弦长仍由原记录明确表示。

二维保守投影是 `G2(x,z,t) = integral[-0.01,0.01](G3(x,y,z,t) dy) / 0.02 um`。`G2` 仍为 `cm^-3 s^-1`；`Q2_C = e * 2e-6 cm * integral(G2 dx_cm dz_cm dt_s)`。只有声明 Si 挤出域与完整时间窗内的质量进入接受电荷，域外、非 Si 原沉积、窗外和晚源独立记账，不补尾、不重归一化。原生 `X→physical x`、`Y→physical z`、第三坐标必须为零；physical y 保留在原三维 source 表，未删除。

一般 dy/dt step 的空间与时间由同一个 u 相关，不能精确变成一个空间 LET 乘公共时间波形的二维 HeavyIon。数学检查给出一个明确非可分离反例。此次候选直接联合积分 u，并用 erf 解析积分 y 和实际 BE 区间，随后除以真实 dt。因此没有提交近似单 HeavyIon 包。

`prepare_pmi_candidate.py::prepare_source_inputs(...)` 未来消费上述全批次真实包，同时要求实际 D2 model、geometry 和 dimensional contract：

```powershell
python -B experiments/dram-see-v4/continuous/projection2d/prepare_pmi_candidate.py source-inputs --batch <已验证BCAT全事件包> --model <实际D2模型JSON> --geometry <实际D2几何JSON> --dimensional <实际D2宽度合同JSON> --window <完整电学起点s> <完整电学终点s> --output <projection-implementation下新目录>
```

每个事件分别输出 `projection-sources3d.dat`（原 R12 11 列物理 xyz/秒/fC/um/秒）、`projection-context.dat`、完整原事件源、独立输入投影参考。`all-event-source-inputs.json` 绑定全批次、实际几何/材料/20 nm 宽度合同和实现 SHA。没有事件选择参数；晚沉积列明需扩展匹配时序，候选不会无声裁去这类源。此命令尚未对真实 BCAT 事件执行。

## 已准备的编译输入

最终输入目录：`local_runtime/dram-see-v4/continuous/control-transition-r14-2d/projection-implementation/pmi-2d-compile-inputs-r2`。

- `candidate-input-manifest.json` SHA：`31dceb972a678be8bccd016d56a9866851a3af46071bc43fd645ccddab289eba`。
- `projection-oracle-vectors.json` SHA：`3d35f172d0ee5817d5cde4b7f0b85bff7f54d67874336a2151681575d486306e`。
- `task.sh` 复用原 R12 已运行过的 SDK/CMI/runtime hash 设置；先核对输入/runtime，再编译与检查 ABI 导出/动态依赖、执行 context 检查及 6 个独立 oracle 对照，记录真实退出。由主代理沿原 operation/owner/锁调度，本模块没有执行入口或新 runner。
- 6 个 oracle 是明确标记的数学向量：零源、点源、一般 dy/dt、仅 y/time 运动、零弦长延迟、重叠。独立期望取自已封存 Python `kernel.generation2d` 的时间数值积分，不来自候选 C++。这些期望不能当成实际 PMI 时钟或原生结果。

原 R12 header 按原已收集字节复用。新 `pmi_projection_qy_r1.C` 仅调用真实 `ReadTime`、`ReadTransientStepSize`、`ReadTransientStepType`、`ReadCoordinate` 和 material API；没有预期 BE 注入。实际 `PMI_UndefStepType` 沿用初始化零源语义并保留原值，实际 BE 必须具备有效正 dt；回退/重试无状态重算。UserField0..5 分别记录 G2/time/dt/type/eta/Nref。时间/type/dt 变化均记录，无截断条数额度。

当前 `eta_G=G2/Nref`、`Nref=1e35 cm^-3 s^-1` 仅是待检验的量子产额表示基。没有制作未经证实的 APD 或可激活的 physics 片段。后续真实验证须确认：实际 APD 数量/单位/tag 及 Nref 基场；PMI 回调随实际接受 BE 及重试更新；原生二维坐标；`OpticalGeneration` 与 G2 的场值/面积×20 nm 积分及矩；相同 mesh/physics 的电子和空穴两方程实际接受同一源。这些问题未解决，不能将编译或 standalone 成功称为 PMI/R12 修复。

## 本轮实际检查

1. `python -B experiments/dram-see-v4/continuous/projection2d/test_bcat_native_adapter.py`：4 项新检查，退出 0。只核对真实编译出处与纯格式/拒绝分支，没有伪造 BCAT event operation。
2. `python -B experiments/dram-see-v4/continuous/projection2d/test_pmi_candidate_inputs.py`：前两项数学检查通过，第三项失败，退出 1。原因是测试将 C++ 流输出 `records<<` 误认为截断比较 `records<`。只修正该测试的运算符匹配，保留原失败日志。
3. `python -B experiments/dram-see-v4/continuous/projection2d/test_pmi_candidate_inputs.py CandidateInputTests.test_03_source_table_preserves_physical_y_and_no_context_approval`：定向重验退出 0，未重复前两项和旧数学套件。
4. 编译输入准备退出 0。r2 复用原已算好的 6 个 oracle 字节，修正新 C++ context 测试中固定输出计数为实际累计计数。此 C++ 测试尚未执行。

本次新增 CMI/GCC 编译数、Geant4 运行数和 TCAD 运行数均为 0。保存原失败、r1 输入和 r2 输入；无取样直到出现大响应的过程，无新预算或签字条件。
