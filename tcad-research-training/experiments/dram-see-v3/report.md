# DRAM SEE v3 阶段性结果

快照时间（UTC）：`2026-10-10T16:29:04.622245+00:00`。本报告来自冻结设计、已结束运行的原始归档及匹配曲线重新审计。运行中输出不参与统计。

固定主矩阵为 **64 个独立事件、128 个 0/1 配对响应**。当前获得匹配指标的响应为 **10/128**；至少一位有指标的事件为 5/64，两位都有指标的事件为 5/64。数值复跑、配对位和氧化层变体不增加独立事件数。

## 当前状态与完整分母

以下主阈值为 ±5 mV。已计算的分类仍需结合阶段门槛；`validation_pending` 保存在逐响应 CSV，不能把待完成参考验证写成最终科学有效。

| 类别 | 响应数（计划128） |
| --- | --- |
| correct | 7 |
| criterion_error | 2 |
| critical | 0 |
| numerically_uncertain | 1 |
| failed | 1 |
| missing | 117 |

累计已登记的新求解预算：17782.66 / 86400 s（4.940 h）。继承归档计为0；运行中或未结运行的最终耗时尚未结算：0 项。

| 阶段 | 工程/审计状态 | 连续容差通过 | 分类稳定 |
| --- | --- | --- | --- |
| references | VERIFIED | — | — |
| pilot | VERIFIED | — | — |
| numerical_preregistered | VERIFIED | True | True |

## 指标、初态与参考

`deltaQ = Cstore × (SNevent − SNcontrol)` 在2.8 ns取样并保留符号；`D=BLsignal−BLneutral`；`M=(2b−1)D(4 ns)`；`deltaM=Mcontrol−Mevent`。单位分别为fC、mV。0.1/0.9 V是理想钳位初态，不是访问管实际写入校准。

已重新审计 32 个归档。初态表见 [initial-state.csv](data/summary/20261010T162904634835Z/initial-state.csv)。参考采用同条件完整中性单元曲线；物理双支路源隔离和匹配电压需要各自的真实验证记录。

| 复核门槛 | 原档重算通过/计划 | 已结束物理分支 | 证据状态 |
| --- | --- | --- | --- |
| references | 8/8 | 8 | VERIFIED |
| pilot | 2/2 | 2 | VERIFIED |

## 按计划分层的计数与区间

每个尺寸×粒子×方向×存储位×阈值计划N=4。failed、missing、critical及数值不确定都进入最佳—最差范围，未隐含视作正确。Wilson双侧95%区间采用冻结分母及未决赋值包络。仅四项全部可判且零误读时，单侧95%上界约52.7%；区间是描述性结果，不保证多重比较同时覆盖。

全部96层见 [statistics.csv](data/summary/20261010T162904634835Z/statistics.csv)，所有128槽位见 [responses.csv](data/summary/20261010T162904634835Z/responses.csv)。原始分类与数值不确定后的分类均保留。

## 预测与真实验证

尚无可报告的真实测试计分。本报告不填充拟合优度、残差或预测成功率；模型/预测冻结及真实测试状态以对应证据为准。

## 数值与氧化层检查

已保存完整数值比较报告 1 份。近边界未复验与确认跨类均按阈值标记数值不确定；连续容差失败独立记录，不能靠放宽阈值或换事件消除。

氧化层敏感性尚无完整结果；4/5/6 nm是预登记假设，不能写成已验证的真实工艺规律。

## 图件与证据类型

下列PNG/SVG由真实数值生成并标为DATA PLOT。它们不代替Sentaurus Visual原生导出或真实桌面截图；原生软件取证须单独保存来源run ID和哈希，未提供时保持待完成。

![initial-state](data/summary/20261010T162904634835Z/figures/initial-state.png)

Actual audited prestrike samples; targets are guides, not simulated samples. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/initial-state.sources.json)。

![readout-l018](data/summary/20261010T162904634835Z/figures/readout-l018.png)

All available planned event curves, controls and neutral curves; missing curves omitted, no sample selection. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/readout-l018.sources.json)。

![threshold-window-l018](data/summary/20261010T162904634835Z/figures/threshold-window-l018.png)

All available event margins in 3.8-4 ns. Guides +/-2.5, 5, 10 mV; crimson alpha, blue proton; dotted 30 deg. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/threshold-window-l018.sources.json)。

![readout-l025](data/summary/20261010T162904634835Z/figures/readout-l025.png)

