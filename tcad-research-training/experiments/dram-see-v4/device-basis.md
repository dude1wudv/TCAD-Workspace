# 器件依据、文献边界与迁移清单

日期：2026-10-12。下表是建模前的来源清单，不是已校准器件参数表。未知值保持待定，不能拿旧模型数值自动补齐。

学习阶段更新见 [新增器件证据](stage1/device-evidence.md)：已找到正确全文PDF路径并取得正文；原图像素仍未核验。Fig8/11与Fig12的控制条件不同，另有Park2002结构候选，尚未合并器件参数。

## 90 nm 候选器件

S. H. Shin 等，*Data Retention Time and Electrical Characteristics of Cell Transistor According to STI Materials in 90 nm DRAM*，Journal of the Korean Physical Society，2003，43(5)，887–891。题录见 [KCI](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001194214)；具体结构信息见 [作者上传的论文正文](https://www.researchgate.net/publication/285712995_Data_Retention_Time_and_Electrical_Characteristics_of_Cell_Transistor_According_to_STI_Materials_in_90_nm_DRAM)。KCI 的期号字段显示为 51，与正文首页的 5 不同，引用以正文为准。

| 参数/证据 | 可核对的内容 | v4 处理 |
|---|---|---|
| 工艺/容量 | 90 nm 设计规则、512 Mbit | node_nm 与 gate_length_nm 分开 |
| 实际栅长 | 正文 §II、p888：约 95 nm | 首选几何依据候选，不能填成 90 或 65 nm |
| 栅堆叠 | p888：poly-Si 80 nm、WSi_x 100 nm、Si₃N₄ 180 nm | 这些不是栅氧化层厚度 |
| STI | HDP 与 P-SOG/HDP 比较；Fig3–5 有结构信息 | 选定一个材料系列，记录应力处理近似 |
| 特定偏压 | Fig10：Vds=3.5 V、Vbb=−0.7 V、Vgs=0 V | 只对应电场图，不当作正常 VDD |
| 电学/保持证据 | Fig8 漏电、Fig11 Vth、Fig12 保持 | 后续读取原图、测量条件及数字化误差 |

以上已核对公开正文文本；本轮未对原始图像测尺或数字化，不能声称已取得可直接拟合的曲线。全文 PDF 下载入口返回 404，DOI 入口在本次工具中不可访问；作者上传的正文仍可读取。后续获取清晰原图后再提取数值，不由文字描述估读图点。

## 待补参数与校准方法

| 项目 | 当前状态 | 所需证据/校准 | 依赖 |
|---|---|---|---|
| 有效沟道宽度、结深、STI 宽深和三维版图 | 未冻结 | 原图尺度/额外同结构文献，保持几何可辨识性 | 小尺寸/三维几何 |
| 栅氧化层厚度/介电参数 | 未取得可靠数值 | 同工艺依据与 C–V/电学约束 | 电容与门控 |
| 沟道、阱、源漏的三维掺杂 | 定性工艺已知，数值剖面待补 | Vth、亚阈值/漏电、多偏压曲线约束；报告非唯一性 | 基准与尺寸扩展 |
| 迁移率、复合寿命、界面陷阱/GIDL模型 | 未冻结 | 版本支持、温度/偏压条件和漏电机制依据 | 保持与粒子响应 |
| Cstore、Cbl、耦合电容和板极偏压 | 未冻结 | 同结构文献或独立电路校准；记录是否常数 | ΔQ/读出/守恒 |
| 温度、VDD、字线/体偏压 | 未冻结 | 每条校准曲线的测量条件和实际工作条件 | 不同曲线可比性 |
| 写入、保持、预充电、读出与参考支路 | 未冻结 | 电路与时序依据；受控初态和真实写入分开 | 无粒子基准与分类 |
| 源径向/时间核、材料 W_eh | 未冻结 | 来源、单位及网格可分辨性检查 | 源积分闭合 |

至少先得到一个代表单元可辨识的参数集合，并列出哪些行为得到校准、哪些仍依赖假设。仅调到一条曲线吻合不能反推出真实工艺掺杂；缺少的关键量阻止相关正式结论，不妨碍接口调试。

## 老师两份文献的用途

本地 [SRAM 文献](../../../参考文献/Yifan---Study%20of%20Single%20Event%20Upset%20Phenomena%20Induced%20by%20Muons%20and%20Protons%20in%2065-nm%20Planar%20Bulk%20SRAMs.pdf) 与 [VDMOS 硕士论文](../../../参考文献/周习瑞-硕士论文初稿.docx) 只用于下表明确范围。PDF 同时给印刷页和文件页（1 起始）；DOCX 用章节/公式定位，不虚构渲染页码。

| 来源定位 | 支持内容 | 不能移植的内容 |
|---|---|---|
| SRAM §3.2.2，印刷42/PDF46 | 电磁过程和 δ 电子生产阈值应与敏感体积尺度相容 | 不能不核对 cut 就用于更小结构 |
| SRAM §3.2.3，印刷43–44/PDF47–48，表3.1/图3.2 | 材料层、组成与密度参与输运 | SRAM 层厚/敏感体积不作为 DRAM 参数 |
| SRAM §3.2.4，印刷45/PDF49 | 敏感体积内外收集效率假设、临界电荷、3.6 eV/电子空穴对 | 该方法未实现 TCAD 耦合，不证明 DRAM 电学接口有效 |
| SRAM §4.2.1–2，印刷66/PDF70 | 质子直接电离、散射与核反应共同考虑 | 文中 >10 MeV 的验证偏差不是 DRAM 通用分界；需独立验证 |
| SRAM §4.2.3，印刷67/PDF71；§5.2.1/§5.3.2，印刷80/88 | 束谱处理以及通量/截面、角度积分 | 8.8% 束谱宽和地面宇宙线谱不等于指定空间谱 |
| 硕士论文 §3.1、式(3-1)/(3-2) | Geant4/SRIM/HeavyIon 分工及单位换算思路 | QGSP_BIC_HP、1 µm cut、常 LET、垂直入射、0.1 µm 半径需重审，不照搬 |
| 硕士论文 §4.2，表4-1 | 一个初级中子事件组织多条次级轨迹；示例含多种粒子 | 不能由表格推断已记录母子 ID、时间和逐步沉积 |
| 硕士论文 §4.3 | 通过种类、动能、材料阻止本领/射程资料得到 LET | 能量不等于 LET；仍不能把整个事件压成单一均匀源 |
| 硕士论文 §4.5，式(4-3) | 初级事件为统计单位 | “任一单轨迹越 SEB 阈值”不是联合源 TCAD，也不是 DRAM 读出判据 |

v4 的同事件多轨迹共同 TCAD 注入是待实现和验证的新接口要求，不能写成两文献已替本项目证明。公开的 [NIST PSTAR/ASTAR 说明](https://physics.nist.gov/PhysRefData/Star/Text/intro.html) 提供质子/氦离子阻止本领依据；核过程选择另查现有 Geant4 版本及官方物理列表文档。

## v3 实现核对与 v4 迁移

| 项目 | 已有实现 | v4 改动/保留 |
|---|---|---|
| 输运 | [geant4_transport.cc](../dram-see-v1/geant4_transport.cc)：EM Opt4、步长限制；真空世界/硅块 | 新增核过程及有依据的材料栈；冻结物理列表、数据版本、cut 和步长 |
| 逐步记录 | 已有 event/track/parent、xyz 中点、时间、步长、总沉积/NIEL/电离沉积；只写硅中正沉积步 | 补全粒子、动能、方向、过程、材料和前后端点；独立全轨迹表保留零沉积轨迹 |
| 零沉积 | [event_audit.py](../dram-see-v3/event_audit.py) 接受零沉积/空 steps；每个事件都有 summary | 延续；额外区分无核反应与无有效沉积，不缩减分母 |
| 转移源 | [transport_adapter.py](../dram-see-v3/r50-main/transport_adapter.py) 与 [build_case.py](../dram-see-v3/r50-main/build_case.py) 将全事件电离量折为单条均匀线源 | 用各轨迹/步的空间时间信息共同构建事件源，保留直接电离 |
| 二维 | 有效厚度 1 µm、AreaFactor=1，实际取 xy | 新版本明确映射与电流归一化；三维验证不丢弃 z |
| 源检查 | [audit.py](../dram-see-v3/r50-main/audit.py) 已检查生成量/目标电荷，旧容差 5% | 原门槛不改；v4 分析/离散源积分和器件生成量分层制定容差 |
| 曲线与标量 | v3 原档已含曲线/端口电流，训练表主要用标量 | v4 统一导出曲线与积分量并进入数据合同，不说旧档只有标量 |
| 观测时刻 | [metrics.py](../dram-see-v3/r50-main/metrics.py)：2.8 ns 的 ΔQ、4 ns 的读出；理想钳位初态 | 仅留历史定义；新尺寸时序重新有据制定 |

四个冻结模型见 [models.json](../dram-see-v3/r50-main/data/predictions/models.json)：bit0/bit1 分别预测 deltaQ_fC 与 deltaM_mV。旧特征为 Qdep、Qdep/L、Qdep·sinθ；能量固定 5 MeV。旧尺寸为 0.18/0.25/0.35/0.45 µm，不能声称已有能量外推检验。

旧器件的 5 nm 氧化层、10 fF 存储电容、100 fF 位线电容、1.8 V 字线及掺杂/结深参数是未校准模型设置，不自动进入 90 nm 代表器件。旧 ΔQ=Cstore·ΔVsn 的标签构造也要求物理约束对照避免仅重复恒等式。
