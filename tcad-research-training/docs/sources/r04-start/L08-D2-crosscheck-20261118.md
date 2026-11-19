# L08 与 D2-narrow-fin 逐项核对报告

- 核对日期：2026-11-18
- 核对对象：D2-narrow-fin
- 论文来源：Soft Error in Saddle Fin-Based DRAM at Cryogenic Temperature
- 论文作者：Minsang Ryu 等
- 期刊：IEEE Access，2025
- DOI：10.1109/ACCESS.2025.3591488
- 原始 PDF：E:\TCAD-Workspace\参考文献\LPDDR5 TCAD\LPDDR5 TCAD\文献\Soft_Error_in_Saddle_Fin-Based_DRAM_at_Cryogenic_Temperature.pdf
- 原始 PDF SHA256：1ebd7294669914cea2fc12ef8381607d8587a336549fb01d3595979ce790b9e0

## 1. 先给结论

D2 确实以 L08 的 14 nm saddle-fin DRAM 作为结构参考。当前 D2 的身份是“L08-inspired 文献代表双单元结构”，用于研究路线的探索性几何、输运和电学校准候选。

D2 对 L08 表 1 的使用关系如下。

- Tox=6 nm、Lsn=20 nm、Lbl=20 nm、Lgt=14 nm、Hjc=82 nm、Hfin=35 nm 直接采用表 1 数值。
- Wfin=8 nm 是表 1 基准值。D2 将它改为 8×0.8=6.4 nm，这是项目定义的窄鳍变量。
- NA=4e17 cm^-3、ND=1e20 cm^-3 以及均匀突变掺杂剖面属于项目代表性假设。L08 图 1 的色标只能提供数量级参考，不能提供完整空间掺杂剖面。
- 154×40×250 nm 来自 L08 图 1 的坐标轴读取并被项目固定为有限计算盒。服务器上的 D2 网格实际坐标范围与这三个数一致。
- D2 的精确内部坐标、材料分区、有限衬底、栅侧间隙、接触位置和电路参数由项目几何构造规则产生。论文图形支持空间关系，未提供足够信息直接复刻这些 CAD 细节。

图 2 主要提供辐照响应工况和趋势。它没有提供 D2 几何尺寸。图 9 提供常规结构 Hjc=82 nm 与加深结构 Hjc=92 nm 的对照。当前 D2 使用 82 nm，没有使用 92 nm。

## 2. 证据清单

| 证据 | 用途 | 当前状态 |
|---|---|---|
| docs/sources/r04-start/L08.txt | 论文文字提取、题录和核对标记 | 本次补齐 |
| plans/dram-se-ddr5-lpddr5/month-one-cases-r06.json | D2 计划倍率和 case 计划 | 已读取 |
| output/r06-case-structure/case-protocol.json | D2 无粒子写入、保持、读取协议 | 已读取 |
| output/r06-case-structure/case-device.cmd | 当前 D2 SDevice 候选 deck | 已读取 |
| scripts/build_r06_case_manifest.py | D2 倍率、几何可行域和有限盒规则 | 已读取 |
| 服务器 experiments/dram-se-r04/model/model.py | L08-inspired 几何构造器 | 已核对 |
| 服务器 experiments/dram-se-r04/model/ASSUMPTIONS.md | 结构假设账本 | 已核对 |
| 服务器 D2 parameter-baseline.json | D2 解析参数、掺杂和几何哈希 | 已核对 |
| 服务器 D2 geometry-reference.json | 40 个区域的实际几何范围 | 已核对 |
| 服务器 D2 verification.json | 原生网格坐标、节点、单元和有限网格前置状态 | 已核对 |
| 服务器 D2 cell_msh.tdr | 当前 D2 原生网格文件 | SHA 已核对 |

服务器侧关键证据如下。

- D2 原生网格路径：<SIM_USER_HOME>/course-workspace/local_runtime/dram-se-r06/p0-anchor-integration-r1/d2-native/cell_msh.tdr
- 同一网格输入路径：<SIM_USER_HOME>/course-workspace/experiments/dram-se-r06/p0-anchor-mesh-export-repair-r1/inputs/r06-p0-d2-mesh-measures-r2/cell_msh.tdr
- 两个文件 SHA256 相同：61a27b7d02765ae9a141ed807f3eed4309232529f37d0eadc28310a7e1cb033c
- D2 解析几何 SHA256：18e8632b896d347dfb94bade39d9b827995fc8143b54d3e4aeb01c9da36d636d
- 实际网格全局坐标范围：x=[0,0.154] um、y=[0,0.04] um、z=[0,0.25] um
- 原生网格统计：28827 个顶点、148145 个单元、40 个区域
- 网格证据状态：passed_limited_mesh_prerequisite
- 当前 D2 的 formal_case_id 为空，native_verified=false，statistics_eligible=false，scientific_accepted=false

