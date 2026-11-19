<!-- PMI_R10_FINAL_RESULT -->
## 2026-10-15 r10单次原生诊断已完成：直接原因已定位，修复未验证

单次授权已使用，不能再次重放。新run `20261015T124711Z-v4-nuclear-closure-r1-qualification-zero-0290aeb0` 求解和字段提取正常结束；10实例49,130次Compute_r全部Undef，8个Transient块首实例都在首BE前完成并析构，957实际BE步没有回调。原始ReadTime/dt在后续块并非0，但原Undef分支显式写四字段0；源更新时间假定与实际回调生命周期不匹配是已证直接原因。更深缓存/调度原因不宣称唯一证明。

新旧完整PLT、mesh、字段测量/inventory逐字节相同；69帧全部审计，414原时钟检查仍失败，无资格gate/正点/器件矩阵。标准接口逐BE刷新目前无已证安全修复，保持PMI及下游阻断；禁止补期望值、假激励、改初态、PostProcess替代联合源或切换未经验证接口。无需再次询问这次已消耗授权，也不重复已完成静态调查。

当前唯一登记入口仍diagnose_zero_r10.py，但已关闭execution_enabled并回到READ_ONLY_HOLD；实际owner退出、锁释放。预算TCAD2/18、纠错1/4、工程编译6、后处理2；输运正常17+纠错1、100008不同初级，旧预算不变。半小时任务ACTIVE保留，仅核查实质新证据与原档。后续独立修复必须有受支持的逐实际BE/回退更新语义、离线验证、新发布及剩余预算核对，不自动追加诊断。

详见 `experiments/dram-see-v4/nuclear-closure-r1/PMI-NATIVE-RESULT-R10.md` 及 `local_runtime/dram-see-v4/nuclear-closure-r1/pmi-root-cause-r10/final-review.json`。此段取代下方准备/等待确认/正在运行等历史快照；原失败和原档全部保留。
<!-- PMI_R10_FINAL_RESULT_END -->

<!-- PMI_R10_AUTHORIZED_PREPARATION -->
## 2026-10-15 r10单次诊断用途已获人类明确授权

用户答复“授权一次诊断，预算和门槛不变”，证据在 `local_runtime/dram-see-v4/nuclear-closure-r1/pmi-root-cause-r10/authorization.json`。这只允许原qualification-zero的1次同条件带日志诊断，计入18次总量及4次纠错；不再重复询问此授权。原物理输入/全帧/门槛不变，不自动放行正点或器件矩阵。

正在冻结 `diagnose_zero_r10.py` 与独立编译模块；仅最新active-entry及release-trace-r10发布完成后可运行。原owner锁/严格SSH/原runner/共享solver锁仍为唯一执行链。旧r8/r7入口不启动，旧失败和原档保留。若根入口正在运行，保护已有owner，不另起队列；未知attempt只查原目录。候选与原日志的静态调查已完成，不重复调查。

此段取代下方“尚未收到答复”的时间快照。实际进程、attempt和最新报告优先。
<!-- PMI_R10_AUTHORIZED_PREPARATION_END -->

<!-- PMI_ROOT_CAUSE_R10_NOTE -->
## 2026-10-15 PMI 根因调查 r10：有新排除证据，尚未发布诊断

本轮已核对官方无输入场写入示例、原始字段映射及原生缓存实现：不能再把“缺PMIUserFields输入”当作已证修复依据；缓存存在，但全局版本戳/依赖仍参与失效，未证明原运行跳过回调。剩余动态问题是Compute_r实际时钟上下文和写后字段提交/覆盖。旧r9中的优先线索须按本段更新，原失败结论和门槛不变。

新 `pmi_source_trace_r10.C` 只增加有界真实调用日志，5项独立源级测试通过，未编译、未提交、未发布。单次同条件诊断提案见 `experiments/dram-see-v4/nuclear-closure-r1/PMI-DIAGNOSTIC-R10.md`；根报告在 `local_runtime/dram-see-v4/nuclear-closure-r1/pmi-root-cause-r10/report.md`。因原纠错用途要求已知根因与修复，已提出一次明确的诊断用途确认，尚未收到答复；不能把提案当授权，也不要重复询问例行确认或重复已完成静态调查。

当前active-entry仍r8 READ_ONLY_HOLD/execution_enabled=false，旧r7不启动。最新现场无调度者/求解器、共享锁空闲。预算仍TCAD1/18、纠错0/4，输运17正常+1纠错、100008不同初级，编译工程5、后处理1。未安装、未新增求解或重提、未放宽任何门槛。后续以实时现场、用户答复及新的独立发布为准。

<!-- PMI_ROOT_CAUSE_R10_NOTE_END -->

<!-- ACTIVE_NUCLEAR_CLOSURE_START -->
## 当前有效计划：nuclear-closure-r1，r8只读验收，PMI资格未通过

旧计划SUPERSEDED_PARTIAL：二维15/17、细网格A1科学失败、16新调用/含历史21及全部原档保留，不继续原A5，不运行旧original-recovery或旧invoke/adopt。

