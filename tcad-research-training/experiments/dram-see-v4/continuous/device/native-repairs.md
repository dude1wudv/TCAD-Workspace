# 原生日志驱动的器件修正

## 接触观察器 r1

依据原档 `local_runtime/runs/20261017T043100Z-v4-continuous-b1-d2-r2/results.tar`。原 SDE 退出为 1；`geometry-with-measurements.log.err` 为 `SCHEME COMMAND 62`、`car: wrong argument type boolean (expected pair)`。原日志显示几何构建、接触设置、掺杂定义、边界保存和 mesh command 写出均成功返回；三个观察 CSV 仅写出表头，尚未产生第一条接触测量。

在第一条接触测量的执行路径中，未经类型检查而调用 `car` 的对象是 `bbox-exact` 返回的 `bounds`。这是按现有日志定位出的最可能路径，旧日志没有打印中间返回值，不能把推断写成已经实测的返回值。

本机已安装 SDE W-2024.09 手册 PDF 第 349 页将 `bbox` 也定义为真实实体的 tight/exact 包围盒，返回 `(min-pt . max-pt)`；第 350 页记录 `bbox-exact` 的同一数据形式。当前补丁使用 `bbox`，保留原实体输入与坐标读数，新增实体 list 和 bounds pair 检查，并把实际接触名、实体列表、bbox 结果写入原日志。没有用名义坐标填值，也没有放宽比较判据。

代码是 `observer_patch.py` 的 `sde-contact-bbox-r1`。生成器只修改当前新副本中的 `s2-observe-contact`，在 `provenance.json/native_repairs` 记录失败 run、原文件哈希、现文件哈希及补丁代码哈希。D2 和 D3 使用相同修正，分别沿用 edge length 和 face area。

新异常的最小本地检查为 `local_runtime/dram-see-v4/continuous/device/sde-observer-fix-check-r1.json`：D2/D3 改变函数的括号配对、物理前缀与其余观察代码逐字不变、无内部 `sde:build-mesh`，均通过。未重跑之前八项或旧套件。

修正后输入是 `20261017T042419Z-v4-continuous-b1-d2-r3`，生成退出 0，随后实际执行仍失败，不能称已修复。其 input manifest SHA-256 为 `5e2301a50b2e709ae6f606d4405bc2c6241c3b917cfd059b5ac21711acf03a07`；run 时间戳使用当前 UTC 工具的真实返回，前一个 run 名称的较大时间值不会作为当前时间来源。

附带工具事实：本地文档提取已成功写入私有 runtime 文本；首次向终端打印包含商标字符时触发 Windows GBK 编码异常，未影响已写入提取文件。随后直接读取已生成文本，不重复提取原页面。

## 接触边界转由实际 mesh 观测 r2

r3 原档为 `local_runtime/runs/20261017T042419Z-v4-continuous-b1-d2-r3/results.tar`。其 `execution.log` 实际记录 `S2_CONTACT_BEGIN "body"`、`S2_CONTACT_ENTITIES (#[edge 29 1])`、`S2_CONTACT_BBOX #f`。因此已经确认失败不是没有接触 edge，而是当前实际 edge list 的 `bbox` 结果没有所需位置对。原退出 1 和部分 CSV 均保留。

已重新核对本机手册：两个 bbox API 均声明接受 ENTITY 或 ENTITY LIST。当前运行表现与文档说明不足以解释具体实现限制，因此停止替换参数形状盲试，不从名义坐标产生“测量”。主代理已授权把辅助 bounds 观测移到原始 mesh/SVisual。

原 measurement-plan 已包含每个真实 Contact region 的全部坐标极值：D2 四接触、XY、min/max，共 16 项；D3 四接触、XYZ、min/max，共 24 项。每项均为原生 `calculate_field_value` 的 region 过滤测量，单位 um、绝对容差 `1e-6 um`、相对容差 0，保持原值。