verification.json 还记录了 reference_matrix_available=false，原因是原生工具调用 des_mesh_ref_coordinates 时出现 overloaded function 不匹配。当前坐标采用原生 AsIs 读取，实际区域边界和网格文件哈希可核对。这个工具调用问题限制参考坐标矩阵的独立比较，未改变本次确认到的全局坐标范围。

## 3. 与 L08 表 1 逐项对照

| 参数 | L08 表 1 | 当前 D2 | 来源判定 | 说明 |
|---|---:|---:|---|---|
| Tox | 6 nm | 6 nm | 论文直接参数 | 栅氧厚度直接采用 |
| Lsn | 20 nm | 20 nm | 论文直接参数 | 两个存储节点柱的基准长度直接采用 |
| Lbl | 20 nm | 20 nm | 论文直接参数 | 共享位线柱的基准长度直接采用 |
| Lgt | 14 nm | 14 nm | 论文直接参数 | 两个字线的几何长度直接采用 |
| Wfin | 8 nm | 6.4 nm | 论文基准加项目设计 | D2 只对鳍宽做 0.8× 修改，6.4 nm 不是论文表 1 原值 |
| Hjc | 82 nm | 82 nm | 论文直接参数加项目几何映射 | 论文表 1 数值直接采用。项目把它实现为顶端结段高度，范围为 z=168–250 nm |
| Hfin | 35 nm | 35 nm | 论文直接参数加项目几何映射 | 论文表 1 数值直接采用。项目把暴露鳍段实现为 z=115–150 nm |

这里有一个需要记住的细节。表 1 给出的是参数名和值，项目的 model.py 需要把这些参数放入一个完整三维盒模型。Hjc=82 nm 被放到顶部 250 nm 的结段中，Hfin=35 nm 被放到 115–150 nm 的暴露鳍段中。这个空间放置规则属于项目实现。

## 4. D2 当前结构的实际空间关系

### 4.1 坐标方向

项目坐标约定为：

- x 方向沿 SN2–WL2–BL–WL1–SN1
- y 方向横跨鳍宽
- z 方向从衬底底部向上

论文图 1 明确展示了 SN2、BL、SN1、WL2、WL1 和 saddle-fin 的空间关系。D2 保留这组关系。

### 4.2 由项目构造规则得到的 D2 区域

| 区域 | 当前 D2 坐标或范围 | 证据性质 |
|---|---|---|
| 有限器件盒 | [0,0,0]–[154,40,250] nm | 图 1 坐标轴读取后固定的项目盒 |
| 三个硅柱的 y 范围 | 16.8–23.2 nm | Wfin=6.4 nm 导出的项目几何 |
| SN2 存储节点柱 | x=21–41 nm | 项目构造 |
| BL 位线柱 | x=67–87 nm | 项目构造 |
| SN1 存储节点柱 | x=113–133 nm | 项目构造 |
| WL2 栅段 | x=47–61 nm | 项目构造 |
| WL1 栅段 | x=93–107 nm | 项目构造 |
| 暴露鳍段 | z=115–150 nm | 使用 Hfin=35 nm 的项目映射 |
| 结段 | z=168–250 nm | 使用 Hjc=82 nm 的项目映射 |
| 栅和侧向包覆范围 | y=4.8–35.2 nm 等 | 栅氧、侧间隙和包覆规则的项目构造 |

服务器 geometry-reference.json 的 40 个区域边界逐项支持上述空间分区。原生 cell_msh.tdr 的实际全局坐标范围也支持有限盒三条轴的边界。

### 4.3 当前 D2 掺杂

当前 parameter-baseline.json 记录：

- 背景受主浓度 NA=4e17 cm^-3
- 结区施主浓度 ND=1e20 cm^-3
- 剖面类型 abrupt_uniform_region

这些值的来源标签是 representative_assumption_not_paper_profile。L08 图 1 色标出现 1.0e20 和 -4.0e17 等数量级，项目据此选择了可解释的代表值。图中颜色分布没有给出可直接用于 TCAD 的完整空间函数，后续需要用电学基线和掺杂敏感性验证。