当前注册候选入口 `continue_values_r8.py`，active-entry.json明确 `execution_mode=READ_ONLY_HOLD`、`execution_enabled=false`。`release-values-r8.json` SHA `48084f2d5dd646403f8f0fa432da985588ef3b1c9cce72733319ec73b3989808` 只放行读档评估，不允许启动接续。最后原生入口r7已退出；原owner及共享锁已核查空闲。不得重启r7或为了维持运行绕过资格门。后续新独立发布仍以active-entry/release及真实现场为准。

N3已全部完成，按阶段完整后的固定顺序选中nc-r1-h-008/event5893（seed50150009），7直接核次级、22后代，窗内后代Si电离0.2700684538687032MeV；完整事件155个正Si源步，离线总电荷12.034352683463064fC。P0/N1/N2/N3的100008个不同初级全部保留。选择SHA `1b8f6d7a30bec7bff74dc763ba94b28d8e60de15b7d649bcb90ce0bd101d3840`。不进入N4、不重选强响应事件、不把离线源当原生验收。

PMI原编译库工程补完已通过：原Cmi ELF逐字节复用，独立新操作严格ldd及六oracle成功，原78/78/0失败保留。compiled=true仍qualified=false，具体见PMI-R6.md与runtime pmi-build-r2/。

原qualification-zero run `20261015T061444Z-v4-nuclear-closure-r1-qualification-zero-fcbd4da7` 正常完成4ns，runner/SSH/远端0；单独传输退出未记录仍未知。957BE、958唯一PLT时刻、69源窗TDR完整，原归档SHA `3a02714b09c58a77af5de80b6e538812566491b0ef210b18c67afd167da6c1ff`。r7只修复精确零迭代RHS收敛句，0000真实首帧保留。

原 `nc-r1-fields-qualification-zero` 已完成69/69帧，适配器/SSH/远端/归档/SVisual均0，归档SHA `64bd777d17b8bec4514f17f3d1c4ee2ac368f7fa1fbf102d21295b09735f59a7`。r8只按同版本手册解析极值value {x y z}，保留所有5106原始行、1104个极值的位置及raw；原r7准备输入完全不变，r8评估身份和真实attempt分开。6项独立测试和静态审查通过。没有重做提取或求解。

**零源科学资格未通过**：69帧PMI时间/步长/步型实测均0，原门产生414项失败；没有改填期望时间/3，没有放宽判据，没有gate、没有正点源调用。typed收据与失败审计见runtime field-values-r8/root-evaluation.json、original-zero-audit/及FIELD-VALUES-R8.md。原失败和原档保持。

根因尚未证实。原log无PMIUserFields输入是优先排查线索，不能据此断言唯一根因。cmi-a实际GCC10.2，厂商构建GCC12.3；已检查/usr/synopsys、/usr/local、/opt、<SIM_USER_HOME>、/depot、/depotbld（含链接）未找到匹配版本。兼容性要求、证据强度、有限诊断和纠错准入条件见PMI-QUALIFICATION-R9.md及runtime pmi-qualification-r9/。当前不安装软件、不切换源接口、不作无已验证修复的推测性纠错求解；只暂停PMI及依赖器件分支。

最新预算：TCAD1/18、纠错0/4；输运正常17/107、纠错1/2、不同初级100008、重放0；编译工程5、后处理1。本轮r8纯读档重审和SSH观察未增加计算调用。旧预算不重置。原材料密度纠错、射偏审计、存储与索引修订全部保留，科学阈值与8/20/160GiB资源门不变。

既有dram-see-v4半小时任务保持ACTIVE，只维护同一任务，状态不变静默留档；后续先查真实进程/原目录/锁和新前置条件，未知状态不重提。继续严格SSH、原continuation/owner.lock、远端共享solver锁、单计算线程/单核。当前现场以latest-progress-check.txt和attempt账本优先，status历史error/初始计数不作新预算。不得恢复旧计划、安装、提交推送、外发、训练、生成持久翻转标签或声称商业器件校准/事件率。
<!-- ACTIVE_NUCLEAR_CLOSURE_END -->

# DRAM SEE v4 操作交接：二维收尾 → 三维试点


<!-- ACTIVE_V4_AUTOMATION_START -->
## 无人值守检查授权：2026-10-14

用户已授权“半小时检查一次，不要停下，自动推进下一步，不要询问我，自行决策，维持仿真运行”。当前对话新建定时任务 **dram-see-v4** 已启用，每30分钟检查并在冻结合同与预算内自主接续；保持现有唯一调度者、未知状态不重提，不扩大物理或预算授权。原有失败停止规则继续适用，只暂停相关分支并保全现场。本次任务不等于恢复历史旧心跳。配置、用户原文与回执：`local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/automation-checks/20261014T162000Z/authorization-and-creation.json`。用户要求停止前保持本检查任务启用；既定矩阵全部完成后仅核查归档，不增加新计算。
<!-- ACTIVE_V4_AUTOMATION_END -->



