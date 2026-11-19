# 三门课共用图表目录

2026-11-16 UTC。题名统一为 **AI辅助下的DRAM存储器单粒子效应评估研究**。
下列15张图已核对原图、报告副本及既有审阅记录的哈希；不重建或另存三套。机器索引：[figure-catalog.csv](evidence/figure-catalog.csv)，核验：[reuse-audit-20261116.json](evidence/reuse-audit-20261116.json)。

## 可以直接引用的图

“直接”指原图及原限定范围可用；新报告须改为统一正式题名并补来源图注，不改图内的真实数值、坐标或状态。研＝科研训练，项＝项目设计，毕＝毕业设计。

| ID | 图与原件 | 可讲清的内容 | 三课用途 | 图注必须保留的限制 |
|---|---|---|---|---|
| F01 | [初态检查](../reports/final-r4/figures/initial-state.png) | 写入初态和后续匹配对照的起点 | 研：方法；项：输入验收；毕：基线 | v3原结构与原时序，不代表真实DDR5校准 |
| F02 | [氧化层敏感性](../reports/final-r4/figures/oxide-sensitivity.png) | 4/5/6 nm固定事件的局部变化 | 研：敏感性；项：复用；毕：局限分析 | 5 nm精确复用；最大变化约0.11256 mV/0.00578 fC，小于原容差，不宣称显著工艺效应 |
| F03 | [预测残差](../reports/final-r4/figures/prediction-residuals.png) | 岭回归与基线、域内/域外、两目标误差 | 研：AI入门；项：评价接口；毕：历史对照 | 旧冻结划分；Qdep等特征需Geant4，不是无输运成本的预测 |
| F04–F07 | 读出响应：[0.18](../reports/final-r4/figures/readout-l018.png) / [0.25](../reports/final-r4/figures/readout-l025.png) / [0.35](../reports/final-r4/figures/readout-l035.png) / [0.45 μm](../reports/final-r4/figures/readout-l045.png) | 相同事件/bit/对照的波形与读出裕量 | 研：机制；项：端到端结果；毕：响应基线 | 固定5 MeV、固定位置和原二维代表模型；误读不等于持久翻转 |
| F08 | [分类计数](../reports/final-r4/figures/stratum-counts.png) | 正确、误读、临界与数值不确定 | 三课均可用 | 共64独立事件/128配对响应；不删除未决 |
| F09 | [分层统计区间](../reports/final-r4/figures/stratum-intervals.png) | 小样本与未决带来的不确定性 | 研：统计；项：验收；毕：可信度 | 每物理条件/bit的N=4；不是截面，也不是同时覆盖所有分层的95%区间 |
| F10–F13 | 阈值与读窗：[0.18](../reports/final-r4/figures/threshold-window-l018.png) / [0.25](../reports/final-r4/figures/threshold-window-l025.png) / [0.35](../reports/final-r4/figures/threshold-window-l035.png) / [0.45 μm](../reports/final-r4/figures/threshold-window-l045.png) | 2.5/5/10 mV与3.8–4 ns读窗的敏感性 | 三课均可用 | 4 ns单点与整个读窗稳定性分开；v4阈值须另按基准冻结 |
| F14 | [原生物理窗口](../reports/final-r4/figures/native-physical-window.png) | 原生模型/场分布查看证据 | 研：工具；项：可复现；毕：模型说明 | 保留完整窗口、图例和单位；不是粒子发生率图 |
| F15 | [原生事件窗口](../reports/final-r4/figures/native-event-window.png) | 指定事件4 ns电场分布 | 研：机制；项：原生验收；毕：场证据 | Abs(ElectricField-V)，V/cm；SVisual竖向X/横向Y，勿擅自换轴 |

F01–F13是由真实数据生成的 **DATA PLOT**，不能叫“原生软件截图”。F14–F15是完整原生窗口。旧`final-field-native.png`存在右侧单位裁切，不列为可直接使用的图。