## 5. 与 L08 图 2 逐项对照

### 5.1 图 2 在论文中做什么

L08 图 2 展示位线电流随 LET 的变化，并按温度区分结果。图面横轴是：

- 0.01
- 0.05
- 0.1
- 1
- 2
- 3
- 4 MeV·cm²/mg

温度为：

- 77 K
- 173 K
- 223 K
- 300 K

论文正文还给出以下辐照条件：

- 重离子作用位置关注 SN1
- 高斯电荷分布半径 10 nm
- 注入时刻 15 ns
- 写 1 时 WL1=2.5 V
- 写 1 时 BL=1.2 V

图 2 用于说明 LET 增大时位线电流整体增大，以及温度变化对载流子迁移率和收集电荷的影响。

论文图注写有“as a function of transient time”，图面横轴实际标为 LET (MeV·cm²/mg)。本报告按图面轴标签解释为 LET-位线电流结果，并在 L08.txt 中保留原文。

### 5.2 当前 D2 与图 2 的关系

当前 D2 的 P0 结构和无粒子 WHR 诊断使用原生网格以及电路候选 deck。当前源字段记录为：

- required_source_rows=0
- required_allocations=0
- source_time_ns=null
- independent_new_primaries=0
- future_particle_control_qualified=false

这表示当前 D2 运行用于检查无粒子写入、保持和读取链路。图 2 的重离子电流结果尚未成为当前 D2 的已验证输出。

当前 D2 的项目时序包含：

- SN2 写入约 2.0–10.1 ns
- SN1 写入约 10.2–18.1 ns
- BL 在 18.1–18.2 ns 切换到 0.6 V
- 保持窗约 18.2–30 ns
- 31.9 ns 读取 SN1

因此，论文的 15 ns 位于当前项目写入期。计划将 21、22、24 ns 作为保持窗候选时刻，先通过 D0 的无粒子波形和匹配事件验证，再冻结正式注入时序。这个时序选择属于项目设计，论文的 15 ns 属于重离子写入条件参考。

当前 D2 的 22 ns 仍属于时序候选，不能写成论文已经采用的时刻。当前无粒子 deck 也没有粒子源，不能用它复现图 2 的位线电流曲线。

## 6. 与 L08 图 9 逐项对照

L08 图 9 比较两个结构。

| 项目 | L08 常规结构 | L08 加深结构 |
|---|---:|---:|
| 位线结区高度 | 82 nm | 92 nm |
| 变化 | 基准 | 在基准上增加 10 nm |
| 其它条件 | 基准 | 论文说明保持相同 |
| 温度 | 77 K、300 K | 77 K、300 K |
| LET | 2、3、4 MeV·cm²/mg | 2、3、4 MeV·cm²/mg |

图 9 的研究问题是位线结区变深以后，SN1 和 SN2 的存储节点电位变化如何改变。论文给出的代表性变化包括 VSN1 在 300 K 最多增加约 2.36%、在 77 K 最多增加约 3.59%，VSN2 的变化更小。

当前 D2 使用 Hjc=82 nm，对应图 9 的常规结构端点。计划中 Hjc 从 82 到 92 nm 的连续范围属于项目探索轴。论文直接支持两个端点中的 82 nm 和 92 nm，没有提供 83–91 nm 的连续扫描结果。

## 7. 论文模型与当前 D2 模型的差异

| 内容 | L08 论文 | 当前 D2 | 判断 |
|---|---|---|---|
| 器件结构 | 14 nm saddle-fin DRAM | L08-inspired 两存储节点共享位线代表结构 | 结构关系参考论文，完整 CAD 由项目构造 |
| 栅长、鳍宽等 | 表 1 几何参数 | D2 使用表 1 基准并把鳍宽改为 0.8× | D2 为项目变体 |
| 温度 | 77、173、223、300 K | 当前 P0 以 300 K 为初始基线 | 温度还未扩展 |
| 辐照粒子 | 重离子 | 当前 D2 P0 为无粒子，后续计划接入质子事件 | 粒子链路不同 |
| 能量描述 | LET | 当前计划使用 Geant4 质子输入，并保留能量、沉积能量、EHP 和收集电荷等字段 | 物理量需分开记录 |
| 电荷源 | 高斯分布半径 10 nm | 当前 D2 零源无源行，后续使用原生节点源目录 | 当前没有图 2 源复现证据 |
| 输运模型 | hydrodynamic | 当前 case-device.cmd 使用 Fermi、OldSlotboom、DopingDep mobility、HighFieldSaturation、Enormal、SRH、Auger | 模型卡尚未逐项对齐 |
| 迁移率 | Philips unified mobility、Lombardi surface scattering | 当前 deck 没有对应模型名 | 后续校准项 |
| GIDL | Hurkx band-to-band tunneling | 当前 deck 没有 Hurkx GIDL 条目 | 后续校准项 |
| 输出与判定 | 论文报告位线电流、VSN1、VSN2 变化 | 当前 D2 P0 报告无粒子波形、位线读出裕量和存储节点波形，暂不生成 upset 标签 | 输出口径不同 |

