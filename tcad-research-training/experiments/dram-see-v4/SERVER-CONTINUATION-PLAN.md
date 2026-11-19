# DRAM SEE v4：服务器接续计划

更新：2026-10-21。本文件是暂停后的接续计划，不是课程完成验收。

用户最新要求“尽快让当前任务结束，收尾”。本机停止自动推进及一切新原生任务；当前正常仿真保留原 runner/owner/共享锁，不杀进程、不清锁、不重投。它尚未收集，后续应先恢复原作业收集。完整课程未完成，Goal 在本轮交接后暂停，不建立定时任务。

**接续时首先读取 [当前原作业收尾状态](LOCAL-CLOSEOUT-STATUS.md)。** 机器记录在 `local_runtime/dram-see-v4/continuous/local-closeout/status.json`；它的 RUNNING 是最后实际观察，不代表服务器接续时仍在运行。

## 1. 已知事实与未完成项

| 状态 | 实际证据与边界 |
|---|---|
| 真实完成 | D2-r8 DC：`20261017T051217Z-v4-continuous-b1-d2-r8`，原二维网格 SHA `53f384abfffe7156302df49ae8b2aa50009a2c65dbac953081beb09784854484`。原 g80、SN87、20 nm 等效宽度。 |
| 真实完成，但不是完整资格 | 原两 bit 全 0–88.2 ns 写入、保持、预充、读出及每接受 BE 的 KCL 已有真实结果：`20261019T193936Z-v4-2d-a0-g80-2p4v-main-b{0,1}-r1`。读出裕量约 53.928/47.765 mV。 |
| 真实失败，保留 | 旧 dt2 bit1 的完整波形比较：SN 最大差 1.709306 mV、BL 5.140344 mV，超过原 1 mV；端口总电荷差 1.6300823% 满足原 2%。不能只取通过项。见 `analysis/a0-g80-alpha-window-dt2-b1-r1/`。 |
| 真实失败，保留 | 旧 175 段 A0 功能检查通过，161 源 BE 最大 19.8757765101 fs；但 322 次源 TDR Writing 最终仅剩 2 个文件。固定 source_index exit 1。见 `analysis/a0-g80-source-subsegments161-main-b1-r1/`。 |
| 正常运行，未验收 | 当前 176 段、每源段唯一前缀的 A0 main-b1，见独立收尾状态。尚无终态退出、收集归档或新版完整源帧证明。 |
| 真实 α 诊断，资格未通过 | 旧 α E5/0° 实际运行与场提取已收齐，G 单位及电荷账有证据；实际源时间步 56.1700042 fs 超过 40 fs。不能称源时间收敛通过。 |
| 真实 Geant4 输运与输入数学 | T03/P50/0°、T04/P100/0°各 4 个独立事件，各保留 2012 steps。两批共 **8 observed primary**。新有限 Si/20 nm 投影、全窗 PMI 输入及短窗九量数学已完成；源电荷不是 Qcol。 |
| 仅请求/准备 | T06/P100/30°有原 4-primary 请求和完整原输入，已原字节暂存，**未提交、未观察事件**。12 是 T03/T04/T06 的已知请求总数，不能写为 12 个实跑事件。 |
| 仅编译/静态兼容 | PMI 原库 `4d6c4f2102a900a8a276e8c05b6d25a3685bf8a6f1b721593b8171dd53cd290a` 已有编译与接口证据，尚无相应实际 SDevice PMI 激活/完整场资格。PMI/R12 仍未证明修复。 |
| 代码已接线，科学工作未完成 | 新 A0、α、质子源帧及学习/受控演示模块有封存检查与审阅。qualified=0、fit=0、固定模型/数值预测=0；演示保持 PENDING_FROZEN_MODEL。 |
| 保留失败的可选分支 | 恢复后缀的完整电学等价检查失败；不能拿局部通过作重启复用依据。完整 3D TCAD 电学是未通过的可选扩展，不是二维结果已替其通过。 |

本表的 `analysis/` 均相对 `local_runtime/dram-see-v4/continuous/`。权威原始引用见该目录 `coordination.json` 和各 handoff；旧失败、旧预算、冻结包与验收原件全部保留，不恢复旧队列。

## 2. 当前原作业：先恢复收集，不再次 run

