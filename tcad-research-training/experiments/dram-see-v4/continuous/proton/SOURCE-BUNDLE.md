# S2 真实输运入口与事件源接口

当前可交给主调度的输入是 `local_runtime/dram-see-v4/continuous/proton/s2-transport-p100-a0-seed61017041-r1/`，label 为 `cgoal-s2-proton-p100-a0-seed61017041-r1`。它引用已经实际编译并完整收集的 `cgoal-bcat-build-20261017t043911z` 原二进制，定义 `proton-T04`、S2、100 MeV、θ=0°、φ=180°、seed=61017041、1 个初级质子。此目录只生成了输入；没有提交 operation，没有运行事件，也没有生成任何假事件源。

S2 在当前编译合同中是 gate_top_depth=80 nm、SN 结深=87 nm、active_width=20 nm、金属最深=150 nm。输运仍将理想电极空隙显式作为 `G4_Galactic`，不能声称含真实栅金属散射。表面入射点是 (-52,0,0) nm；原生生成器从该方向反向延伸到 z=-1 µm 处发射。两者分别保存在事件 binding 的 surface position 和 beam start，不能混写。

在项目根目录复现新输入的入口如下。现成目录不允许覆盖；新的独立输入必须使用新输出目录与 label。这是数据定义，不是资源上限。

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_bundle.py prepare-run --condition-id proton-T04 --seed 61017041 --events 1 --label cgoal-s2-proton-p100-a0-seed61017041-r1 --output local_runtime/dram-see-v4/continuous/proton/s2-transport-p100-a0-seed61017041-r1
```

该命令已执行成功，不应为重现日志而再次创建同目录。主代理按原 owner/锁，将这一个包复制到 `local_runtime/dram-see-v4/transport-probe/inputs/<label>/` 后使用原 operation 调度；原运行程序会先做 `Initialize`、`BeamOn(0)`、材料/几何核验，再运行事件。若需独立初始化包，入口支持 `--initialization-only`；当前未额外生成重复包。既有任务断连后只用原 label 查询和收集。

```powershell
python -B experiments/dram-see-v4/transport-probe/operation.py cgoal-s2-proton-p100-a0-seed61017041-r1 local_runtime/dram-see-v4/transport-probe/inputs/cgoal-s2-proton-p100-a0-seed61017041-r1
python -B experiments/dram-see-v4/transport-probe/operation.py status cgoal-s2-proton-p100-a0-seed61017041-r1 --json
python -B experiments/dram-see-v4/transport-probe/operation.py collect cgoal-s2-proton-p100-a0-seed61017041-r1 --json
```

上面的调度/查询命令仅供主调度执行，本次未执行。开发准备入口只开放原矩阵中的 S2 train：T03 (50 MeV,0°)、T04 (100 MeV,0°)、T06 (100 MeV,30°)，seed 必须出自该条件记录。I02 (50 MeV,30°) 也属于最终留出，E01 (150 MeV,0°) 属于最终能量留出；它们不会被重标为训练。只读真实证据审计与准备入口分开，前者允许最终阶段审计原 S2 留出证据，仍输出 `final_holdout=true` 和 `never_for_tuning`。S1/S3 要使用未来实际 D3 几何及相符的原编译包，当前实现拒绝假用固定 S2 几何。

## 一个原生事件生成一个源包

仅在原操作完成、原始退出成功且归档完整收集之后运行：

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_bundle.py bundle --operation local_runtime/dram-see-v4/transport-probe/operations/cgoal-s2-proton-p100-a0-seed61017041-r1 --event-id 0 --build local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-build-20261017t043911z --output local_runtime/dram-see-v4/continuous/proton/s2-p100-a0-seed61017041-event0-source-r1
```

源包沿用 `couple.py` 的原文件：`sources.dat`、`source-contract.json`、`fragments.json`、`heavyion.physics.inc`、`source.par` 和 Plot/CurrentPlot 片段。新的包加上 `geometry-contract.json`、`event-binding.json`、`source-bundle.json`、`data-input-suggestions.json`、`source-reference-pre-clock.json`，只写一个包。结构零源事件仍有原事件身份和完整分母，不能因没有正 Si 沉积而删除。

`source-bundle.json` 的 schema 是 `continuous-proton-source-bundle-v1`；`binding` 的 schema 是 `continuous-proton-native-event-binding-v1`。供 `data/source_bridge.py` 重新审计的接口为：

```python
from pathlib import Path
import source_bundle

original_build = Path(recorded_bundle['binding']['build_operation']['path']).parent
actual = source_bundle.audit_transport_event(original_operation, event_id, build=original_build)
assert actual == recorded_bundle['binding']
```