<!-- ACTIVE_RECOVERY_HANDOFF_START -->
## 当前接续：2026-10-14 19:15（UTC−08:00）

用户已明确答复“**授权该单次工程恢复例外**”。新增独立版本 `experiments/dram-see-v4/original-recovery-r1/`，47 项定向/整合检查通过；冻结发布 SHA 为 `5f36ce180ce52c525e8bc023d50f18c8d080ad9f1d5c1f565af642f66bb8076f`。原冻结实现、物理门槛、原退出事实和归档没有改写；下方“等待授权”段落已成为历史快照。

A6通过后，旧清理器因不能识别r1验收来源哈希而停止，未生成清理计划或删除文件。独立r2仅修复明确的新旧验收来源绑定，原路径/归档/白名单/物理保护不变；旧r1发布和失败退出1记录保留。r2发布SHA `36552040e90169e28c48388387cdaf57d90f3f198d780e04d4307f08e45e388a`。已确认旧owner和scheduler退出，再用原所有权锁启动唯一r2接续；通过adopt复用A6结果，不重算、不重新发布其gate。

原 A1 `20261014T040702Z-v4-source-interface-r5-a1-b1-time-b8fc5db7` 已结束，远端退出 0；完整 4 ns 曲线、849 文件归档及前后哈希链已恢复，原本地 runner/SSH 退出仍未知、包装完成标志仍缺失。新合同精确绑定该 run：原执行合同未通过，独立工程恢复证据通过。原 A1 的405帧提取、404个接受步加1个边界帧、全帧字段审计、匹配 A0 与时间细化比较均已通过，角色 gate 已发布。 时间细化A6也已完成4ns、405帧后处理和全部科学验收。

原唯一接续owner PID 140508、scheduler PID 138776 已退出，二维子调度退出码2；截至 2026-10-15T03:14:54.078709+00:00，本地无活动调度者，远端无v4计算进程，共享锁空闲。这些PID仅用于追溯，不能作为仍在运行的依据。旧owner/coordination的失败记录保留，未启动替代调度者。

入口 `original-recovery-r2/continue.py` 已按失败规则退出：细网格A1未通过网格细化比较，A5及其下游暂停；不得跳过gate或重提相同输入。二维全部17项通过且子调度退出释放锁后，才会启动三维 A0/A1 和六次固定输运请求、共8初级事件。现在不要启动第二份 `--adopt`、旧三维等待进程或心跳。任何未知状态/非零阶段均保存并停止，不自动重试。

预算快照：二维新批 **16/21**、含历史 **21/26**、已通过角色 **15/17**；纠错 **0/4**；三维 TCAD **0/4**、匹配 Geant **0/6次**、初级事件 **0/8**。恢复/归档/原生字段后处理不是新 TCAD 调用。

证据：`local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/` 下的 `authorization.json`、`root-implementation-acceptance.json`、`continuation-r2/execution.json`、`launcher-r2/`、`observations/`；A1原生字段 operation 为 `local_runtime/dram-see-v4/transport-probe/operations/r5-a1-b1-time-r1-fields/`。原A1的 `execution.json`、`manifest.json` 仍保留历史 RUNNING，只能结合新合同、恢复回执和实时进程判断，不能因旧值重提原求解。

最近细网格A1完成/失败复核：`local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/progress-checks/20261015T031448Z`；205帧原生后处理完成，4ns完整输出、全帧字段与源审计均已重放核验。但SN连续扰动差4.560820mV超过冻结上限1.749307mV，角色验收未通过、无gate。A5、三维及固定输运仍依赖该gate，未启动；失败诊断、完整原档、哈希与预算见同目录report.md。半小时检查任务dram-see-v4保持启用，未放宽门槛或盲目消耗纠错预算。
<!-- ACTIVE_RECOVERY_HANDOFF_END -->

## 最新接手恢复核查：2026-10-14 02:14（UTC−08:00）



原 A1 已结束：原远端 `exit-code.txt=0`，原生日志和两条完整有限 PLT 均到 **4 ns**，最终 TDR 存在，共享锁已释放；没有启动新的调度者。



已从**同一原目录**完整回收 **849 个文件、1,221,928,960 bytes**。传输退出码 0，前后逐文件 SHA-256 与归档一致；原输入和 `run.sh` 一致。归档 SHA-256：`ca9b51554f10d4a4ffb846ee4bc1b49aa606d99ab7774287b6844ff5452d01df`。原目录 `local_runtime/runs/20261014T040702Z-v4-source-interface-r5-a1-b1-time-b8fc5db7/results.tar` 已补齐，并增加独立 `original-archive-recovery-r1.json`；恢复前记录与原始归档另存于 v4。原 `manifest.json`、`execution.json` 和协调状态原样保留，原本地 runner/SSH 退出码仍未知。