当前 `contact-bounds-from-native-mesh-r2` 补丁取消 SDE bbox 及对应 CSV 坐标列。SDE 继续测量实际接触实体数、边长/面积，并保留全部接触探针归属及材料探针。比较器要求 mesh 边界测量完整覆盖原接触、坐标、极值方向、原 expected 和原 tolerance；随后从实际 `contact-measurements.csv` 读取数值，任何缺项、错误状态或超差仍失败。该改动改变辅助边界证据的来源，没有取消接触空间范围判据。

新增定向检查只覆盖本次异常：`sde-observer-fix-check-r2.json` 检查两个维度的 Scheme 改动、16/24 项覆盖、缺项及错 region/阈值/expected 拒绝；`mesh-bounds-comparator-check-r1.json` 使用明确标记的合成夹具，完整观察可比较，改变 mesh 坐标或 CAD measure 时 contacts 均为 false。二者都在 `local_runtime/dram-see-v4/continuous/device/`，exit 0；没有重跑原八项或旧套件，也不表示原生成功。

新输入 `20261017T042819Z-v4-continuous-b1-d2-r4` 已冻结并交主代理；manifest SHA-256 为 `c7a3d9ddcc7b0f6c7abcf8ea1d25ef7490bd5e2a82982e2ce18d662c84c3628f`。原生确认仍由原 runner 的下一次真实结果决定。

## Gaussian 深尾数值稳定化 r1

r4 原档 `local_runtime/runs/20261017T042819Z-v4-continuous-b1-d2-r4/results.tar` 的 SDE 实际退出 0，完成接触数、长度、探针及材料观察。日志实测 body 长度 2 um、gate 总边长约 0.165132741228718 um、drain 0.04 um、source 约 0.04 um。snmesh 实际生成最终 50,257 points、99,476 elements、6 regions 并保存 TDR，但最后报告 floating point exception，退出 1；没有进入 SVisual/DC，该 mesh 仍属失败诊断产物。

原 General 表达式在 1 um 域底计算 SN Gaussian 指数约 `-961.7279476039927`，从深度约 `0.8582465376 um` 开始其 exp 进入双精度次正规区。原手册确认 General 直接使用设备 x/y/z 坐标、init 支持分号赋值；这些坐标和初始化形式没有发现语义错误。日志没有报告 FPE 的精确指令，所以这里只确认一个确定存在的 exp 下溢风险，不能宣称它是唯一根因。

当前补丁以文档支持的 `abs` 构造 `min(q,700)=q-((q-700)+abs(q-700))/2`，其中 q 为无量纲深度平方。在未截断区，减去的项精确为 0；再先计算 Npk×exp 后乘 w，以避免中间次正规值。保留原始 w 和 literal `1-w`。没有改峰值 `1.45e20 cm^-3`、背景 `1e17 cm^-3`、0.087/0.1375 um 结深、0.005 um 混合宽度、几何或审核容差。

该数值处理不是全域严格符号等价：深尾的最大新增浓度为 `1.4296530988451667e-284 cm^-3`，相对于背景约 `1.43e-301`。这条差异在每份新输入的 provenance 中明确记录。普通采样点还会产生求值次序的浮点舍入差；9,009 点域内检查的最大绝对差为 `32768 cm^-3`，高于 `1e-250 cm^-3` 的浓度区最大相对差约 `5.70e-14`，均未改变比较判据。

顺带修正实际日志计数：优化阶段的 50,437 vertices 不是最终数；资源观察器现在只解析 `The final mesh has: 50257 points.`。以原失败日志的定向检查确认取得 50,257，原退出 1 保持失败。检查报告为 `local_runtime/dram-see-v4/continuous/device/gaussian-stability-check-r2.json`；前一数值实现的本地检查 r1 保留，最终代码使用减少相消误差的 r2 形式。