## 8. 三类参数清单

### 论文直接提供的参数或条件

- 表 1 的 Tox、Lsn、Lbl、Lgt、Wfin、Hjc、Hfin
- SN1、SN2、BL、WL1、WL2 的结构角色和相对关系
- 图 1 的坐标轴范围读取结果 154×40×250 nm
- 图 2 的 LET 点和四个温度
- 重离子高斯电荷分布半径 10 nm
- 重离子参考注入时刻 15 ns
- 写 1 时 WL1=2.5 V、BL=1.2 V
- 图 9 的 82 nm 常规结区和 92 nm 加深结区

### 从论文图形读取后形成的结构关系或项目映射

- SN2–WL2–BL–WL1–SN1 的 x 方向排列
- 三个硅柱和两个字线围绕共享位线的空间关系
- 154×40×250 nm 有限计算盒的使用方式
- Hfin=35 nm 放在 z=115–150 nm
- Hjc=82 nm 放在 z=168–250 nm
- 以 x=77 nm 作为共享位线中心

这些内容由论文图形提供方向约束，具体坐标由项目构造器完成。

### 当前项目自行设计或实现的参数

- D2 的 Wfin=0.8×，解析值 6.4 nm
- NA=4e17 cm^-3、ND=1e20 cm^-3 和均匀突变剖面
- 绝对内部坐标、栅侧间隙、有限衬底深度、材料分区和世界盒
- 2e-14 F 存储电容、2e-13 F 位线电容
- 1000 ohm 导通电阻、1e15 ohm 断开电阻
- 0.6 V 板电压、1.2 V 写 1 位线电压的完整电路实现
- 写入、保持、读取的完整 PWL 时序
- 21、22、24 ns 时序验证点和 31.9 ns 读出点
- 当前 35 ns 仿真终点
- 当前 SDevice 物理模型、求解器、时间步、网格和线程配置
- 当前 Geant4 质子源、事件抽样和共享池资源配置

## 9. 当前证据边界和建议

已确认的内容：

- D2 参数基准与 L08 表 1 逐项对应关系。
- D2 的 6.4 nm 窄鳍变体确实由 8 nm×0.8 产生。
- D2 原生 TDR 的三轴范围与项目有限盒一致。
- D2 的 Hjc=82 nm 对应 L08 图 9 常规端点。
- 图 2 提供辐照工况和电流趋势，没有提供 D2 几何尺寸。
- 当前 D2 仍处于 P0 几何、无粒子和电学链路验证阶段。

需要保留的事项：

1. 服务器 parameter-provenance.json 使用 docs/sources/r04-start/L08.pdf 作为源文件路径。本地本次补齐的是 L08.txt，原始 PDF 仍由题录记录和 PDF SHA 绑定。源文件路径需要后续统一为“原始 PDF + 提取文本”双记录。
2. L08 论文模型卡与当前 D2 case-device.cmd 尚未逐项对齐。当前结果适合做结构和链路调试，科学响应比较需要单独完成模型校准。
3. 当前计划文件中的 parameter_baseline_sha256 仍为空。服务器已经有 D2 解析几何 SHA 和原生 TDR SHA，后续冻结正式 case 时应把这两个哈希写入正式输入绑定。
4. D2 原生网格核验使用 AsIs 坐标，参考坐标矩阵因工具函数签名问题暂缺。后续修复工具调用后，应补做一次坐标矩阵独立读取。
5. 论文是重离子、低温和位线电流研究。当前项目是质子、三维结构、写保持读出和预测模型路线。后续报告引用 L08 时应按“结构参考和机理参考”使用，不能直接把论文曲线当作当前 D2 的定量标定数据。

当前没有修改 D2 输入、网格、运行器或活动任务。本次交付只补齐来源文本并增加核对报告。
