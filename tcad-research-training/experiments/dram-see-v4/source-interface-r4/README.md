# r4：A0/A1 bit1 网格细化与逐接受步场输出

本修订只补做原计划中的 **A0/A1、bit1、mesh factor 0.5** 空间分辨率诊断。r2/r3 的源观测失败保留；它们不会因新后处理可用而变成通过，也不自动把 mesh 0.5 升为其余多源工况的新主网格。器件仍是继承的未校准 0.25 um 二维代表单元，没有引入新器件、训练或三维投影。

此前 r3 实测 legacy/no-window HeavyIon 总量约 1.00416388 fC，两类 Window 的 HeavyIon 积分为零，而 Temperature 窗口有正常输出。这排除了简单补 z 即可解决的假说。因此 r4 保留这些合法输出作诊断，验收改为 **legacy 全时段总量与独立原生 SVisual 全帧测量**，Window 不承担源量通过判定。[上一修订的后备方案与原生语法依据](../source-interface-r3/diagnostics/tdr-fallback-design.md)

## 冻结的物理与观测差异

两个 r2 mesh 参考输入由未修改的 r2 builder 新生成，作用仅为物理输入参考，不是已通过的求解。r4 的 `geometry.scm`、`heavyion.par`、`source-spec.json` 与对应参考逐字节相同；其 `matching_contract` 完全相同。`physical-diff.json` 对照既有 r2 base：只有 `mesh_scale: 1 → 0.5`、`variant` 和几何文件哈希变化，几何文本差异亦完整保存。源参数、电路参数、各段 Transient 和读出时序都不变，注入段 `MaxStep=0.5 ps`。

A0 无源、总指定电荷为零。它保留 legacy/noWindow/Window/Temperature 积分，省去零生成量没有定义的 `Coordinates` 请求；缺少 HeavyIon 原生字段只能标为结构无源，不能虚填数值零场。A1 保持 1 fC、起点 `(0.425,0.3,0) um`、方向 `+y`、长度 0.6 um、径向宽度 0.03 um、`t0=1 ns`、`s_hi=2 ps`，继承原显式 HeavyIon 系数。

在原 0.95–1.05 ns 注入段内只增加：

```text
Plot(FilePrefix="gstep" Time=(Range=(0.95e-9 1.05e-9)) NoOverwrite)
```

本机 SDevice UG pp193–194 区分无 `Intervals` 的范围输出与强制离散时点输出：这里不写 `Intervals`、`MinSpacing` 或额外时点。原有五个 `gfield` 固定输出时点完整保留。去掉 r4 的观测块后，整个 deck 恢复为相应 r2 mesh deck；不能把“本修订不增加强制时点”误写成“原 deck 从未有固定时点”。

`project.json` 继续只列固定曲线、日志、final TDR 和五个 gfield TDR，不使用通配符。原 `scripts/tcad.py` 对整个工程打 tar，动态编号的全部 gstep TDR 由该归档保存。动态名称、帧数和时间不得按假定编号硬编码；固定 outputs 检查成功也不等于全帧完整。

## 独立原生测量要求

提取与审计由独立模块负责，本 builder 不执行 SVisual 或求解。每一实际接受的 BE 步必须能从成功步骤日志、原生 `Writing` 记录和 PLT 精确时刻对应到真实 TDR；窗口起点状态不重复计作正时间区间。缺帧、不唯一映射、失败步或不完整归档均不能用解析场、五帧插值或拟合波形补齐。

全帧原生测量包括 Total 在内的九个 ROI、域面积及空间矩；电荷按实际区间 `Σ G_i Δt_i`，时间矩按区间中点加权。注入窗 TDR 只直接测该窗口，0–4 ns 全量由 legacy 曲线独立测量，不能以解析尾部替代未测窗口外数据。`offline-source-check.json` 是指定源的解析核对，不是 TCAD 测量。

冻结门槛不变：源量相对误差 5%、ROI 比例绝对差 0.05、空间质心 0.01 um、时间质心 0.5 ps；细化对照为电荷 2% 和控制相对电压的 `max(1 mV, 5% 扰动峰值)`。实际 Window 或原生节点积分的离散差异只记录原因，不能据结果放宽阈值。[合同](source_contract.json)

## 构建、检查与共享预算

已生成参考：

```text
local_runtime/dram-see-v4/source-interface-r2/inputs/v4-source-interface-r2-a0-b1-mesh
local_runtime/dram-see-v4/source-interface-r2/inputs/v4-source-interface-r2-a1-b1-mesh
```

已生成候选：

```text
local_runtime/dram-see-v4/source-interface-r4/inputs/v4-source-interface-r4-a0-b1-mesh
local_runtime/dram-see-v4/source-interface-r4/inputs/v4-source-interface-r4-a1-b1-mesh
```

构建 CLI 只接受 A0/A1，bit1 与 mesh 固定；已存在目录拒绝覆盖：

```text
python -B experiments/dram-see-v4/source-interface-r4/build_interface.py build <new-r4-output> --case A0|A1 --reference-project <corresponding-r2-mesh-input>
python -B experiments/dram-see-v4/source-interface-r4/build_interface.py check <r4-input>
python -B experiments/dram-see-v4/source-interface-r4/build_interface.py plan
python -B -m unittest discover -s experiments/dram-see-v4/source-interface-r4 -p test_interface.py -v
```

新候选只准许由主代理按原 `scripts/tcad.py run <r4-input>` 调度。没有新 runner、自动求解、自动重试或软件安装。**跨 r2/r3/r4 共用全局 19 次 TCAD 尝试预算**；本修订冻结时已用 3 次，A0/A1 各一次实际尝试分别消耗剩余预算。`prior_attempts_at_revision_freeze=3` 是冻结时证据，不是实时计数，也不重置当前主调度账本。构建输入本身不启动或预占一次求解。

两候选均通过 `check_project`。14 项离线检查通过，覆盖完整物理 deck 恢复、mesh 唯一物理差异、源参数未变、无新增强制时点、五帧保留、无 outputs 通配符、零源质心语义、全局预算与越权角色/重复输出/篡改/缺字段/非零 z 拒绝。该结果仅表示离线输入一致性，不代表真实全帧提取或源项验收已通过。