- Run ID：`20261021T004925Z-v4-2d-a0-g80-2p4v-waveform-frames161-main-b1-r1`。
- 本地原记录：`local_runtime/runs/<Run ID>/manifest.json`；终态原件应为该目录 `manifest.json`、`inputs.tar`、`results.tar`，尚未收集的归档 SHA 不预填。
- 原远端目录：`/srv/tcad-dram-see-v4/runs/<Run ID>`。
- wrapper PID `102071` / start ticks `25679406`；SDevice PID `102162` / start ticks `25680306`；boot ID `ed9b6579-cd76-45c0-8242-a3bcec06b401`。
- 远端 wrapper SHA：`2cd66d0cb0fe40ed9ee8aabbc77cc9bf45bffacf58005112555a0609da85af88`。
- 当前原 input-manifest：`ae12d3f9447f929a3437df01aa4b56c3e80345fcddf5cc9656b2877f04265071`。
- 原 runner：`scripts/tcad.py`，SHA `d462e4ddbbcd18999ebf7beccf66d2f1c046b2b9dbac41e1df6d111f40193c24`；原 operation：`experiments/dram-see-v4/transport-probe/operation.py`，SHA `95613896f92a9569e39dc7d67767f228d89f7f13c812d28439ce24ea1187012d`。
- 原 owner 入口：`experiments/dram-see-v4/nuclear-closure-r1/supervisor.py::ownership`；本地 `local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/continuation/owner.lock` 是 Windows 单字节锁，不保存 owner 姓名或 PID。不能仅凭锁文件存在推断持锁者。
- 原共享锁：`<SIM_USER_HOME>/research-training/.solver.lock`；原控制根 `<SIM_USER_HOME>/research-training`，数据根 `/srv/tcad-dram-see-v4`。既有正常作业保持单核、数值线程 1。

在原 Windows 工作区运行以下**查询**；它只观察原作业并保存真实身份/时间/用量：

```powershell
& 'C:\Users\sun\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\python.exe' -X utf8 -B local_runtime/dram-see-v4/continuous/actual-usage/observe-a0-waveform-frames161-main-b1-r1.py
```

确认终态后，若原 manifest 尚未表明 COLLECTED 且 collection_verified=true，沿原工具收集一次：

```powershell
& 'C:\Users\sun\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\python.exe' -X utf8 -B scripts/tcad.py collect 20261021T004925Z-v4-2d-a0-g80-2p4v-waveform-frames161-main-b1-r1 --json
```

断连先定位上述原目录、身份和原状态。已收集则复用；未明确终态则不重提。PID 或 boot 不符时保留中断证据，不能把旧 PID 当新进程。不要删除、覆盖或移动原档来“恢复”。

收集后必要本地整理：核对真实 native/remote/SSH/collect 退出、输入和归档哈希、完整时钟、所有接受/拒绝/零时间事件、322 次预期源帧 Writing 与实际唯一文件对应、写/保持/预充/读/KCL。使用当前 `continuous/data/source_segment_frames_baseline_2d.py`（SHA `0c789b704c82c52f1e1e8b51e7a4d082b6e9fa2df0f4b0c96bfecd0eefa3b317`）生成新输出，不能覆盖旧减缩结果。此本机收尾**不启动 SVisual/字段提取、dt2、h2、粒子或其他新原生任务**。

## 3. 新版本的精确输入与入口

当前实现入口和原件按下列 handoff 定位；它们是接续候选，不是自动队列。

