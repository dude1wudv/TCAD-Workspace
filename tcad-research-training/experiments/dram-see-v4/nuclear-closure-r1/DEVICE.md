# 三维器件输入与原生 PMI 场审计

本模块生成输入、准备只引用原始 TDR 的提取操作、核验原生输出。模块不会启动 SSH、求解器或调度者。正式提交、工程资格验收、物理响应验收、预算和唯一所有权由本修订的根控制器负责。旧二维和旧三维实现不修改。

## 稳定 API

```python
mesh = build_cases.freeze_mesh(event_source)  # 纯计算；由控制器独占保存公共 manifest
manifest = build_cases.build(role, destination, event_source,
                             pmi_binary_path, mesh_manifest_path=None)
build_cases.check_project(project_path)
build_cases.check_control(a0_project, signal_project)

job = field_audit.prepare(run_path, operation_label, project=None, destination=None)
receipt = field_audit.collect_receipt(operation_path)
result = field_audit.audit(run_path, operation_path, project=None, output=None)
manifest, provenance = field_audit.source_provenance(run_path, project=None)
```

`build` 只接受合同中的 14 个角色，目标须为新 `RT/inputs/` 或隔离 `RT/device-dev/` 子目录。共享库名须为 `pmi_nuclear_source.so.<architecture>`，输入中复制其完整字节并绑定 SHA256；ELF 文件头检查不等于 ABI 或加载验收。资格零源和点源允许 `event_source=None`、`mesh_manifest_path=None`。其余角色必须在真实事件选定后提供完全可复现的公共网格 manifest；事件选定和自然核见证审核由根控制器完成。

输入项目名称固定为 `v4-nuclear-closure-r1-<role>`，与本地目标目录名无关。`build` 返回 `nuclear-closure-inputs-r1` 字典：`role`、`files_sha256`、`pmi_binary_name`、`pmi_binary_sha256`、`mesh_key`、`time_key`、`matching_contract_sha256`、`source_code_sha256`、`frozen_dependencies`。输入目录已存在时拒绝覆盖。

`prepare` 的操作标签为 `nc-r1-...`；默认仅写旧 `transport-probe/operation.py` 使用的输入目录。测试可指定隔离 `RT/device-dev/` 目标。它返回 `input`（仓库相对路径）、`tdr_count`、`tdr_bytes`、`max_frame_bytes`、四遍原 TDR 哈希读取总量、逐输入哈希和 `dispatched=False`。根控制器随后通过既有 operation 入口串行执行 `task.sh`。

`collect_receipt` 和 `audit` 可接收操作根目录或其 `collected` 子目录。收据存在时重新核验后逐项比较，只复用完全相同的记录，不覆盖。`audit(output=None)` 不写；给出新 RT 子目录时保存 `audit.json` 和 `frames.csv`。

## 器件、网格和时间

正式器件沿用已哈希绑定的代表性三维 Si/氧化层结构、封闭多边形源漏掺杂、bit1 电路与材料模型。`AreaFactor=1`，真实三维体积，无二维外推。PMI 作为负净复合率与原有 SRH/Auger 同时使用。小体资格器件为边长 0.18 µm 的均匀 p-Si，掺杂 1e17 cm⁻³、300 K，两个相对 y 面均接 0 V。

先选定真实事件，再用真实事件和四个人工验证源全部原始端点构成公共细化包络，向外扩展 4w 并裁到 Si。包络只控制网格，不截断 Gaussian 源。保留旧全域、表面及氧化层界面细化窗；新增源包络的 M0 最大/最小长度目标为 10/5 nm。M1 对每个窗的所有长度目标乘 0.75。所有人工角色和 `event-m0-t0` 匹配同一 `a0-m0-t0`；其余矩阵点各匹配自身 A0。

源活跃窗口为所有真实和人工步的 `[min(t0,t1)-8σ,max(t0,t1)+8σ]`，裁至 0–4 ns，向外整数 fs 取整、合并；全部正式 A0/信号共用窗口。T0 源窗最大步长 0.5 ps，3–4 ns 读出最大步长 5 ps，若窗口重叠则采用较小值。T1 将所有阶段最大步长减半。显式 `TurningPoints(Condition(Time(...)))` 使用嵌套整数 fs 点，块边界使用 `InitialTime`/`FinalTime`；不把绘图插值当作求解检查点。

源窗内保留每个实际接受步的 TDR。每个块的 Plot 起点比块初始时刻晚 1e-21 s，仅排除重复初态；该偏移小于最小求解步长 1e-18 s。日志与 PLT 必须证明所有新接受步均有且只有一个 TDR，不能抽帧。0–4 ns 端电流、电路和源标量样本完整保留，包括源窗之外的 Gaussian 尾部。

`check_control` 比较相同几何、网格定义、共享活跃窗、离散检查点、PMI 二进制、电路和数值设置，并逐字比较 geometry/deck。输入步顺序规范化不新增求解。正能量零长度步骤始终保留点源。

## 原生输出和单位

归档中固定输出：`cell_msh.tdr`、`cell_msh.log`、`mesh-resource-report.json`、`mesh-resource-passed.json`、`transient_des.log`、`circuit.plt`、`access_device.plt`、`initial_access_des.tdr`、`final_access_des.tdr`。源窗动态帧匹配 `gstep_bNNN_<digits>_access_des.tdr`，以原生日志的接受时间关联，不按文件名推测时间。