r5 项目 `20261017T043418Z-v4-continuous-b1-d2-r5` 生成退出 0，manifest SHA-256 为 `37d6a1b8edf35a532ca6948bfe7285bac184b5009b35f37bca792f8f5c862197`。只有实际 snmesh 退出 0 及后续真实掺杂/几何观测才能解除相应阻断；此处不把失败 mesh 或软件数值检查计为原生资格。

## SVisual 上下文、Interface 元数据及有源区网格 r1

r5 已实际完成并完整收集：SDE、snmesh 均退出 0，原 FPE 阻断在该输入下解除；SVisual 退出 222，未进入 DC。`geometry-status.json` 记录 30 项必需错误。积分报 dataset reference resolving failed，极值报需要 `/plots/block=false`；已有 `create_plot` 但命令没有显式绑定 plot/geom。带 `-plot` 的坐标掺杂探针则成功返回真实数据。

`visual_patch.py` 复用同版本已成功的 `source-field-audit-r2/extract_fields.tcl` 调用：对 integrate_field、calculate_field_value 和 create_field 显式传 `-plot $s2_plot -geom $s2_dataset`，保留已有 plot 的创建/释放、region/material 过滤、probe 命令和前后 mesh 哈希，不设置未公开的 block 内部属性。

真实库存还包含原生 `Interface` 元数据 `R.Silicon+R.Trench`。比较器只识别由当前两个已声明物理区域组成的这一个接口；它不作为第三种体材料参与积分。任意额外物理材料、区域或与未声明区域相连的接口仍拒绝。原物理区域、接触集合和字段检查保持。

r5 成功取得的 42 个点掺杂字段里，7 个 Arsenic 点超出既有 2% 门，偏差约 3.15%–21.94%，完整不利样本保存在 `r5-doping-diagnostic.json`。没有删除样点、改期望或放宽容差。按主代理确认，在整个有源掺杂邻域添加连续精细网格：D2 x 为 ±0.1 um、depth 为 0..0.25 um，max 为 1 nm、min 为 0.5 nm；D3 x 为 ±0.1 um、y 为 ±0.07 um、depth 为 0..0.25 um，max `(1,5,1) nm`、min `(0.5,2.5,0.5) nm`，覆盖接触和过渡区域，未将 1 nm 铺满整个 0.5 um 宽域。这改变离散精度，不改变掺杂函数或物理结构。

本次最小检查 `r5-repair-check-r1.json` 检查两个角色的 Tcl 完整性、显式上下文与原 probe 命令、新网格范围，并用真实 r5 库存确认该 Interface 可以识别、三种外来库存被拒绝。exit 0，仅为软件检查。r6 输入 `20261017T044000Z-v4-continuous-b1-d2-r6` 已冻结，manifest SHA-256 为 `16958f38c7c68396ac845bad461b40a721271c03b01e91b202fe545dabb71dbf`，绑定原 runner `bba4825dc64e4554268086586ed92860aa82380e9afe10c4a4e88082c84ddc9f`，交主代理串行提交。

## 真实 TDX 拓扑和区域字段观测 r1

r6 原档 `local_runtime/runs/20261017T044000Z-v4-continuous-b1-d2-r6/results.tar` 中，SDE、snmesh 和 SVisual 均真实退出 0，`geometry-status.json` 记录 completed true、mandatory_errors 0。主 runner 把真正的 `svisual_exec` 当作未捕获进程，原运行以 admission 86 停止，未做 DC。主代理随后按实际 `/proc` 父链、安装路径和 ELF 身份修正映射；device 子代理没有修改 runner。

实际数值检查不能仅凭 SVisual 退出 0：16 项 Contact 坐标极值以及 4 项 SiO2 donor/acceptor 极值都返回 `nan {nan nan nan}`，同时状态字段为 OK。其余 6 项材料/域测量、42 个掺杂探针和 4 个 Si 掺杂极值均有限且满足原容差。无效原行完整保留。TDR 元数据后来证实 Contact 没有字段数据，而 SiO2 的实际掺杂字段确实存在，因此既不能把 Contact 的 `nan` 当测量，也不能把 SiO2 视作字段缺失后补 0。