| 用途 | 现成输入/封存引用 |
|---|---|
| α 窗 A0 | `control-transition-r14-2d/source-segment-frames-a0-implementation-r1/projects/20261021T004925Z-v4-2d-a0-g80-2p4v-waveform-frames161-<variant>-b<bit>-r1`；main-b0 `f4b81a81db1dead42078798a0bed18b820e5f6e5e86e9fc748ba2ad5ebef11e3`；当前 main-b1 `ae12d3f9…`；dt2-b0 `4ac2147fee8a0c9e2daeb553e005efacb3442556ed22cee4c998334872852785`；dt2-b1 `a3636d04efafbe132541795be1cd14214837958132171d78e06d2218ab7f776f`。四套已 prepare，只有当前 main-b1 已提交。 |
| α 数值时序 | main `664ddc1fd19f4c3572d417bd6202d53f4165d133c1469cd7891a73c5913ceba2`；dt2 `ec352a05258790ebb9f5f1a2dd82d2dbe8f8fa3623c1207b6f16f0d39f204466`。总 176 段、161 源段。 |
| 质子窗 A0 | `control-transition-r14-2d/proton-source-segment-frames-a0-inputs-r1/handoff.json`，SHA `c66bf637db3ce2a955ab8b2151f35ad7ed1840d4dfa06f1f3504afb3b568e0bd`。四套前缀 `20261021T013221Z-v4-2d-a0-g80-2p4v-proton-waveform-frames1606-`，全部未提交。 |
| 质子数值时序 | main `bd8a1646ac2b2a04ef7f28c076d83f8dee15c56e2849c10ebe5dd4aaa751c9f8`；dt2 `4aea5d9b38696e298281759ec7b35aef82bb71c3dfd1ca8a02ed5797bcc9119b`。总 1621 段、1606 源段；数学窗 76.084–76.1161 ns，PMI 全窗 0–88.2 ns，epoch 76.1 ns 只加一次。 |
| 粒子输入入口 | `continuous/device/prepare_source_segment_frames_case.py`，SHA `a7e7d5defbb92a01ccf35cfafbb13caf6cf03c070f3462ca530e98c77b957058`；A0 保留独立 `source_segment_frames_operating_2d.py` 入口。当前根桥 f783 与当前 A0 封存桥 c9fc 是不同真实版本，不修改旧输入来统一。 |
| T03 新源/九量 | `control-transition-r14-2d/proton-t03-source-segment-frames-packages-r1/handoff.json`；源 manifest `274e7a106bcd1bd6028695f0fa8c96cb2fe211c17e4a137542124006b61fdb35`；新摘要 manifest `f8068598ab1160f5f4e7d0a46e0df58ac9db08c38a83f2205ab3bfa5777d8a68`，见 `proton-t03-source-segment-frames-summary-r1/handoff.json`。 |
| T04 新源/九量 | `control-transition-r14-2d/proton-t04-t06-source-segment-frames-packages-r1/handoff.json`；源 manifest `a3c8af710e8c14774c810898cc7881f0ddd3f704712e40f1f2a34dd39bc0522e`；摘要 manifest `5d5d52fd0cfab801a45c8c42f78427e0e27719ecf9a5d5e321c9f616d7c254aa`。 |
| T06 原输入 | `local_runtime/dram-see-v4/transport-probe/inputs/cgoal-r14-proton-p100-a30-seed61017061-n4-r1`；manifest `8861828e19a40adb59b133a246561272dada7716e9a8d6ebe89f813e7776dec5`。19 文件、385894 B 原字节暂存，未建立 operation、未提交。 |
| 学习登记副本 | `control-transition-r14-2d/source-segment-frames-learning-math-registration-r1/registration.json`，SHA `6e39a23d7d83591335693b70c7bd599575a73aac2839509fe8691fcebce62c67`。已实际消费 T03/T04 两个新数学包，所有训练槽仍 pending。原 registry/plan 未改。 |
| 开发几何准备 | `local_runtime/dram-see-v4/continuous/device/parameterized-d2-next-inputs-r1/projects/` 下 `20261019T200032Z-v4-2d-dc-g70-sn87-main-input-r1` 与 `20261019T200032Z-v4-2d-dc-g80-sn87-h2-input-r1`，仅准备、未提交。 |

除特别注明，表中 `control-transition-r14-2d/` 相对 `local_runtime/dram-see-v4/continuous/`，`continuous/device/` 相对 `experiments/dram-see-v4/`。

## 4. 服务器上的有序待办

