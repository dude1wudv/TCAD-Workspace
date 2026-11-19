# Geant4 10.7.3 初始化与质子记录探针

`transport_probe.cc` 是独立 v4 实现，参考 v1 几何但不修改旧源码、二进制或数据。不产生 TCAD 源，也不把全部沉积折成均匀 LET。编译、安装、SSH 与真实运行仅由主代理通过现有串行锁和单核策略调度。阶段1大矩阵不是本轮自动运行授权；本轮请求以主代理的 [probe-contract.json](probe-contract.json) 和 [run-plan.md](run-plan.md) 为准。

## CLI 与初始化门槛

```text
transport_probe init|thin H|E energy_MeV angle_deg seed events [miss=0|1]
```

能量只接受 1、5、20、100 MeV，角度只接受 0°、30°，seed 是正整数。`init` 必须 events=0、miss=0；`thin` 必须 events≥1。未知参数、已有输出或已有预约文件非零退出；不能在同一目录重发。每次运行必须使用独立目录，`probe-reservation.lock` 在成功和失败后都保留。

初始化采用 `G4RunManager::Initialize()` 后调用 **`BeamOn(0)`**。Geant4 10.7.3 将此视为 fake run，仍建立物理表，事件循环为零次：

- [G4RunManager.cc](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/run/src/G4RunManager.cc) 的 BeamOn、RunInitialization、DoEventLoop 路径。
- [G4RunManagerKernel.cc](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/run/src/G4RunManagerKernel.cc) 的 RunInitialization、UpdateRegion、BuildPhysicsTables 路径。

程序要求 G4_Si 与 G4_Galactic 各自 gamma/e-/e+/proton 四种 production-cut 能量阈值均存在且为正、range cut 为 0.01 µm，才设置 `physics_tables_built=true`。初始化模式另禁止调用用户 GeneratePrimaries，要求事件、轨迹和步骤计数均为零。初始化完成不能代替 hadronic 模型在目标材料/能区的物理准确性验证。

`init` 的 `beam_on_called` 与 `zero_event_beam_on_called` 为 true，但 `nonzero_event_beam_on_called` 为 false；这表示合法的零事件建表。`thin` 也先通过同一零事件门槛，再调用请求的正事件数；没有自动用一个粒子事件弥补初始化失败的分支。

## 两臂与几何

H 臂采用 QGSP_BIC，然后在 PreInit 以 `ReplacePhysics(new G4EmStandardPhysics_option4(...))` 替换电磁构造器；E 臂只有 Opt4 电磁构造器。两臂都只注册一次 `G4StepLimiterPhysics` 并显式保持 charged-only。替换 API 依据 [10.7.3 G4VModularPhysicsList.cc](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/run/src/G4VModularPhysicsList.cc)，最终以构造器及实际 process 清单核验，不能只看请求名称。

H 保留参考列表默认的 `G4NeutronTrackingCut`，中子 10 µs 时限在 metadata 中声明。每次实际 `G4NeutronKiller` step 和结束的 track 都单独计数。没有新增按沉积量、粒子种类或存储响应筛除轨迹的用户杀轨。E 的 Opt4 仍含核阻止/NIEL，因此 E 的含义是无强子反应的电磁基准，不能称完全没有核阻止。

硅体积名 `Si`，材料 G4_Si，边界 x=[0,0.85]、y=[0,1.2]、z=[−0.5,0.5] µm；真空世界名 `World`，半边长10 µm。正常束源为 `(0.7+0.001*tan(theta),-0.001,0)` µm，方向 `(-sin(theta),cos(theta),0)`。`miss=1` 将表面 x 改为 −5 µm，保持方向和发射补偿，作为确定性的零入硅诊断，不是真实辐射事件概率样本。

production cut=0.01 µm；Si 内最大带电 step=0.02 µm。前者是次级产生阈值，后者是空间步长上限；production cut 不是低能 track 的统一停止条件。两者也都不是新尺寸器件已经收敛的证据。

## 输出与物理含义