All available planned event curves, controls and neutral curves; missing curves omitted, no sample selection. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/readout-l025.sources.json)。

![readout-l035](data/summary/20261010T162904634835Z/figures/readout-l035.png)

All available planned event curves, controls and neutral curves; missing curves omitted, no sample selection. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/readout-l035.sources.json)。

![readout-l045](data/summary/20261010T162904634835Z/figures/readout-l045.png)

All available planned event curves, controls and neutral curves; missing curves omitted, no sample selection. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/readout-l045.sources.json)。

![stratum-counts](data/summary/20261010T162904634835Z/figures/stratum-counts.png)

Fixed N=4 per bit/physical stratum; missing bars describe planned status, not measurements. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/stratum-counts.sources.json)。

![stratum-intervals](data/summary/20261010T162904634835Z/figures/stratum-intervals.png)

Only strata containing actual classified observations; descriptive envelope includes unresolved assignments. 来源：[哈希与run索引](data/summary/20261010T162904634835Z/figures/stratum-intervals.sources.json)。

未生成图件（没有补造数据）：

- threshold-window-l0.25：No matched event and neutral curves
- threshold-window-l0.35：No matched event and neutral curves
- threshold-window-l0.45：No matched event and neutral curves
- prediction-residuals：No completed scored test responses
- oxide-sensitivity：No completed oxide comparison

### 原生场图与真实窗口证据

原生场图和真实SVisual窗口截图与DATA PLOT分开保存。原始归档、4 ns信号TDR及本地取证文件已核对哈希，只证明来源一致；色标、单位和所选run的视觉审查仍单独待完成。

- `20261010T103149Z-v3-physical-l018-b1-33b11a8f` / `v3-physical-l018-b1`；预声明目标：是；状态：`CAPTURED_PENDING_VISUAL_REVIEW`。 [原生导出](figures/native/20261010T103149Z-v3-physical-l018-b1-33b11a8f/final-field-native.png)；[真实窗口截图](figures/native/20261010T103149Z-v3-physical-l018-b1-33b11a8f/own-window.png)；[取证JSON](figures/native/20261010T103149Z-v3-physical-l018-b1-33b11a8f/evidence.json)。

  条件：L=0.18 um，bit=1，oxide=5.0 nm；场量 `Abs(ElectricField-V)` (V/cm)，坐标 um。原档 SHA-256：`dd60439dbc6a6df35d9d80625d6ca7cae4d1478204cddbd05b984d31e787174b`；TDR SHA-256：`b93832c293345c1510ec216114c8a8e2f1b96fbc878566670d94ea9926a4b9a5`。范围：Actual 4 ns signal electric-field map; NOT a transient readout curve or Workbench Run-button evidence; no solver launched 视觉审查：pending human/agent image inspection of actual colorbar, units and selected run。

- `20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16` / `v3-l018-alpha-a30-s202610311-b1`；预声明目标：是；状态：`CAPTURED_PENDING_VISUAL_REVIEW`。 [原生导出](figures/native/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/final-field-native.png)；[真实窗口截图](figures/native/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/own-window.png)；[取证JSON](figures/native/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/evidence.json)。

  条件：L=0.18 um，bit=1，oxide=5.0 nm；场量 `Abs(ElectricField-V)` (V/cm)，坐标 um。原档 SHA-256：`f86b5a2ccec292d8ef5acb1c582d9504a76e399fda33ea114bf8ffcfc82d8466`；TDR SHA-256：`feea6832e0d859db5f636aeda6e58665d43f890cb6e2ae66b52e898dd9503f82`。范围：Actual 4 ns signal electric-field map; NOT a transient readout curve or Workbench Run-button evidence; no solver launched 视觉审查：pending human/agent image inspection of actual colorbar, units and selected run。

## 课程交付与结论边界

课程材料草案索引见 [materials/index.md](data/summary/20261010T162904634835Z/materials/index.md)，参数来源见 [parameter-sources.csv](data/summary/20261010T162904634835Z/materials/parameter-sources.csv)。实际学生分工、教师审核、实验室资源交接、答辩和最终考核均须真实记录；本脚本不把技术运行替代课程验收。

本研究为未校准二维1T1C探索模型。粒子扰动、判据误读和物理持久位翻转不能混称，不外推商业DRAM可靠性或真实辐射截面。

原始证据及源码哈希见 [sources.json](data/summary/20261010T162904634835Z/sources.json)；完整阶段快照见 [summary.json](data/summary/20261010T162904634835Z/summary.json)。
