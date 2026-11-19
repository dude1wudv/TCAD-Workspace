# 厚硅核机制记录实现

这是独立的 Geant4 10.7.3 机制见证程序。冻结输入与次数以同目录 `witness-contract.json` 为准；不修改薄硅 `transport-probe`、v3 或 TCAD 工程。10 mm Si 立方体置于 40 mm 真空 world 中，100 MeV 质子从 `(0,-5001,0) um` 沿 `+y` 入射；硅边界为三轴 `[-5000,5000] um`。它不是 DRAM 模型，输出不用于估计截面、事件率或 TCAD 响应。

## CLI 与运行权责

```text
transport_witness init|witness H|E seed events
```

`init` 只接受 `events=0`；`witness` 要求正事件数。生产运行必须再由主调度者按冻结合同核对完整请求，CLI 本身不提供追加事件或自动重试功能。当前目录必须无既有结果，`witness-reservation.lock` 在成功和失败后均保留，禁止覆盖重跑。

H 使用 `QGSP_BIC`，通过 `ReplacePhysics(new G4EmStandardPhysics_option4)` 替换电磁构造器；E 只注册 Opt4。两臂均注册一次 charged-only `G4StepLimiterPhysics`。production cut 为 10 um，Si 带电粒子最大步骤为 100 um，未强加中子步长。保留参考列表标准 10 us 中子追踪时限，未新增用户杀轨、权重或偏置。

初始化执行 `Initialize()` 后调用 `BeamOn(0)`。10.7.3 将零事件视为 fake run，但仍执行建表；事件循环没有迭代。程序随后要求 Si/World 对 gamma、e-、e+、proton 的实际能量 cut 表存在且为正，确认全部计数为零后才输出 `INITIALIZATION_COMPLETED`。`witness` 此后才调用正事件 `BeamOn`。最终标记为 `TRANSPORT_WITNESS_COMPLETED`；异常返回 2，并尽力保存 `FAILED` 状态和已有记录。

Geant4 官方实现依据：[G4RunManager.cc](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/run/src/G4RunManager.cc)、[G4RunManagerKernel.cc](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/run/src/G4RunManagerKernel.cc)。源码只实现求解程序；编译、SSH、运行、归档由主代理复用已有唯一串行调度器完成。

## 原始记录

保留 `events.csv`、`tracks.csv`、`steps.csv`，所有实际输运轨迹、World/Si 步骤、零沉积步骤及零沉积初级事件都写出。能量单位 MeV，长度 um，时间 ns；浮点输出 17 位有效数字。每步记录 total edep、NIEL 和 `max(0,total-NIEL)`，不设“沉积不得大于入射动能”的核事件断言。

`birth-links.csv` 每个次级轨迹一行，列为：

```text
event_id,birth_token,parent_track_id,parent_step_id,secondary_ordinal,child_track_id,
creator_process,creator_type,creator_subtype,parent_hadronic_before,parent_hadronic_after
```

在 `UserSteppingAction` 从 `GetSecondaryInCurrentStep()` 为实际 secondary 对象建立 `e<event>:t<parent>:s<step>:n<ordinal>`。`G4EventManager` 分配 track ID 后，`ClassifyNewTrack` 使用同一对象身份绑定 childTrackID；不输出内存地址，不按位置、时间或粒子能量匹配。事件结束若有未绑定对象或未结束轨迹则失败。`ClassifyNewTrack` 始终返回 `fUrgent`。Geant4 production cut 内部未形成可输运 track 的过程产物不被伪造为轨迹；其局部沉积以实际步骤量为准。

这一生命周期可由官方 [G4EventManager.cc](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/event/src/G4EventManager.cc) 的 `StackTracks` 和 [G4SteppingManager2.cc](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/tracking/src/G4SteppingManager2.cc) 的 secondary 处理核对。

`tracks.csv` 新增稳定 token、母产生步骤与以下独立标签：

- `direct_hadronic_child`：自己的 creator type 为 4。
- `creator_lineage_hadronic`：自己的 creator 或任一母链 creator type 为 4。
- `em_from_hadronic_lineage`：自己的 creator type 为 2，母链包含 type 4 creator。
- `em_from_post_hadronic_primary`：由原初轨迹的 EM 过程产生，母轨迹在本步骤开始前已有核作用。
- `em_in_primary_hadronic_transition_step`：由原初 EM 过程产生，与母轨迹首次核作用发生在同一步；不声称 EM 产生严格晚于步骤末核作用。