按 W-2024.09 TDX 手册第 23 页，主代理用原 operation 对同一 r6 mesh 执行只读转换。第一次包装在 TDX 前因 checksum 清单 CRLF 失败；第二次 `cgoal-tdr-observe-20261017t045007z` 确实生成 `.grd/.dat`，但 Tcl 将 `TdrFileConvert` 的实际非布尔返回值用 `!` 解析，退出 255，未执行 after hash。失败原档不补写结果。随后拆成 metadata-only Tcl 与独立 CLI `tdx -dd -M 0 -S 0`，分别记录真实退出。

成功诊断为 `local_runtime/dram-see-v4/transport-probe/operations/cgoal-tdr-observe-20261017t045517z`。其 SSH、远端、task、collection、metadata、converter 均为 0，28 个收集成员的 size/SHA 已逐一核对；源前后 SHA 均为 `53f384abfffe7156302df49ae8b2aa50009a2c65dbac953081beb09784854484`。导出 `.grd/.dat` 与前次失败调用留下的文件分别逐字一致，SHA 为 `da9abe0bdbbc774a70c6916dae4a52b7880a57279034c2b34484b6000a2b2a5a` 和 `9307acbe18646381cacbc44f841199a77a75572bb0466033936f9c52a57b9fb7`。

转换器保留了 coordinate-system warning。实际 TDR transform 为单位矩阵、shift 为 0；DF-ISE transform 同为单位矩阵、translate 为 0；95993 个顶点范围为 x[-1,1]、y[0,1]。实际 Contact 元素节点给出四接触正确的范围，源/漏/body 线长与 SDE 原观测相符。184902 个 Si 和 5912 个 SiO2 三角形的有向边全部闭合且面积正；唯一节点数 93103/3243 与对应原字段值数完全一致；面积分别为 1.996368386864/0.002540229520，与独立 SVisual 积分相差 4.4e-11/5.75e-11。没有按警告自动旋转、翻轴或重新缩放。SDevice 手册第 59 页明确 `AsIs` 不施加变换，原 device.cmd 已显式使用它。SDE 手册第 76 页明确建模本身无量纲，本项目冻结建模单位选择 um；实际坐标和积分核对该选择在导出链上未变。

SiO2 的 DopingConcentration、ArsenicActiveConcentration、BoronActiveConcentration 各有 3243 个真实有限值，全部为 0。`dfise_observer.py` 从完整字段值计算极值，不替代缺字段，也不跳过非有限值。接触的坐标来自实际元素连通关系指向的网格顶点。原测量计划、样点、expected 和 tolerances 原样复用；原 SVisual 行继续作为原始方法失败记录进入报告。

生产流程升级为 bridge schema r2，并保留两个独立 TDX 原退出、metadata 前后 hash 和整个转换区间的 mesh identity。D3 → A0 导入现在要求真实六步骤成功归档及这组完整原证据，仍不得伪造原 SSH 退出。D3 合同包含 Si、Trench 和两个 STI 区域；Interface 元数据必须是其两个不同已声明区域的 pair，不能成为新增体区域或引入未知区域。

本次准备时本地 Python 语法检查发现 `prepare.py` 新 provenance append 的一个多余括号，未产生新输入或原生提交，修正后 Python 3.6 语法检查通过。对原 r6 观察和成功转换的只读组合数值审计得到 105 条比较，materials/contacts/doping/units 均 true；报告位于 `local_runtime/dram-see-v4/continuous/device/r6-retrospective-native-observations-r1/retrospective-audit.json`，明确 `source_device_run_passed=false`、`scientific_acceptance=false`。r7 为后续真实验证的新输入，不改写任何旧原档。