**恢复未获验收，队列暂停。** 新发现原 `execution.log` 截断在约 1.025 ns，缺少强制 `ENGINEERING_RUN_COMPLETED`；冻结验收函数原样执行报 `Missing original runner completion marker`。两条 PLT 各有 1028 个唯一时间点、匹配 A0 实际网格和物理合同一致，仅为恢复诊断，不能替代全帧场审计及角色 gate。输出链断开是原因假说，未确认精确机制。



预算不变：二维 **14/21**、含历史 **19/26**、纠错 **0/4**，角色 **13/17**；三维 **0/4**，匹配输运 **0/6次、0/8事件**。未 adopt、未新求解、未发布 gate；没有接续程序在后台等待。旧协调状态仍是历史记录，不能当活动进程。



已准备精确绑定本 run 的独立工程恢复例外提案，**尚未授权或激活**。用户明确“不放宽门槛”，缺失强制完成标志的替代证据需单独决定；现有独立恢复适配授权不能被解释为按旧门槛自动通过。若允许新恢复协议，仍须保留原退出码未知、旧门槛未通过，并执行全部原物理门槛与定向验证；否则保持依赖暂停，绝不重提。



证据索引：`local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/`，含 `report.md`、`archive-diagnosis.json`、`recovery-exception-proposal.json`、`budget-observation.json` 及 `collection/20261014T100927Z/` 原始取证。旧快照见下文，仅供追溯。



## 最新复核补充（2026-10-14 08:13 UTC）



用户本次仅授权核查与留档，以避免与接手agent重复操作。原远端A1仍在运行，已接受至 **2.7839 ns/4 ns**，bash7911、SDevice8095仍在，共享锁忙。退出文件、最终TDR、完成标志未出现，本地results.tar未生成。旧本地调度与runner进程仍不在，未发现新的本地任务入口；原输入/run.sh抽查哈希匹配。**本次没有恢复状态、归档或队列，更没有新调用。** 第1节恢复流程仍留给接手agent执行。



最新账目为二维14/21次、含历史19/26次、纠错0/4；三维0/4、Geant0/6、初级0/8。当前A1仍占既有一次调用，科学角色仍13/17；不可因“仍运行”重新提交。记录：[本次复核](../../local_runtime/dram-see-v4/three-dimensional-pilot-r1/handoff-checks/20261014T081311Z/report.md)、[预算](../../local_runtime/dram-see-v4/interface-completion-r1/budget/20261014T081327.103088Z-dfd6994d/budget.md)。下文04:31 UTC内容为首次交接历史快照。



交接快照：2026-10-13 20:31（UTC−08:00），即 2026-10-14 04:31 UTC。机器目录、日志及 run ID 保持 UTC。本文件是交接索引，不替代现有合同、调用账本或原始证据；发生冲突时先核查原作业，不能按文档补造状态。



## 1. 接手第一件事：恢复失去本地调度者的原作业记录链



最新现场与前一次交接不同：本地二维调度 PID **246636** 和三维接续 PID **404876** 已不在，相关 launcher/runner PID 也已不在。原因尚未查明，不能声称是正常退出。两份 `coordination.json` 仍分别写着 `STAGE_RUNNING` 和 `WAITING_OLD_SCHEDULER`，均为滞后状态。



远端原作业仍活着。2026-10-14 04:31:22 UTC 的只读核查得到：



- label：`r5-a1-b1-time-r1`；run ID：`20261014T040702Z-v4-source-interface-r5-a1-b1-time-b8fc5db7`。

- 远端目录：`<SIM_USER_HOME>/research-training/runs/20261014T040702Z-v4-source-interface-r5-a1-b1-time-b8fc5db7`。

- 该目录中的 wrapper bash PID **7911**、SDevice PID **8095** 存活，`.solver.lock` 被占用。

- `exit-code.txt` 尚未产生；日志 848561 bytes，已接受至 **1.0939 ns**，正在计算下一步。该时刻已离开注入细步窗口，日志中的 10 ps 步长不能误报为注入窗 0.25 ps 设置失效。

- CPU affinity 为 0。前次线程核查为一个活动计算线程、两个不耗 CPU 的休眠辅助线程；不要把 OS 线程总数 3 当成三路计算。

- 此处未发现求解失败；**本地调度丢失已确认，原运行最终退出状态仍未取得**。



证据：



- [最新远端检查](../../local_runtime/dram-see-v4/three-dimensional-pilot-r1/handoff-checks/20261014T043119Z/record.json)及同目录 `stdout.txt`、`stderr.txt`、`read-only.sh`。

- [上次完整依赖复核](../../local_runtime/dram-see-v4/three-dimensional-pilot-r1/continuation-checks/20261014T042138Z/root-review.json)：当时进程仍在，14 份 gate 完整性通过，A1 正确绑定时间细化 A0。它不能证明现在本地调度者仍在。

- 本次首个只读 SSH 脚本因 Windows 文本 stdin 转成 CRLF 失败，已原样保留在 `local_runtime/dram-see-v4/three-dimensional-pilot-r1/handoff-checks/20261014T043059Z/`。后改用二进制 UTF-8 stdin，检查成功。这是检查命令失败，**不是 TCAD 失败，也不占求解预算**。



