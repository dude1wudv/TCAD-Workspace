# Geant4 初始化与事件记录审计

`audit_transport.py` 只读本地已完成的v4运行证据，不执行SSH、安装、编译、粒子仿真、TCAD或训练，不改旧数据、源代码、合同或运行账本。只有显式 `--output` 才在v4审计子目录写 `audit.json`。

```powershell
python -B experiments/dram-see-v4/transport-probe/audit_transport.py init local_runtime/dram-see-v4/transport-probe/runs/init-h-r2 --output local_runtime/dram-see-v4/transport-probe/audits/init-h-r2
python -B experiments/dram-see-v4/transport-probe/audit_transport.py events <已完成运行目录> --output <v4审计子目录>
```

Python接口：`audit_init(run_dir, output=None)`、`audit_events(run_dir, output=None)`。CLI成功返回0，失败或证据不完整返回1；报告包含每项检查、失败原因、输入输出哈希、原始库存及描述性统计。不得依据进程已退出或目录存在代替本审计。

## 证据合同

运行目录使用 `collect_record.py` 导出的 `record.json`，schema为 `dram-see-v4-transport-run-v1`。其中 `mode` 为 `init`／`events`，原始 `request.mode` 则为 `init`／`thin`。运行attempt可使用新ID，冻结request的label与参数仍须在 `probe-contract.json` 中；例如修复后的 `init-h-r2`仍绑定原`init-h-r1`请求。

- `runner_exit_code`是同步SSH包装进程的真实返回码，不能冒充另一份独立求解进程退出证据；`remote_exit_code`再次对照原始 `exit-code.txt`；`collection_exit_code`是实际归档传输返回码。三者都必须为整数0，null、字符串、布尔和非零均拒绝。三值还须与 `operation_evidence` 指向的原始operation记录一致。
- `input_sha256`和`output_sha256`列出的本地文件逐个重算。`raw_archive`指向原始结果tar：重算整体哈希，拒绝穿越路径、链接、特殊成员及重复文件，不解压，并将归档的完整文件清单及每份内容哈希与导出文件比对。输入副本仍必须保持原值。
- `provenance_files`绑定实际二进制、环境脚本和数据库存。存在本地二进制时直接重算；若只有远端hash见证，报告明确区别。C++源快照也须在冻结输入中。这里核查编译产物和源快照的归档关联，不重新编译。
- 数据库存需有对应环境变量、版本目录、正文件数与字节数及内容清单哈希。H臂核查EMLOW7.13、ENSDFSTATE2.3、PhotonEvaporation5.7、PARTICLEXS3.1.1；E臂核查前两者。环境脚本路径与库存一致。审计不重新读取远端数据字节，也不将G4NDL或RadioactiveDecay列为普通QGSP_BIC的共同必需项。
- `run.sh`保留共享锁及affinity设置；`affinity.txt`包含原始 `/proc` 的 `Threads: 1`和单CPU列表。结合实际metadata中的串行 `G4RunManager`验证资源约束。

## 初始化门槛

`Initialize()`后还需合法的 `BeamOn(0)`建立物理表；它不生成初级事件。实际metadata必须记录Geant4版本号1073、`Initialize_then_BeamOn_0`、串行manager及固定几何/单位。status最终必须为COMPLETED、initialized、physics_tables_built、zero_event_beam_on_called均true；init的事件、轨迹及步记录总数必须全部为0，且未调用非零事件BeamOn。

`constructors.csv`及`processes.csv`记录实际库存，初始化phase为`post_zero_event_init`；thin结束再有`post_events`。每个phase只允许一个电磁构造器，其实际名必须为 `G4EmStandard_opt4`。质子`hIoni`必须唯一；H臂的`hadElastic`和`protonInelastic`必须唯一、类型为强子过程且有实际注册模型；E臂不得有强子过程或模型。

`cuts.csv`必须有G4_Si和G4_Galactic中的gamma、e-、e+、proton范围阈值和非空、正的能量阈值；缺表不能通过。范围阈值为冻结的0.01µm。模型范围只报告实际注册的全局能区，不宣称已验证材料/同位素覆盖或物理准确性。标准QGSP_BIC的10µs中子tracking cut保留并明确计数，不当作自定义筛轨缺陷；超过该截断的延迟历史不在本次范围内。

## 事件与轨迹门槛

首轮 `events_requested=2`，事件ID必须连续为0、1，包括完全没有硅电离的事件。每事件一个原初质子，track1且parent0，出生能量、位置、方向和时间与冻结请求一致。request种子、几何哈希、方向、单位和实际metadata均对齐。显式miss测试必须没有硅步及硅电离。

`tracks.csv`与`steps.csv`覆盖所有材料中的轨迹和步，包括零沉积步。审计检查父轨迹存在、母子图无环、creator身份、轨迹步号连续、时间/位置/动能链及体积—材料对应；按全域、Si、World分别加总总沉积、NIEL和电离分量，再与轨迹、事件和status统计核对。负值、非有限量、NIEL超出总沉积或分量不闭合都失败。

核谱系标志在审计输出中按creator的Geant4强子过程类型及母链派生，命名为 `creator_lineage_has_hadronic`。它与“原初质子已经发生强子相互作用”不是同一概念：track1在首次强子步之前、当步及之后的硅电离另行核对。原初质子核作用后的电磁次级不能仅凭track_id或非零parent_id就改称直接核产物。强子计数包含弹性及非弹性过程，输出保留过程名，不把两者合成未经区分的反应概率。

报告给出粒子种类计数、强子creator轨迹数、强子相互作用步数、零硅电离事件数、中子tracking-cut终止数、逃逸轨迹动能及硅电离量。逃逸动能是描述量；不使用“总沉积不超过初级动能”的旧上界，也不声称已完成静质量、激发能及逃逸项的完整核质量—能量守恒。

## 冻结的记录算术容差

| 项目 | 容差 |
|---|---|
| 能量分量／加总 | `1e-12 MeV + 1e-9 × max(abs(a),abs(b))` |
| 时间链 | `1e-9 ns` |
| 位置链 | `1e-9 µm` |
| 单位方向的平方范数 | `1e-10` |

这些仅为CSV精度和加总检查，不是cut、最大步长、TCAD网格或时间步的收敛标准。少量固定事件不估计粒子概率；没有核事件时如实报告0，不自动增加事件或搜索种子。

## 本地开发证据

`local_runtime/dram-see-v4/transport-probe/audit-dev/test_audit_transport.py`含12项软件检查，制造夹具仅用于解析、缺失/损坏记录和判定逻辑；不计入Geant4结果。首次真实兼容检查位于同目录 `first-real-init/`，保留检查前源码快照及H/E初始化结果；原失败初始化也保留其拒绝结果。后续真实事件的准入仍需独立验证及主代理放行。
