# 三维 A0/A1 接口试点

仅生成两个 bit1 人工案例的输入；本目录不启动 SSH、SDE、SDevice 或 Geant4。两个正式调用和两个预留调用由主调度者管理，失败也保留。全部真实输运事件的 `tcad_ready` 仍为 `false`。

## 模型和新增假设

`geometry-contract.json` 是实体、接触、掺杂和坐标的唯一来源，也供匹配 Geant4 读取。保留旧代表单元的 xy：硅 `[0,.85]×[0,1.2] µm`，氧化层 `[.3,.55]×[-.005,0] µm`，沿 z 外挤到 `[-.5,.5] µm`。这是 0.25 µm 代表单元的人工外挤，不是商业结构校准或 90 nm 器件。

SDE 使用两个 `create-cuboid`。四个接触是完整的对应边界面，`find-face-id` 必须返回唯一面；没有额外金属实体。z 两侧不设电极，采用自然 Neumann 电势、零法向载流子电流边界。固定 `AreaFactor=1`，实际 `Cstore=10 fF`、`Cbl=Cref=100 fF`，不乘 z 厚度。电路、初态控制和 4 ns 时序从登记的 r5 bit1 输入逐字继承；不执行旧模块，也不改其全局变量。

源漏掺杂使用闭合 Polygon。角点按 `+z` 再 `+x` 排列使法向为 `+y`，选择 `Positive` 放置。保持原有浓度、深度和横向 Gaussian factor。Smesh 手册说明 lateral Gaussian 仅在 primary domain 外衰减；覆盖整个 z 宽度的基面因此保留体内均匀 z 分布。仍须在原生网格中核对不同 z 切片，不能以离线字符串验证替代实际网格验证。

xy 全局/表面网格继承 main=0.5 的尺寸。原二维 `MaxLenInt=0.001 µm` 没有直接用于三维，以免隐含要求全宽 z 都达到 1 nm；改为显式各向异性氧化层/界面薄窗，保持 xy 目标而令远场 z 上限为 0.05 µm。源核心 z 上限 0.01 µm，过渡区 0.025 µm。A0/A1 网格定义完全相同。这是诊断起点，未证明收敛；无可信的最终节点数硬上界。

## 源与观测

A0 不含 HeavyIon 源；A1 仅一个 `Ion1`，起点 `(0.425,0.3,0) µm`、方向 `(0,1,0)`、长度 `0.6 µm`、电荷 `1 fC`、宽度 `0.03 µm`、中心 `1 ns`、`s_hi=2 ps`。采用 Native Gaussian/PicoCoulomb，三维归一化 `exp(-r²/w²)/(πw²)`，时间标准差等于 `s_hi`。保留已明确的 `a_i=0,k_hi=1,c1=0,c2=1,c3=0,c4=1`，不将其说成安装默认参数。

`oracle.py` 提供独立闭式体积电荷及 x/y/z 矩、时间积分。该入口只接受上述正 y 人工单轨迹或无源，不接受真实 Geant4 事件、非零电荷零长度沉积、轨迹重复分配、二维投影或事后裁切重归一化。3D 体积积分单位换算为 `1 µm³=1e-12 cm³`，绝不再乘二维等效厚度。

保留 5 张固定 `gfield` TDR 和注入窗口每个接受步的动态 `gstep` TDR；Range 不加 Intervals，不新增强制时间点。`project.json` 仅列固定产物，动态文件由原 runner 的完整原档保存。`access_device.plt` 保留器件端口数据，`circuit.plt` 保留节点及电路支路数据。CurrentPlot 的全域 G、Coordinates 及 Window 仅作为诊断；源场验收依赖独立原生三维 TDR 测量，不能沿用旧失败的 Window 路径当通过依据。A0 没有 HeavyIon 字段时报告结构无源，不创建伪造的数值零场。

## 同一 SDE 阶段的资源门槛

成网后，SDE 通过手册支持的 `system:command` 调用已存在的 `/usr/bin/python3 mesh_resource_guard.py`。它只读输入、网格、网格日志、`/proc/meminfo` 和可用空间，写本次 `mesh-resource-report.json`；通过时另写 `mesh-resource-passed.json`。未知/重复节点记录、空间或初始内存不足都会返回非零并触发 `sde:error`。原 runner 要求 SDE 阶段产出 passed 文件，故不会继续 SDevice。没有另建运行器或另起网格作业。

使用 fine A0 原档实测的 103498 mesh vertices、103112 SDevice grid points、平均帧 9900357 bytes 作为**条件资源代理**：

`平均帧字节 × 实际 mesh vertices/103498 × 410 帧 × 1.25 格式裕量 × 2 副本 + 1 GiB`。

估计后至少留 8 GiB 磁盘，初始 MemAvailable 至少 4 GiB。mesh vertices 不是器件实际 grid points；410 帧、线性比例和格式裕量不构成严格上界。没有可信的 ParDiSo 峰值内存估计，守卫通过也不保证求解一定装得下。主调度者仍负责运行前资源核查和实际作业状态。守卫阻断保留原档并计已开始的尝试，不自动降网格或删帧。

## 使用和验收边界

从仓库根目录执行（这些命令只生成/检查）：

```powershell
python -B experiments/dram-see-v4/source-interface-3d-r1/build_interface.py build local_runtime/dram-see-v4/source-interface-3d-r1/inputs/v4-source-interface-3d-r1-a0-b1-main --case A0
python -B experiments/dram-see-v4/source-interface-3d-r1/build_interface.py build local_runtime/dram-see-v4/source-interface-3d-r1/inputs/v4-source-interface-3d-r1-a1-b1-main --case A1
python -B experiments/dram-see-v4/source-interface-3d-r1/build_interface.py check-control local_runtime/dram-see-v4/source-interface-3d-r1/inputs/v4-source-interface-3d-r1-a0-b1-main local_runtime/dram-see-v4/source-interface-3d-r1/inputs/v4-source-interface-3d-r1-a1-b1-main
python -B experiments/dram-see-v4/source-interface-3d-r1/test_interface.py
```

主调度者通过 `python scripts/tcad.py run <新工程目录>` 调用现有工具链。输出目录必须全新且属于本 revision；`check_project` 逐字重建全部期望输入、核对角色、源量、dimension、源码和旧参考哈希。`check_control` 核查配对输入一致，不冒称已有真实电学对照。

本实现未运行远端工具。原生 SDE 语法/接触面积、掺杂 z 切片、实际 3D 网格、资源守卫远端执行、4 ns 完成状态、三维源场与回路结果都必须由真实试点确认。任何失败不修改原阈值或历史版本。首次三维导师汇报还需要另批几何匹配核次级的联合器件响应，本人工试点不满足该里程碑。

手册依据保存在授权的 `local_runtime`：SDE UG pp232、242–243、323、553、567–568、574；Smesh UG pp37、175、181–182；SDevice UG pp58–59、193–194、813–814。源合同记录这些受限文件的 SHA，不复制进源码目录。