接手顺序：



1. 重新核对本地实际进程、上述原远端目录的进程、锁、日志和退出文件。不能复用旧 PID 存活结论。

2. 远端还在运行就保护它；不再执行 `scripts/tcad.py run`，不创建替代 label。等待的是同一原作业，不是重算。

3. 原作业结束后，从**同一原目录**核对退出文件、`ENGINEERING_RUN_COMPLETED`、完整 4 ns 时序、输入及运行脚本哈希，然后收集原始结果归档，留存准确传输退出码与 SHA-256。先保存原 `manifest.json`、`execution.json` 等未恢复快照。

4. 原本地 runner/SSH 父进程已丢失，不能将其未取得的退出码直接填成 0。恢复记录须区分“原远端退出码”“本次取证/传输退出码”“无法恢复的原父进程退出码”。现有验收是否接受这样的恢复证据，需对照代码审查；若需要新恢复适配，使用独立修订与针对性验证，不篡改旧执行事实、不得放宽物理门槛。

5. **不要现在直接跑 `campaign_runner.py --adopt r5-a1-b1-time-r1`。** 当前执行记录为 `RUNNING`，该分支会要求原 `launcher_pid` 存活并拒绝继续。原控制器无独立“只重新收集”CLI；`--adopt` 不是 SSH 重连功能。

6. 原状态已可靠恢复、归档就绪且唯一调度所有权明确后，再由唯一二维调度入口完成本角色后处理/验收及余下队列。`--adopt` 会继续整队列，属于执行命令，须满足其证据前置条件。不是查看状态的命令。

7. 二维 17 项全部通过，旧调度者退出并释放锁后，才恢复唯一三维接续程序。原接续进程已退出，不能再声称它会自动推进；恢复之前要再次确认没有新接续进程。



本次用户要求交接，因此没有替接手者启动恢复或重启队列；远端原求解保持运行。



## 2. 目标、已授权范围与研究结论边界



导师主线：修正粒子作用过程 → 真实事件到三维器件的传递 → 小尺寸器件依据 → 尺寸与能量数据 → 物理约束预测。



已批准执行：先收尾二维，再完成**三维 A0/A1 两次试点**和**匹配输运六次调用、八个初级事件**。这是内部接口与成本节点，首次三维导师汇报的最终目标仍是“几何匹配的自然核次级联合器件响应”；目前尚未实现。



- 人工源与电子事件检查不能冒充核次级联合响应。

- 厚硅固定 212 个初级事件取得 9 个核非弹性见证，证明记录链；不属于 DRAM 几何，不能平移、缩放或压缩进器件，也不能用于 DRAM 发生率或训练。

- 旧薄硅 22 个事件保留 44 条电子次级，没有核见证；三份源账本保留 xyz，但不等于三维 TCAD 映射通过。

- 本轮没有授权扩大三维矩阵或自然核事件搜索。固定批次未取得核事件就如实写“未取得”，不更换种子搜索、不自动强制反应。

- 不启动新尺寸批量、正式 160 事件矩阵、空间谱、训练；没有匹配读出依据时不生成翻转标签。



## 3. 二维真实进度、匹配 A0 与预算



正式队列：`experiments/dram-see-v4/interface-completion-r1/campaign.json`；调度：同目录 `campaign_runner.py`。不要按旧 stage2 中的 19 次上限覆盖新批预算。



已过 13 个角色：主网格 bit1 A4/A5/A6/A7/A2/A3/A8S2/A8S4；更细网格 bit1 A0；主网格 bit0 A0/A1/A4；时间细化 bit1 A0。加上 `reuse-main-b1`，现有 gate 文件共 14 份。



| 待完成顺序 | 网格与时间 | 匹配零源 |

|---|---|---|

| `a1-b1-time`（原远端正在运行） | mesh_scale=0.5，注入最大 dt=0.25 ps | `a0-b1-time` |

| `a6-b1-time` | 同上 | `a0-b1-time` |

| `a1-b1-fine` | mesh_scale=0.25，注入最大 dt=0.5 ps | `a0-b1-fine` |

| `a5-b1-fine` | 同上 | `a0-b1-fine` |



当前 **14/21** 次新调用、**19/26** 次含历史调用；其中纠错使用 **0/4**。`coordination.json` 的 `new_attempts=13` 是当前调用开始前的快照，实际调用账本已为 14；不要手改协调状态来“修正”这一滞后。



- 主网格 bit1 A0/A1 复用 r4，经跨版本证据 gate 关联，不能重命名历史版本。

- 时间 A0 run：`20261014T033236Z-v4-source-interface-r5-a0-b1-time-f9574b96`。

- 时间 A0 gate SHA：`ae2e1ade77d0ed6dba0c60d0047f4167543df3562aef2a45d7a2c3c267d3ebd7`。

- 当前 A1 输入 manifest SHA：`7bbf0966eba166a88e8cb6dd7578814db4dd298f4ac9461d9ffad22618c9e56a`。