所有 CSV 数字采用17位有效数字，文本按标准 CSV 引号转义。事件编号从0开始；每事件一个初级质子，通常 track_id=1、parent_id=0；step_id 取 SDK CurrentStepNumber，从1连续。元数据 schema 为 `v4-transport-probe-r1`。

| 文件 | 内容与边界 |
|---|---|
| metadata.json | 请求、实际 Geant4 版本、随机引擎与 seed、串行 run manager、坐标/材料域/单位、cut/step、标准中子时限、初始化方式 |
| status.json / status-history.jsonl | 当前状态与阶段历史、请求/完成事件数、全部完成 track/step 数、零/正事件 BeamOn 调用及建表标志；异常保留 FAILED，Geant4 直接中止时可能停在上一阶段，必须结合外层退出码 |
| events.csv | 每个初级事件一行，保留零入硅沉积；全部/Si/World 的 total、NIEL、ionizing；轨迹/步计数、hadronic 步、原初首个核过程位置、标准中子截断计数与完成状态 |
| tracks.csv | 全部 track 的出生和结束粒子/PDG/Z/A/质量/电荷、parent、creator process/type/subtype、KE/位置/方向/时间/体积/材料，以及步数/沉积/状态；最终结束顺序不等于track编号顺序 |
| steps.csv | **World 与 Si 全部步，包括零沉积步**；pre/post 位置/方向/KE/时间/体积/材料、步长、total/NIEL/ionizing、post-step process/type/subtype，以及原初核状态和中子截断标志 |
| constructors.csv | SDK 实际构造器名称及 physics_type；Opt4 的实际名称可能为 G4EmStandard_opt4 |
| processes.csv | 所有已定义粒子的实际 process 名称/type/subtype及强子模型数 |
| hadronic-models.csv | 各强子 process 的模型名称与全局最小/最大能量；不声称已逐材料核验模型适用范围 |
| materials.csv / elements.csv | 实际材料密度、温度、状态、组分及原子密度 |
| cuts.csv | 实际 material-cut couple 的四类 range/energy threshold 和可用标记；空表或缺关键能量阈值不通过初始化 |

清单 phase 为 `post_zero_event_init`；thin 完成后再追加 `post_events`，以包含事件运行时新建的离子定义。成功 init 只有前一个 phase，三个粒子记录 CSV 只有表头。

单步 `ionizing=max(0,total_edep−NIEL)`，按 **pre_volume** 记沉积。出世界边界的 post_volume 为 OUTSIDE、post_material 为 NONE，边界步不丢弃。没有用 primary KE 作为含核反应事件总沉积上界；此处只提供分步/分轨迹/分材料账目，不声称包含反应静质量/Q值和逃逸能量的完整全局守恒证明。

`primary_hadronic_seen_before/after` 表示该事件原初质子是否已经历 type=fHadronic 的步骤，并按实际记录顺序更新。`si_ionizing_primary_at_or_after_hadronic_MeV` 包含该相互作用当步；连续能损与步末核相互作用同一步时，此字段不是精确时刻分解。它与 creator 祖先链不是同一个标签。核后代应由 `parent_id` 与 `creator_type/subtype` 重建；δ电子不能统称核次级。

程序只保留完整事件记录，不挑选核反应、重沉积或漂亮轨迹。两个物理列表即使用相同seed也不构成逐事件核贡献差分。若本轮没有核事件，按事实报告，不能据此否认已注册的机制，亦不自动扩大搜索。

## 验证交接

本文件最初交付仅完成针对10.7.3头文件与官方源码的 API 核对和静态输入审阅，未由实现代理编译或运行。主代理复制冻结源码后执行真实编译；编译失败需保留原日志并将诊断回传，由唯一源码写入者修复。二进制/环境/数据/源码及准确命令的哈希由外层调度归档，不以程序 metadata 代替这些证据。

成功最终标记为 `TRANSPORT_PROBE_COMPLETED mode=... arm=... events=... tracks=... steps=...`。仍必须同时检查外层退出码、实际 events 分母、CSV闭合和过程清单；标记或文件存在本身不足以验收。