1. **恢复收集当前原作业。** 完成本地终态核对，更新收尾状态；保留失败结果。先确认原共享求解已空闲，再讨论服务器接续，不在两个主机重复运行同一身份。
2. **确认环境与连接。** 服务器尚未提供。本轮不安装、不连接。推荐先保留 Windows 控制端及原工程路径，仅迁 Linux 求解端；对原连接/路径/owner机制做显式版本化适配，保持原调度职责和严格 SSH。新硬件兼容由实际证据证明。
3. **新 A0 主线与两 bit。** 对当前 main-b1 完成真实字段提取/单位/帧身份审计；实际匹配 dt2-b1，保留原全波形 1 mV、总 Q 2% 判据。完成新 main/dt2 bit0；获得真实 h2 DC/网格并完成对应 A0 h2 两 bit。α 窗与质子宽窗各守其原时序/来源身份，不用旧结果冒充。
4. **α 实际耦合。** 依真实同条件 A0 生成新 main signal、zero、half、split、h2、dt2；每个需要的场与单位证据都真实提取。保留源电荷五去向、源时钟、端口 Qcol、读出与非线性，half 不预设器件响应线性。
5. **Geant4→TCAD 质子。** T03/T04 复用真实完整事件与新数学；实际运行原 T06 请求并保留全部材料/零步/次级/晚时沉积，未知数量不照抄其他批。随后完成 matched A0、PMI 实际加载、APD/BE/OpticalGeneration 与独立 N/P/单位/场证据，以及 zero/half/split/h2/dt2。只有这条实证链成立才可称 PMI/R12 修复。
6. **开发矩阵。** 先跑 g70 实际 DC/对应网格，沿固定 24 条件设计补齐缺失 T01/T02/T05 及其他所需开发输入、原请求和事件分母；两粒子各六训练条件均完整记账。保留失败、不可表示及 pending，不缩分母，不用合成标签填补。
7. **训练期物理约束与匹配无约束对照。** 真实资格行全部到齐后，沿当前学习入口做相同训练样本、分组、预处理、结构及比较安排的两组训练，只改变所声明物理项。记录真实训练用量及失败，不设置 fit/CPU/调用/训练时间/存储额度。
8. **冻结预测与最终留出。** 固定模型、超参、训练证据和预测输出之后再解封最终响应评分。保留 g90/E7/P150/I01/I02 等原留出安排；尤其 g80/P50/30° 是 proton-I02，不能拿来调优。最终输入允许按原协议准备，但最终标签不参与调优。
9. **预测、外推、演示与交付。** 生成真实输入源条件的预测与外推误差，交付受控自然语言改参→真实输入/固定模型→结果溯源演示、图表、自然语言总结报告、答辩材料、复现命令和完整证据索引。没有固定模型时保留 pending，不生成虚假数值。

## 5. 计算量：角色需求，不是调用额度

当前每个完整**训练响应**要求六类粒子求解：main signal、zero、half、split、h2 signal、dt2 signal。另需 main/h2/dt2 各自 matched A0，故未经跨响应复用时是 **9 个 solver 输出身份/响应**，对应最多 9 个字段提取证据身份。已存在并完全匹配的 A0 可以在服务器阶段审查能否复用；本轮不把可能复用计为已节省任务，也不修改任何判据。

若某质子条件有原请求事件数 `E_c`，两 bit 的响应槽为 `R=2×ΣE_c`，未经复用的 solver 角色数为 `9R=18×ΣE_c`；六类粒子角色本身为 `6R`。这是证据角色计数，不是已执行调用数、预算或允许删减的上限。

- T03/T04 已观察 8 事件→16 响应槽→144 个九角色槽；T06 的 4 个未观察请求另对应 8 响应槽→72 个角色槽。已知请求子集合计 216，全部仍未形成合格训练响应。
- 质子六训练条件的完整公式为 `18×(E_T01+E_T02+E_T05+12)`；三个缺失请求的事件数未知，不能擅填。六个非训练条件的请求/事件数也未全定义，不给虚假的项目总调用数。
- α 每粒子六训练条件预留两 bit 共12条件位槽；目前仅 T03/T04/T06 各一个已知源 identity，能确认的6源事件位槽对应54个九角色槽。其余条件尚缺源身份，不能称已观察响应。
- 原一次 α main 的实际 CPU 约30931 s、旧 A0 main 约14416 s、旧 dt2约21888 s；当前新版 A0 已消耗25972.77 s且仍运行。这些只作已有测量参考，不是新服务器工期承诺或额度。h2、不同事件、提取和新服务器成本尚须实测。

未来可审查同一原 G4 事件在两 bit 间复用输运、完全同身份 A0/数学/静态检查复用，以及独立作业的并行安排。必须先具备新服务器、许可证、内存、owner/锁隔离和来源匹配依据；本轮不实施并行、不改变单核单线程约束、不减事件数、不简化控制/细化、不动留出。非训练留出按固定预测后评分协议安排，不能自动套用全部训练控制矩阵制造额外研究。

## 6. 必须迁移和校验的资料

迁移应保留完整项目工作副本，不能只克隆 Git：`local_runtime/` 下包含大量不可替代的未跟踪原档。推荐保留原 Windows 控制路径 `E:\TCAD-Workspace\tcad-research-training`，另做独立备份。