`steps.csv` 新增 `track_hadronic_before/after`、`secondary_count`、`pre/post_step_status`、`chord_um`、`deposit_kind` 和 `local_ionizing_MeV_per_um`。后者仅是当前离散步的电离沉积除以实际路径长度，不是无限制 LET 或质量 LET。零长度有沉积时保持点记录，比例字段留空，不补假长度；路径非零而端点重合单列 `point_zero_chord`。路径与端点弦长分别保留供将来分析，程序不生成 TCAD 线源。

终止记录包含末步定义过程的 name/type/subtype 和 `termination_reason`：`reference_neutron_tracking_cut`、`escaped_world`、`natural_stop_or_absorption`、`hadronic_termination` 或 `unknown`。末步定义过程不保证是所有 AlongStep 能量损失的唯一原因。自然停止标签仅表示终态动能为零且在世界内；未知情况保留原始状态，不归并成正常停止。

`processes.csv` 的 `is_neutron_killer` 由实际 neutron PDG 2112 与 SDK `G4NeutronKiller` 类型确定。审计核对实际 name/type/subtype 组合和初始化清单，参考值为 type 7/subtype 403；不要求过程名含 `neutron`（实际名可为 `nKiller`）。原始 constructors、processes、hadronic-models、materials、elements、cuts 的清单保留初始化后与事件后两阶段。

## 独立审计与离线测试

```text
python -B experiments/dram-see-v4/mechanism-witness/audit_witness.py init <receipt_dir> --output <audit_dir>
python -B experiments/dram-see-v4/mechanism-witness/audit_witness.py events <receipt_dir> --output <audit_dir>
python -B -m unittest discover -s experiments/dram-see-v4/mechanism-witness/tests -v
```

不提供 `--output` 时只读审计并打印报告。receipt 使用 `record.json`，schema 为 `dram-see-v4-witness-run-v1`，`mode=init|events`；内部 `request.mode=init|witness`。请求必须完全匹配冻结合同，几何内容 hash 重新计算。保持旧 adapter 的原始 operation、tar 归档、退出码、输入/输出 hash、可执行文件、源码、数据与环境绑定，并要求新 CSV、elements 和状态历史都在原始 hash 清单内。实际 source 为 `transport_witness.cc`，binary 为 `transport_witness`。

审计拒绝未知/非零退出码、来源不一致、未完成事件、母链循环、缺失绑定、重复 token、错误母产生步骤、错误 creator 分类、能量求和不闭合、步骤链断裂、伪造点沉积长度、SDK nKiller 身份不符。物理库存要求唯一 Opt4、H 的真实 hadElastic/protonInelastic、完整能量 cut 表；E 不允许 type 4 注册。

`mechanism_summary.qualifying_witnesses` 给出每条满足条件的 `protonInelastic` 产生步骤、直接子轨迹、可追溯全部后代及其正 Si 电离沉积。同一程序运行内按 event ID、parent track ID、parent step ID 排序。跨运行的首例选择由主代理按冻结 requests 顺序（含 pilot）执行，不因发现见证而删除后续合同事件；未发现见证也不触发增样。报告保留全事件分母、终止分类、点沉积分类和 lineage 标签计数。

已运行 18 项纯离线测试，全部通过；夹具明确为 synthetic，不代表真实 Geant4 结果。覆盖稳定绑定错误、遗漏步骤/事件、核后代与原初作用后 EM 混淆、终止误分类、点沉积比值伪造、实际 `nKiller` 分支与未知/非零退出码。主代理回报首版已在 GCC 10.2 / Geant4 10.7.3 编译通过；子代理曾只读试审 H/E 零事件原档通过，正式审计与后续真实事件验收由主代理保存。

适用边界：审计是来源、记录和算术验证，不是强子模型校准，也未封闭静质量、核激发、逃逸能量与晚中子的总能量账。10 um cut 和 100 um step 是本次厚靶诊断条件，不是 DRAM 源映射的分辨率依据。H/E 是分布层面的对照，不能把不同随机历史逐事件相减。