- A0/A1 matching contract SHA：`e8f659f3f7bd8597f6cb4e85113afc86e682d6e61f741312b6817eb6f93651e5`。

- `scientific_calibration_passed=false`、`overall_source_interface_passed=false` 是明确边界；单角色 gate 通过不表示整轮或器件校准通过。



二维固定门槛：离线闭合 `max(1e-6 fC, 0.1% Qin)`；原生总生成量误差≤5%；分区占比绝对差≤0.05、分区加总误差≤5%、质心≤0.01 µm、时间中心≤0.5 ps、实际 BE 区间平均波形误差≤5%。同源等价 Q差≤1e-4 fC、V差≤10 µV，另有原电流与生成曲线门槛。分段/数值细化 Q变化≤2%，减各自匹配 A0 后扰动差≤`max(1 mV, 5%扰动峰值)`。失败不改门槛。



## 4. 三维试点冻结实现与待验证项



冻结发布：[release.json](three-dimensional-pilot-r1/release.json)，SHA **`e30ca832214a2cd5c418ef7195c5e8152ec82e9601e8a8f2e5711d50f864d7aa`**，固定 66 个文件。04:31 UTC 再次 `check-release` 通过。新交接文档在冻结列表之外；不要改列表内 README、代码、合同或输入。



| 模块 | 入口与职责 |

|---|---|

| [三维总控](three-dimensional-pilot-r1/README.md) | `control.py` 预算、原始状态、门槛；`campaign_runner.py` 串行队列；`acceptance.py` 原生验收 |

| [三维器件与源](source-interface-3d-r1/README.md) | `build_interface.py`、`geometry-contract.json`、`source_contract.json`、`mesh_resource_guard.py` |

| [三维原生场审计](source-field-audit-3d-r1/README.md) | `audit_fields.py`、`extract_fields.tcl`、`field_contract.json`；全部注入窗帧及 xyz 观测 |

| [匹配输运](matched-transport-r1/README.md) | `transport_matched.cc`、`control.py`、`audit_matched.py`、`matched-contract.json` |



模型为未校准 0.25 µm 平面代表单元的外挤结构：Si范围 `[0,0,-0.5]→[0.85,1.2,0.5] µm`，栅氧 `[0.3,-0.005,-0.5]→[0.55,0,0.5] µm`。x/y结构、掺杂、电路继承现有模型；z均匀延拓。接触为理想边界，没有捏造金属、BEOL、多晶硅或实际电容实体。z侧面无接触，采用自然 Neumann 电势及零法向载流子电流边界，仍须原生验证。



AreaFactor=1；存储10 fF、位线/参考各100 fF不按宽度二次放大。A0为bit1无源完整时序；A1起点 `(0.425,0.3,0) µm`、沿+y长0.6 µm、1 fC、宽0.03 µm、中心1 ns、σ=2 ps、注入最大dt0.5 ps，使用自己的3D A0。不要求与二维局域响应相等。



- 三维体积单位 µm³→cm³为1e−12，不再乘二维有效厚度或AreaFactor。

- 源核为有限均匀纵向段及横向Gaussian；不能拿旧离线诊断核当原生核通过证据。

- 正沉积零长度步仍作为点沉积保留；点源核未验收不能造短线段或删除后送入TCAD。

- 三维生成量≤5%、xyz质心≤0.01 µm、分区占比差≤0.05、时间中心≤0.5 ps、BE平均波形≤5%；首次A0/A1不等于时间/三维网格已收敛。

- 网格沿z在源附近≤0.01 µm。薄界面使用保留xy细化的各向异性网格，避免在整个3D域机械采用1nm等距网格；它是已登记试点假设，仍待原生检查。

- SDE成网后在同一次调用中执行资源守卫；必须有 `mesh-resource-passed.json` 才进入SDevice。未知日志格式或空间不足应阻断，不重新提交。

- `acceptance.py` 的原生 `Tetrahedra/Tetrahedrons` 日志识别尚未实测。若仅解析失败，先保留原结果并修复解析，不重算器件。

- 场审计直接只读原远端TDR，校验组前后、帧前后哈希及路径身份。用新 `collect_receipt()` / `audit_fields.py collect`，不要误用旧stage2字段收集器（旧版需要复制payload）。原始远端与本地完整归档仍保留。

- 12个ROI包括9个旧分区及z正/负/中心管；初始场9个掺杂探针检查源漏正、体负、同xy跨z相对差≤1%。这不等于工艺校准。



预生成输入在 `local_runtime/dram-see-v4/source-interface-3d-r1/inputs/`，A0/A1分别为 `v4-source-interface-3d-r1-a0-b1-main`、`...-a1-b1-main`；manifest SHA分别为 `6678458458210a9f01d336f78cb994522dfb33644c289ebe599b6ccdffe456b8`、`5e03f417baa25b788dd02174aedb5c8bd340ba0ac45ba49cb82340291dd54ffa`。



## 5. 匹配输运的六次固定请求