| 类别 | 内容与校验依据 |
|---|---|
| 源码/规范 | `experiments/dram-see-v4/`、`scripts/tcad.py`、项目 AGENTS/当前 Goal 计划、原模型/物理/单位/源协议、所有版本化冻结源码。保留当前未提交改动；不因迁移提交/推送。 |
| 原生原档 | `local_runtime/runs/`、`local_runtime/dram-see-v4/transport-probe/operations/` 的 manifest/operation、inputs.tar、results.tar、collected、日志、真实退出和失败。按各原 manifest 的 SHA256 校验，已验证大归档可复用记录，迁移后再校目标字节。 |
| 新输入与接线 | `local_runtime/dram-see-v4/continuous/` 的全部 prepared projects、control-transition-r14-2d、source 包/数学账、登记副本、analysis、actual-usage、coordination 及备份。上表 handoff 内含完整成员 SHA，不仅保存摘要。 |
| 历史失败 | 旧预算/审批/冻结/失败包、帧覆盖原始输出、完整 dt2失败、旧 α 时间步失败、恢复后缀失败、3D失败/OOM/重启原档全部保留；不删除不利样本。 |
| 原远端 | 当前 `/srv/tcad-dram-see-v4/runs/<Run ID>` 必须先完整收集；其他尚未本地收齐的原目录按原 ledger 恢复。保留控制根和数据根的来源映射，不把活跃 PID/boot/锁复制成服务器有效身份。 |
| 图表和报告素材 | `analysis/proton-t03-projection-figures-r1/` 的 PNG/SVG/原数据CSV/脚本/图注；已有真实波形失败图、源帧覆盖图、报告和答辩材料原稿。明确其证据边界。 |

迁移清单记录相对路径、大小、SHA256、来源 manifest、实际复制/校验结果和缺失项。源地址和目标地址可以记录，SSH密钥、密码、访问令牌和许可证秘密不得写入文档/仓库/日志。保留原始 JSON 字节；绝对路径适配应有新映射/新版本证据，不能原地改历史 manifest 使其冒充新主机结果。

环境前提：

- 控制端实际 Python 3.13.15；既有分析环境 NumPy 2.5.3、Matplotlib 3.11.2。`local_runtime/vdmos-analysis-venv/pyvenv.cfg` 含 Windows 路径，不能直接视作 Linux 可运行环境。
- Sentaurus **W-2024.09 linux64**、相应合法安装/许可证/SDK/工具可用性需在服务器确认。原 PMI CMI实际编译器 GCC10.2.0，厂商构建记录 GCC12.3.0 有一致性警告；保留 `cgoal-r14-projection-pmi-build-r2/collected/` 的 expected-runtime、compiler、ldd和编译输出。原.so静态兼容不是跨主机ABI或原生激活证明。
- Geant4 **10.7.3**、原GCC10.2构建、QGSP_BIC+EMoption4，G4EMLOW7.13、G4ENSDFSTATE2.3、PhotonEvaporation5.7、G4PARTICLEXS3.1.1。绝对库/数据路径见 `cgoal-bcat-build-20261017t043911z/collected/environment.sh` 及 linked-libraries/dataset 原档。
- 当前 `tcad.py:31–44` 连接仍依赖 vmrun/vmx 和旧 `HostKeyAlias=tcad-training-vm`；不能仅改IP冒充服务器适配。保留严格主机密钥核验，为新主机独立核实指纹；不关闭校验、不套用旧指纹。
- Windows owner 使用 msvcrt。若控制端也迁到 Linux，需明确适配同一 owner 语义；不能清空锁/绕锁或另起不受管的 runner。当前没有服务器连接信息，本轮不做这些改动。

## 7. 禁止原样重投的历史输入

`20261020T153052Z-...source-subsegments161-...` 和 `20261020T214336Z-...source161-waveform-...` 的共享源前缀输入有帧覆盖问题，不能作为当前协议重投。旧 `20261020T034151Z-...proton-window-...` 属旧共享前缀/旧时序；旧直接 α 时间步失败、旧全波形 dt2失败、恢复后缀等价失败均不能恢复为已通过队列。旧 `proton-h-e100-a30-r1` 不能替代 T06 的真实身份。当前唯一 run 已经提交过，任何恢复都先查原目录，绝不再 run 同一ID。

本轮本机收尾后不会自动启动上述任何待办。新服务器接续须先读取这份计划、独立收尾状态和最新真实原档；完整课程完成标准仍以 `CONTINUOUS-GOAL-PLAN.md` 为准。