必须沿用记录的原 build 路径，不选择以后新的编译包。审计重新读取原 operation v2 receipt、归档、所有提交输入、二进制、请求和原编译归档；保留原 SSH 退出，不把恢复收集误写成原 SSH 成功。核对原生束流方向/表面点/发射点、单线程、原几何探针与 overlap 结果、所有原事件 ID 和全批次分母。对所选事件的全部 tracks/steps/birth-links 重新构建祖先图：唯一原初质子、exact birth token、父 step、每步全部次级枚举、完整 step 序号、实际 hadronic 状态、轨迹/事件能量账。不是读取手填的 `passed=true`。

能量账采用原输运审计的 `1e-12 MeV + 1e-9 relative` 浮点闭合容差；束流重建的 `1e-12` 只覆盖17位输出/三角运算舍入（位置单位 µm，方向无量纲），不是放宽物理位置条件。保留零弦长和晚次级，不要求事件有核反应，不用 `edep <= 初级动能` 代替核事件能量核算。这里只验记录闭合，不宣称逃逸/静质量总能量平衡或统计输运收敛。

`data-input-suggestions.json` 为两个 stored_bit 给出同一事件 group 的身份建议，明确未注册。实际 TCAD 输入还需要成功 D3 几何合同、`physics_manifest_sha256`、`circuit_contract_sha256`、注册后的 data-input hash；不能从建议填造这些身份。原 source-spec schema 为 `continuous-particle-source-spec-v1`，particle=proton，实际角色 SIGNAL 或 STRUCTURAL_ZERO，另绑定 stored_bit、physics/source-contract/data-input hash。匹配 CONTROL 使用相同 mesh/physics/circuit 和真实无源运行。

## 有限 Si 电荷、时钟与原生场

源转换保留原核 w=0.03 µm、sigma=2 ps、3.6 eV/电子空穴对，所有正 Si 电离沉积使用 `edep-NIEL`。`source-reference-pre-clock.json` 使用独立 `source_reference.py` 积分真实 Si/SiO2/GateVoid 边界，并以四分之一数值容差重算；它没有原生时钟，仅是运行前参考。全空间分配电荷与有限 Si 电荷分别保存，不重归一尾部，也不把离线参考当原生场积分。

TCAD 的 `required_source_window_s` 必须覆盖全部源的 `[min(t0)-8sigma,max(t1)+8sigma]`。对 sigma=2 ps 的质子，起点约为14.984 ns 加真实飞行时间，不能继承 α 的14.9984 ns。源期 BE 最大步长0.4 ps、加密0.2 ps只是待验证设置；必须读取实际接受步，再检查原生 HeavyIon 场和时间细化。超过当前电路收集终点19.9 ns的晚沉积保留在分母中并标记不可表示；定义延长的匹配电路与度量窗口之前不得裁尾纳入资格。

真实 SDevice 运行后，用完整所需窗口提取原生接受 BE/TDR，再生成带实际时钟的独立参考。以下占位路径必须替换为真实原运行/输出，窗口必须取该事件 source-contract；零源使用 `--structural-no-source`。

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_clock.py --run ACTUAL_SOLVER_RUN --window ACTUAL_TMIN ACTUAL_TMAX --output NEW_CLOCK.json
python -B experiments/dram-see-v4/continuous/proton/source_reference.py --source BUNDLE/sources.dat --geometry BUNDLE/geometry-contract.json --clock NEW_CLOCK.json --output NEW_REFERENCE.json
```

原生场提取复用 `continuous/data/field_adapter.py`，每 ROI 字段为 G/XG/YG/ZG/ONE，载流子另保留 eDensity/hDensity。G 的体积分单位 `cm^-3 s^-1 um^3`，空间矩为 `cm^-3 s^-1 um^4`，ONE 为 `um^3`；数据端与 `source_compare.py` 接线，不重复创建 adapter。随后核验场/标量积分、波形、ROI、质心、匹配 A0、双载流子响应、LET/时间划分、网格与实际 BE 细化，才能讨论 HeavyIon 源资格。

本阶段6项新增定向检查通过，日志为 `local_runtime/dram-see-v4/continuous/proton/source-bundle-tests-r2.log`；祖先链/束流样例明确是单元测试构造数据。当前 bundle 原生转换尚无真实事件可执行，所有结果仍为 `native_source_qualified=false`、`pmi_r12_fixed=false`。HeavyIon 后续成功也不会证明 PMI/R12 的实际 BE/APD 接口已修复。