共享几何 SHA：`3fb882383484e35445192b23169981d0061b650b06c64f132d1fb4ba63fd755d`。Si、SiO2与TCAD同源；世界为真空。100MeV质子，沿+y正入射；正常源 `(0.7,-1.005,0) µm`，射偏源 `(1.85,-1.005,0) µm` 避开全部实体。production cut=0.01 µm，实体内带电粒子最大步长0.02 µm，都是诊断起点，未做输运收敛。



| 顺序 | 请求 label | 种子 | 初级数 |

|---|---|---:|---:|

| 1 | matched-init-h-r1 | 40142001 | 0 |

| 2 | matched-init-e-r1 | 40142002 | 0 |

| 3 | matched-normal-h-r1 | 40142101 | 2 |

| 4 | matched-normal-e-r1 | 40142102 | 2 |

| 5 | matched-miss-h-r1 | 40142103 | 2 |

| 6 | matched-miss-e-r1 | 40142104 | 2 |



H=QGSP_BIC替换EM为Opt4；E=Opt4；串行G4RunManager。保留所有事件/轨迹/步骤/材料，稳定出生token关联母产生步骤和子ID；动态离子库存用 `reset(false)`，不用GenericIon替代真实离子库存。`Eion/step_length`称局域电离沉积密度，不直接称标准LET。



编译包 `local_runtime/dram-see-v4/matched-transport-r1/inputs/matched-build-r1` 已准备，**尚未原生编译/运行**。控制器把包完整复制至原 `transport-probe/inputs/` 并核验，复用原operation适配器；不要动态改适配器全局变量绕路径限制。编译操作单独记账，不算六次Geant二进制调用，但失败同样保留且不自动重试。



两臂初始化均通过后才做四次事件请求。本批只验格式、材料几何与成本，不保证核反应，更未放行这些真实事件进入TCAD。



## 6. 预算与停止规则



| 账目 | 已用/上限 | 说明 |

|---|---:|---|

| 二维新批调用 | 14/21 | 17个必做角色+4次明确修复余量；当前调用已计入 |

| 二维含历史 | 19/26 | 旧5次保持历史，不能抹掉 |

| 三维TCAD | 0/4 | A0/A1两次必做+2次明确修复余量 |

| 匹配Geant二进制 | 0/6 | 0/8初级事件；不自动重算 |



本地新试点预留80 GiB与旧批剩余需求分别核算，不能共用同一笔额度。远端每次预计峰值后至少剩8 GiB。04:31 UTC远端可用28,085,612 KiB只是一份快照，不是下一作业资源许可。



三维成本不能按二维线性外推。成网后守卫依据实际节点数估计原始场/归档峰值；4 GiB MemAvailable门槛不是峰值内存保证。A0完成后更新A1预算；A1完成后只提出下一批冻结建议，不自动扩展。后处理单列时间/存储，不占求解数。



已知失败只阻断相关依赖；A0失败阻断A1，但在状态明确、共享锁释放时独立匹配输运仍可做。任何未知原作业状态阻断新提交。相同根因连续两次失败暂停分支；余量不能用于加新工况或搜索通过结果。纠错须保存根因、旧版本、修复、离线验证和单次修复票据。



## 7. 已完成的实现验证，避免无故重复全套测试



实现已冻结，尚未产生3D原生科学结果。无新改动/失败不重跑全套测试。



- 三维输入28项、三维场审计24项、总控17项、总控独立26项通过。

- 匹配输运73项通过，另有独立运行身份定向复验和集成验证。

- 根验收：[root-implementation-acceptance-r1.json](../../local_runtime/dram-see-v4/three-dimensional-pilot-r1/validation/root-implementation-acceptance-r1.json)。

- 控制审查：[controller-review-r2/review.json](../../local_runtime/dram-see-v4/three-dimensional-pilot-r1/validation/controller-review-r2/review.json)。

- 匹配复核：[matched-transport-recheck-r1/evidence.json](../../local_runtime/dram-see-v4/three-dimensional-pilot-r1/validation/matched-transport-recheck-r1/evidence.json)。

- 依赖复核：[continuation-20261014T0421-r1/evidence.json](../../local_runtime/dram-see-v4/three-dimensional-pilot-r1/validation/continuation-20261014T0421-r1/evidence.json)。



已修复且保留失败版本：运行ID与请求/原operation/归档身份未严绑定；空或重复gate证据；只信顶层passed却忽略内部失败；已知单支失败错误阻断独立请求。旧版本在各模块 `revisions/`、旧审查在 `validation/controller-review-r1/`。不要回滚这些保护。



## 8. 目录和安全命令



工作目录 `E:\TCAD-Workspace\tcad-research-training`。PowerShell变量不要占用 `$HOME`/`$CODEX_HOME`。