`access_device.plt` 要求每个端口的 `TotalCurrent`、`eCurrent`、`hCurrent`、`DisplacementCurrent`，以及默认原生标量 `IntegrSemiconductor PMIRecombination`。正式器件有 source/drain/gate/body，资格器件只有 source/drain。资格 `circuit.plt` 为 `time`、`v(qs)`、`v(qd)`、`i(access,qs)`、`i(access,qd)`；正式电路沿用已冻结的 sn/bl/ref/wl、电容、泄漏和预充电支路观测。

PMI 使用实际 `ReadTime=t`、`ReadTransientStepSize=dt` 输出 `[t-dt,t]` 的 BE 区间平均源；不把 `Compute_r` 的温度形参当时间。

| 原生字段 | 解释 |
|---|---|
| `PMIRecombination` | `-G_BE`，cm⁻³ s⁻¹ |
| `PMIUserField0` | 独立输出的 `+G_BE`，与负复合率积分交叉核对 |
| `PMIUserField1` | 原生 t，s |
| `PMIUserField2` | 原生 dt，s |
| `PMIUserField3` | 原生离散类型；源帧必须为 BE=3 |
| `eDensity` / `hDensity` | 原生电子/空穴浓度，cm⁻³ |

SVisual 在 Si 内独立积分 `G=-PMIRecombination`、`G_CHECK`、`XG/YG/ZG`、常数 1、e/hDensity。体积单位 µm³；`G` 的积分乘 dt、1e-12、元电荷、1e15 得 fC。`frames.csv` 的 `N_raw` / `P_raw` 为 e/hDensity 的全 Si 体积分，乘 1e-12 得电子/空穴数量；每行包含原生 `start_s`、`end_s`、`dt_s` 和所有 ROI 的率与矩。根资格验收须进一步比较 point/zero 的 e/h 正增量，场源通过本身不代表载流子响应通过。

## 独立证据和门槛

`field_audit` 复用旧归档读取、原生日志接受步解析和原 TDR 引用身份核验的纯函数；每项旧依赖都精确 SHA256 绑定。新 PMI 源审计不调用旧 HeavyIon 科学验收。可选本地 project 只增加逐字验证，不能改变后续重现的归档身份报告。

后处理 `tool-versions.txt` 记录实际请求/解析后的 SVisual 路径、继承的 OMP/OpenBLAS/MKL 线程环境，并从这一次真实 `svisual.log` 原样摘录版本、changelist 和实际 worker 数；不增加一次查询工具调用。独立解析器要求版本 W-2024.09/linux64、changelist 9150440、native worker=1，原 wrapper `/proc` 记录为一个线程、单一 CPU，且线程环境全部为 1。原生 banner 必须与完整日志完全重现。旧版本不存在所误引的 `_serial_metadata`，本次集成修复改为该独立实现，未降低串行门槛。

后处理不复制或删除原 TDR。对整组前、每帧前、每帧后、整组后四个阶段核验原路径、目录身份、设备/inode/大小/mtime/ctime/mode 和 SHA256；每帧释放 SVisual plot/dataset，仅释放内存对象。核验 operation 三类真实退出、归档全清单、输入逐字哈希和完成标志。

源审计将实际 BE 区间与独立解析箱体-时间积分比较：全域/ROI 体积、实际 xyz 范围、每帧时钟/dt/BE 类型、完整 0–4 ns 标量总量、全帧源窗总量、ROI 分配、三轴分区闭合、空间质心、时间质心和 BE 波形。原生总电荷界限严格为目标的 5%，不使用离线绝对容差下限；A0 要求原生源与矩严格为零。其他门槛取冻结 `contract.json`，不因资格或细化失败放宽。源窗外和空间/0–4 ns 之外的解析量单独报告，不重新归一化。

场审计 schema 为 `nuclear-closure-field-audit-r1`，包含 `passed/errors/checks`、`run_id/role`、源/mesh/manifest/archive SHA256、`accepted_intervals`、`native_metrics` 和 CSV 路径/哈希。工程提取收据 schema 为 `nuclear-closure-native-field-receipt-r1`，明确 `physical_acceptance=False`；科学场验收与完整电路/读出验收分开。

## 资源与验证边界

生成的 Python 3.6 原生网格守卫读取实际 SDE 顶点数、网格字节哈希、可用内存与磁盘。估算依据旧实际帧 bytes/vertex、计划接受检查点数的四倍加 16 帧、复制与格式余量；这是提交前条件筛查，不是内存或动态步数的数学上界。守卫要求原冻结内存/磁盘下限和 160 GiB 条件上限，不自动粗化、删帧或改矩阵。真实源与网格可能导致更多 Newton 重试和接受步，须由根控制器继续按真实资源证据守卫。

离线测试只使用隔离临时目录与明确标识的非真实 ELF/源/场夹具。已验证 14 角色生成、输入不可变、共网格/匹配对照、M1/T1、原生检查点、帧覆盖、时钟/源/缺列反例、严格原生总量、收据恢复与资源拒绝。Tcl `info complete` 只证明脚本语法结构完整。

尚须原生资格验证：库的编译器/头文件/ABI 与加载，SDE/PMI/deck/TurningPoints 实际语法，原生 CurrentPlot 名称，原始全接受步导出，真实回退后的 ReadTime/dt/type 和场值，PMI 源符号与 e/h 响应，以及原生 SVisual 字段和积分单位。离线通过不能替代这些资格门槛。本模块未运行这些原生工具。
