# 共用指标、标签与评估口径

2026-11-16 UTC。先复述已冻结 v3 的真实实现，再列 v4/实验需要冻结的合同；不同版本不强行套用同一阈值。
来源：[v3 metrics.py](../experiments/dram-see-v3/r50-main/metrics.py)、[statistics.py](../experiments/dram-see-v3/statistics.py)、[reporting.py](../experiments/dram-see-v3/r50-main/reporting.py)、[v4 接口](../experiments/dram-see-v4/interface-contract.md)。

## 1. v3 连续量：符号和时间

令 b∈{0,1}，signal 为粒子响应，control 为同初态无粒子对照，neutral 为独立中性参考：

- `ΔQ_fC = Cstore × [Vsn_signal(2.8 ns) − Vsn_control(2.8 ns)] × 1e15`。有符号，不能取绝对值代替。
- `D_mV = [VBL_signal(4 ns) − VBL_neutral(4 ns)] × 1e3`。
- `M_mV = (2b − 1) × D_mV`；control_M 用匹配 control 与同一参考计算。
- `ΔM_mV = control_M_mV − M_mV`；正值为裕量损失，负值为裕量增加。
- 读窗为 3.8–4 ns：真实采样分段线性插值，在相关端点并集求 extrema；不超出覆盖区间外推。4 ns 单点分类与整个读窗稳定性分开报告。

signal/control/neutral 的完整匹配键及实际 mesh 哈希须一致。neutral 的 0.5 V 初态不表示可把其真实参考波形替换为恒定 0.5 V。

例如已有 bit0 响应 `M=77.242354 mV`、`control_M=37.496666 mV`，所以 `ΔM=−39.745688 mV`；不能写成正的退化幅度。

## 2. 分类与科学含义

| 标签 | 判据或含义 | 报告规则 |
|---|---|---|
| correct | M > ε | 原定读出判据下正确，不等于所有后续时刻都安全 |
| criterion_error | M < −ε | 判据误读；底层旧别名 criterion_logic_flip 不直接译为已证持久位翻转 |
| critical | −ε ≤ M ≤ ε | 含等号，保留边界类 |
| numerically_uncertain | 原数值细化/连续量/跨界规则尚不足以给出确定标签 | 覆盖原始分类，保留 reason 和后续证据 |
| failed / missing | 求解或验收失败 / 缺所需输出 | 留在计划分母与失败统计；不得默认为 correct 或零响应 |
| persistent flip / SEFI | 需独立的持续性/功能判据与观察证据 | 现有 v3 裕量不能独立证明；未测记 unknown |

v3 主阈值 ε=5 mV，敏感性阈值 2.5/10 mV。距阈值≤0.5 mV且匹配细化未全、细化实际跨界或连续量资格失败时，按原 reporting 规则保留数值不确定。细化组合为 step=0.5/mesh=1 与 step=1/mesh=0.7，不在新报告中放宽。

## 3. 分母、未决与不确定区间

- 每物理条件、每个 bit 的计划独立事件 `N=4`；同事件的两种 bit、验证角色、重试、OS 更新前后重放均不增加独立事件。
- `unresolved = critical + numerically_uncertain + failed + missing`。
- 误读比例范围为 `[criterion_error/N, (criterion_error+unresolved)/N]`，不删除未决后再缩小分母。
- `valid = correct + criterion_error + critical` 是原表定义，不能称为“全部确定标签”。
- 原 Wilson 95% envelope 使用最好/最坏未决归属的端点；是各分层描述性区间，不宣称所有分层同时覆盖95%。
- 仅无未决且零错误时，报告单侧95%精确上界 `1−0.05^(1/N)`；N=4 时约0.5271，不能据零错误声称可靠性已经很高。
- 全表 96/20/8/4 是冻结设计的响应计数概览，不当作统一器件总体发生率；不以128配对响应取代64独立事件。

## 4. v4 电荷与物理约束：待本版资格冻结

`ΔVsn = Vsn_signal−Vsn_control`；`ΔQsn = Qstore_signal−Qstore_control`。仅常电容、相同板极条件下可简化成 CΔV。

`margin = (2b−1)(VBL−Vref)`；`Δmargin = margin_control−margin_signal`。评价时间、参考、读窗和阈值依 v4 基准冻结，不自动复制 v3 的 4 ns/5 mV。

电流正向统一为流入节点：`R_KCL(t) = ΔQnode(t)−ΔQnode(t0)−∫[t0,t] ΔI_noncap,into(τ)dτ`。保留时间轨迹、端口定义、积分算法和原容差；电容分量不能在 Q 与 I 中重复计入。

AI 对照至少有同划分、同特征预算的无约束模型与物理约束模型。把同一目标的 `ΔQ=CΔV` 恒等式重写为罚项，不足以单独证明物理约束带来新信息；需独立电流/守恒残差及消融，并报告违反率与预测误差的取舍。

## 5. 预测指标与泄漏控制

- 回归误差定义 `e=prediction−observation`；分别报告 MAE、RMSE、max|e|、有效样本数、目标单位、bit与域内/域外划分。
- 所有预处理、标准化、特征筛选、超参选择只拟合当前训练折；同原事件、配对 bit、细化与派生源角色归同一组。
- 原 v3 岭回归只作为历史基线；新的模型比较必须重冻结开发/测试协议。看过旧留出的新方案不能再称在该集合上盲测。
- 若做分类，按确定标签给混淆矩阵，并另报未决/失败占全部计划样本比例；不把只对确定子集的准确率写成总体可靠性。
- 输入若含 Geant4 的沉积电荷，推理成本包括输运；由同一仿真结果计算出的目标/后验物理量不能泄漏进“求解前预测”特征。
- 已冻结 g90/E7/P150/I01/I02 继续隔离；g80/P50/30°属于 proton-I02，不拿来调参。最终留出在模型与预测冻结后才评价。

## 6. 实验截面、错误率和环境 SER：当前待数据

| 指标 | 需要的分母/定义 | 当前可否给项目实测值 |
|---|---|---|
| 固定设计的条件误读比例 | 计划初级事件 N、位置/能量/角度、判据与未决 | v3可按原分层给出 |
| 每bit翻转截面 | `σ_bit=N_bit_errors/(Φ×N_tested_bits)`，Φ为注量；明确容量和错误计数处理 | 不可：原始实验与完整分母尚未交接 |
| 每器件事件截面 | `σ_device=N_events/Φ`，说明单/多位事件合并规则 | 不可；不能把错误bit数当事件数 |
| 每bit单位时间错误率 | `N_bit_errors/(N_tested_bits×观测时间)`，说明工作状态和辐照条件 | 不可；不是无条件环境SER |
| 环境 SER | 在适用粒子/能谱/角度等条件下积分截面与通量，并给适用性与不确定性 | 不可：缺相应实验/空间采样、谱与校准 |

固定入射位置的 TCAD 响应不能直接变成面积截面。中子、质子、α及 SEFI/多位翻转分别记口径；实验计数区间在取得原始数据后按实际统计模型冻结。资料缺口统一见[导师资料清单](mentor-materials-request.md)。