```powershell

Set-Location 'E:\TCAD-Workspace\tcad-research-training'

$v4Python = 'E:\TCAD-Workspace\tcad-research-training\local_runtime\vdmos-analysis-venv\Scripts\python.exe'

Get-Content -Raw local_runtime/dram-see-v4/interface-completion-r1/coordination.json

Get-Content -Raw local_runtime/dram-see-v4/three-dimensional-pilot-r1/coordination.json

# PID必须来自刚读取的记录，并进一步核对进程身份；存在也可能是PID复用。

Get-Process -Id 246636,404876 -ErrorAction SilentlyContinue

& $v4Python -B experiments/dram-see-v4/three-dimensional-pilot-r1/control.py check-release

```



仅生成新本地报告，不求解：



```powershell

& $v4Python -B experiments/dram-see-v4/three-dimensional-pilot-r1/report.py

& $v4Python -B experiments/dram-see-v4/interface-completion-r1/budget_report.py

# 二维是make_report.py，不存在interface-completion-r1/report.py

& $v4Python -B experiments/dram-see-v4/interface-completion-r1/make_report.py

```



报告不是实时远端核查。查看二维 `publication_ready`/`report_errors`，不能只看退出码。`acceptance.py`会写audits并发布gate，影响后续准入，不属于普通报告；`doctor`会签出版本检查所需许可，不是纯路径读取。



以下命令**会执行工作**，只在恢复前置条件落实后由唯一负责人使用，当前不得直接复制运行：



```text

python -B experiments/dram-see-v4/interface-completion-r1/campaign_runner.py --adopt <已恢复的原label>

python -B experiments/dram-see-v4/three-dimensional-pilot-r1/campaign_runner.py --wait-for-old

```



后台启动用 `Start-Process -WindowStyle Hidden` 并留存launcher PID、实际scheduler PID和独立stdout/stderr；不要用 `start` 等无留档包装。旧心跳不得恢复，不另建自动化代替当前队列。



远端连接只使用 `scripts/tcad.py.connection()`：VMware Tools发现地址、固定host key、专用密钥。不要显示 `local_runtime/connection.json` 的敏感配置，不猜IP或关闭校验。SSH运行多行脚本要用LF字节stdin，例如 `subprocess.run(ssh + ['bash -s'], input=script.encode('utf-8'), capture_output=True, timeout=...)`；不要用Windows `text=True` 输入导致CRLF。超时只能说明检查中断，不意味着原作业已停止。



| 事实/产物 | 目录或文件 |

|---|---|

| 二维角色gate | `local_runtime/dram-see-v4/interface-completion-r1/gates/` |

| 二维原调用账本 | `local_runtime/dram-see-v4/source-interface-r5/launches/<label>/execution.json` |

| 原TCAD运行证据 | `local_runtime/runs/<run_id>/manifest.json`、`run.sh`、`inputs.tar`、`results.tar`（恢复前可能尚无） |

| 三维调用账本 | `local_runtime/dram-see-v4/three-dimensional-pilot-r1/calls/<label>/execution.json`；不是calls.jsonl |

| 三维编译/后处理 | 同目录 `operations/<label>/execution.json` |

| 三维协调、历史变化 | 同目录 `coordination.json`、`events.jsonl`、`launcher-r1/`、`stage-results/`、`audits/`、`gates/` |

| 既有运行备注 | `local_runtime/dram-see-v4/three-dimensional-pilot-r1/handoff.md`，按末尾最新更正阅读 |

| 原operation证据 | `local_runtime/dram-see-v4/transport-probe/operations/<label>/` |

| 匹配输运结果 | `local_runtime/dram-see-v4/matched-transport-r1/{runs,audits,gates}/` |



## 9. 文献、下一汇报与保护范围



[90 nm证据](device-evidence-r2/README.md)：Shin Fig.8/11/12原图已核验，90nm工艺节点与约95nm物理栅长分开；Fig.8/11同剂量、Fig.12同阈值等条件不能混淆，保持参数缺口。Park Table1/Fig.10/13原图未取得，独立候选，不能拼装两文参数；23 fF不移植到当前代表单元。



首次三维导师汇报还需要“初级质子→真实核作用和精确后代→三维电荷账本→全事件联合源→匹配A0节点电压/独立端电流”。当前试点结束只交真实成本、验收与下一批建议；后续多源、非零z、边界、错时、分段、数值细化及自然核事件数量须另行冻结。



训练后置。用独立端电流积分与正确电路守恒提供信息，不能以由CΔV构造的标签重复证明同一关系。导师“降低拟合准确性”原文保留为沟通问题，现按样本效率及跨条件预测理解。



v4源码和大量先前成果尚未提交；`git status`还显示历史v3改动与未跟踪文件，**不是本次交接造成，也不能reset/clean掉**。本次只增加交接文档及v4运行记录，不改v3、交付稿、冻结实现、原始失败。商业手册仅存被忽略的本地runtime，不能提交。用户未授权安装软件、Git提交/推送或对外消息。



交付给用户时说清：恢复了什么原作业、通过哪些角色、调用数与剩余预算、已知失败及未知状态、原生三维是否真的运行。不能继续沿用“本地接续程序正在等待”的旧结论。