数据图来源为[冻结目录figures](../experiments/dram-see-v3/r50-main/data/delivery-r4/20261012T0033Z-full/figures/)中的同名`.sources.json`，里面绑定summary、原run归档、数据/脚本和PNG/SVG哈希；绘图脚本：[plot_results.py](../experiments/dram-see-v3/plot_results.py)。原生图来源见[审阅记录](../reports/final-r4/data/native-visual-review.json)。排版优先使用同名SVG，不能裁掉图例、单位或失败状态。

## 可以直接复用的表与数据

| 内容 | 可排版原件 | 数据与用途 |
|---|---|---|
| 裕量预测误差 | [prediction-dm.tex](../reports/final-r4/tables/prediction-dm.tex) | prediction-scores.csv，mV；分别保留bit、域内/域外与模型 |
| 电荷预测误差 | [prediction-dq.tex](../reports/final-r4/tables/prediction-dq.tex) | prediction-scores.csv，fC；不要和mV混成一个误差 |
| 阈值统计 | [thresholds.tex](../reports/final-r4/tables/thresholds.tex) | statistics.csv；主阈值与敏感性、计划分母和未决 |
| 数值状态 | [numerical-status.tex](../reports/final-r4/tables/numerical-status.tex) | 连续量与分类资格分开，解释不确定结果 |
| 边界细化 | [boundary.tex](../reports/final-r4/tables/boundary.tex) | 真实细化身份与跨界/未完成原因 |
| 氧化层对照 | [oxide.tex](../reports/final-r4/tables/oxide.tex) | 固定事件、复用与局部敏感性，不扩展为统计规律 |
| 历史训练选择 | [training-cv.tex](../reports/final-r4/tables/training-cv.tex) | 历史模型选择过程；不冒充新模型交叉验证 |

上述七张表也属于已核验的211项报告包。CSV原件位于[冻结数据目录](../experiments/dram-see-v3/r50-main/data/delivery-r4/20261012T0033Z-full/)，复制表格进Word时保留字段、单位与脚注。

## 三门课的建议选图

- **科研训练**：F01＋选一张F04–F07＋F08/F09＋选一张F10–F13＋F03，配合文献方法比较；重点讲为什么这样设计、遇到什么问题。
- **项目设计**：F14/F15、同一组波形与数值状态表，配输入哈希/数据合同及后续真实性能图；重点展示可复现流程和验收。
- **毕业设计**：上述原图作为历史方法基线，配新v4资格、校准、AI消融与外部验证；不让旧图替代尚未获得的新结论。

可直接改写的图注模板：

> 图X　v3冻结设计下的[图件内容]。数据版本：20261012T0033Z-full；按原条件与配对规则展示，原始run与输入/输出哈希见共享证据索引。结果用于未校准代表模型的方法验证；[补该图的特有限制]。

## 下一批需要补的图：先有合格数据，再绘制

| 拟新增图/表 | 最少数据 | 当前能推进的工作 | 等待条件 |
|---|---|---|---|
| D2两条完整I–V与原生结构图 | 两条201点曲线、最终TDR、几何/工程验收 | 指标、表头与来源关系已可复用 | 当前D2真实终态与收集 |
| 单/双/三任务吞吐与资源图 | 同探针、真实重叠、native wall/CPU/memory及全程采样 | 使用原并行测试合同，不手填数值 | 主任务完成1/2/3波次 |
| v4两bit全周期与KCL | 匹配A0、main/dt2/h2、真实读窗与电流 | 冻结字段/符号、整理旧失败 | 原作业收齐和资格通过 |
| α/质子源与响应资格图 | 源帧/积分/实际步长、PMI动态证据、六角色及对照 | 验证角色与复用关系已列好 | 代表事件资格补齐 |
| 数据覆盖与缺失矩阵 | 原计划事件/工况、已合格、未决、失败及缺失 | 定义独立事件/角色/版本粒度 | 合格v4快照导出 |
| AI无约束/物理约束消融与分组CV | 同输入预算、同划分、训练记录、冻结预测 | 确定误差、守恒残差和泄漏规则 | 足够合格开发数据 |
| 真实截面/外部泛化比较 | 导师原始错误、注量、容量、条件、重复与模型适用性 | 已列资料缺口与计算口径 | 导师资料到位；当前不能出项目实测图 |
