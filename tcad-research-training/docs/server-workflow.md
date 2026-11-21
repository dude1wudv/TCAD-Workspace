# TCAD 云端工作方式

日常操作见[首月流水线手册](../automation/server-codex/MONTH-ONE.md)。以下按日期保留历史收据，不是实时槽位或当前科学计数。

## 异步调度升级已接管（2026-11-21 UTC）

执行代码提交 `9341d73`，异步控制器运行时为 `1a3e1eb`，发布目录标识 `20261121T044948Z`。原唯一服务已重启并恢复按需异步规划；配置为 TCAD 上限 13、Geant4 上限 4、轮询间隔 5 秒、同一时刻最多一项原运行器操作。沿用下节已验证的 20 核服务器、17 核虚拟机和原共享池，不新增池或改写科学 contract、冻结输入、运行身份与历史 profile。

先在关闭规划侧车、全局上限 1 下接管原 Geant4 任务，保留原 100,000 primaries 输入。原计算退出 0，完整归档核验后由原运行器释放租约，状态为 `COLLECTED_PENDING_AUDIT`；接管期间发现并修复的收集身份比较错误和原失败记录均保留。只有对账确认活动数 0、无发现不确定性后，才恢复正式上限并切回 TCAD。`2026-11-21T05:25:52Z` 核验：服务 active、无暂停标记、发现无不确定性，原任务 `r06-s-d1-c1-p07-b1-r1` 在槽 12 以冻结的 4 核配置运行。该次实际运行 1 项；其余候选仍受科学准入、依赖或槽位条件约束，不代表 13 槽满载已经验证。

控制器 243 项回归通过（1 项环境跳过）；新增原运行器协议回归在服务器 Linux 上 7 项全部通过。原 runner 全量入口的历史 5 个失败、1 个导入错误另行保留，不据此修改 sealed 指纹。5 秒是轮询配置；持续 3–5 秒心跳、批量探针延迟、结束到归档与补槽的典型值/P95、满载内存和长期吞吐尚未完成生产统计验收。原工程收集成功与正式科学验收分别记账。

## 20 核调度上线（2026-11-20 UTC）

服务器可见 CPU0–19。虚拟机实见 17 核、分配内存 28 GiB，QEMU 有效绑定为服务器 CPU0–16，另 3 核留给服务器。原 TCAD 共享池配置 13 个槽：CPU0–11 每核一项，CPU12–15 合跑一项，CPU16 留给虚拟机后台。切换前原租约均已收集，12 把锁均空闲。Geant4 保留原 profile、最多 4 项，继续在空池轮换。原运行器在首次符合准入的预约时更新池标记。

12:23 UTC，唯一调度服务按新配置恢复并设为开机启动，服务账号检查通过。切换时的 396 项计划内，正式粒子与正式输运均无提交，26 条正式 Z 暂无复用绑定。D0 最新粗步事件已完成验签收集与提取；控制器已收到接续指令：核对粗细步及零源读出、源前电流超限、日志和正式时序，逐器件审核双状态基线，满足共同与目标器件准入后自动派发首波。D1 双核诊断原档保留；新冻结的优先项可显式声明四核。满载性能和内存尚待真实负载验证。

## 当前执行覆盖：r0.6 已授权上线（2026-11-17 UTC）

以 `plans/dram-se-ddr5-lpddr5/EXECUTION-AUTHORIZATION-r06-20261117.md` 为当前执行依据，覆盖下文旧 r0.4/r0.5 预算、人工等待及九并发默认说明。13 个 profile、10 个辐照条件、396 个计划槽位（含 26 条 Z），214 是有统计用途的槽位上限，当前科学合格数为 0。诊断与性能测试独立记账，不填正式完成率。22 ns 仍是需验证的候选，P0 科学证据通过后执行方自行放行，不再等待用户逐阶段审批。

2026-11-18 服务器已扩为 14 核，系统可见内存约 31 GiB，虚拟机分配 11 核、28 GiB 内存，QEMU 绑定服务器 CPU0–10。5×2 的五项任务已全部收集释放，四项退出 0，D1 写 1 按用户要求停止后以退出码 143 收集。1×10 的 D0 O2 写 0 已退出 0 并收集。原 10×1 于 2026-11-19 02:03 UTC 提交十项单线程任务，使用虚拟机 CPU0–9，CPU10 留作后台余量。截至 08:15 UTC，八项已退出 0 并收集，D1 写 1 的两个副本仍在求解。6×1+2×2 已取消。Geant4 沿用原 profile。原自动派发控制器在性能对照期间维持维护暂停。

本轮输入及运行证据在服务器 `<SIM_USER_HOME>/course-workspace/local_runtime/r06-compare-20261118/`。`one-ten-events.jsonl` 和 `ten-one-events.jsonl` 记录各批次的原提交与收集。5×2 满载期采样完整，D1 写 1 尾段采样在 14:02 UTC 恢复，中间存在采样缺口。网站每分钟读取原任务进程、CPU 绑定、虚拟机可用内存及日志物理时间，原始输入和调度状态由原 runner 维护。

2026-11-19 用户决定在 10×1 原批全部收集并释放后，正式使用 6 个单核槽和 2 个双核槽。CPU0–5 分给单核槽，CPU6–7、8–9 分别组成双核槽，CPU10 留给后台。新冻结输入中 D1 写 1（`D1-short-channel`、`stored_bit=1`）使用双核，其余默认单核。已有冻结的双核输入沿用其资源声明。遇到其他持续收敛困难的条件，保留原证据，下一次经原修复规则提交的输入可声明双核。调度按每项冻结声明匹配空槽，求解中途不改线程数。Geant4 保持原 profile 和最多 4 并发，只在原池空闲时轮换。按 P0、开发、冻结留出的依赖顺序推进 396 个计划槽位，跳过额外并发跑分。

原 `tcad-autonomy.service` 是唯一求解调度者。最新部署为 `20261117T184322Z-r06-intent-reconcile-r1`，readiness 为 `<SERVER_CONFIG_DIR>/readiness-r06-20261117-intent-reconcile-r1.json`；部署收据位于 `<SERVER_STATE_DIR>/operations/20261117-r06-intent-reconciliation-r1/`。已完成有界日志 PMI 的真实编译与收集；D1/D2 的新 P0 几何/DC 已实际进入原生求解。D0 首条短诊断因启动前历史终态兼容问题留下缺失 manifest 的原 intent，新修复仅允许用原始失败、冻结输入、历史运行器和原池的完整证据将其闭合为失败，再经新 ID/目录与 `repair_of` 继续；不能重放原 ID、伪造 manifest 或把结案计成求解/科学通过。实际对账、收集和后续启动均以最新原 observation 及收据为准。

截至 `19:11 UTC`：D1/D2 几何/DC 均已退出 0、核验收集并释放；D0 原失败已独立对账，新修复短诊断也已退出 0、核验收集并释放，原 B 依赖沿成功修复谱系自动解除并实际运行。原服务 active/enabled；科学合格数仍为 0。详细上线记录见 `plans/dram-se-ddr5-lpddr5/DEPLOYMENT-REPORT-r06-20261117.md`。桌面旧每小时巡检实际为 PAUSED，本次保留该状态，持续执行由服务器原服务负责。

原状态页已部署 r0.6，最终网页 revision 为 `e9cea0bfcd8b9c9d4c34ccea1c3c8eaae4653175`，
读取同一清单、Runtime、观测和原归档，分别显示 P0、工程收集与科学通过。HR/HP 明细
保持封存，公开计划分母不会因隐藏明细或重试改变。接口见网站的
`ops/PROGRESS-INTERFACE.md`；不手写公开 `status.json`。接口现在还支持私有的
`r06-gate/results/z-baseline-reuse/<case_id>.json` 完整 WHR P0→Z 复用绑定；
它要求冻结清单、profile/bit、`r06-hold-window-v1`、完整 input map、结果 SHA 和
实际证据，短 prefix 不得计入正式 Z，统计资格仍独立且尚未接入。

最新观测（`2026-11-17T19:44:44Z`）显示原 Runtime 明确运行 3 项 P0：
D0 O2 短零源、D1 网格测量和 D2 网格测量；D0 prefix-b 已成功收集并释放。
服务仍 active/enabled，`discovery_uncertain=false`，正式科学合格数仍为 0。

空间分别报告服务器剩余空间、虚拟机分配空间、虚拟机剩余空间、服务器上虚拟机磁盘文件可增长空间，不相加。服务器至少留 20 GiB；每波还核对虚拟机与底层写入池能否容纳在途输出和收集副本。长期执行仍须经过日志/源积分/数值重复性、正式时序和各 profile 的无粒子体检，再进入开发与冻结后的留出验证；服务在线不是截面或错误率已完成。

## 当前执行：双核四并发短测通过、`/home` 增加40GiB（2026-11-17 UTC）

用户已明确授权立即暂停当前任务，不等待自然完成。原4个单核 `sdevice` 已于03:10:40 UTC退出143，全部沿原ID由原runner收集为 `FAILED_COLLECTED`，归档核验和槽位释放通过；没有把中止结果计为成功科研响应。双核阶梯验收后，原 `tcad-autonomy.service` 已于05:05:26 UTC恢复，加载 `20261117T045000Z-mc2-four`，保持原唯一调度者、owner、共享池及锁。下文“原4项继续原样运行”或“默认9个单核任务”的历史表述由本节覆盖；服务在线与真实native运行仍分别核对。

03:41:40 UTC已在线扩展原虚拟机 `/dev/sda3`、PV、`centos/home` 和XFS，`/home` 从46.99GiB增加到86.99GiB，增量精确40GiB；当时 `df` 为87G总量、47G已用、40G可用、55%。文件系统UUID和虚拟机boot ID均保持，未重启VM。保留分区首MiB、分区表和LVM前后备份。底层有界ext4写入池从64GiB扩至71GiB；虚拟机逻辑余量不等于底层物理余量，继续按两层实际空间核查并保留服务器管理缓冲。

04:04 UTC已在线打通现有overlay的discard回收，并在原launch配置中持久化 `discard=unmap`；QEMU PID仍为2757，源base保持只读且mtime不变。先将15个虚拟机重复归档逐一与服务器权威归档、原receipt及双方SHA核验，再仅删除 `.collection/results.tar` 副本，共23,407,360,000字节；原输入、原始输出、日志、身份、receipt和服务器归档保留。虚拟机XFS及底层ext4两层trim后，04:17 UTC收据为：虚拟机 `/home` 87G总量、30G已用、58G可用、34%；底层实际可用约42.5GiB，服务器根可用约65.4GiB。新增40GiB具备实际落盘余量，服务器总盘仍为170GiB。该收据不是整月432项长任务存储容量的承诺。

扩容和原任务收集证据：`local_runtime/server-codex/operations/20261117T034000Z-expand-home-40g/`；中止证据：`local_runtime/server-codex/operations/20261117T030631Z-pause-current-r04/`。最新只读05:08 UTC读数：虚拟机 `/home` 可用约57.3GiB，底层写入池约42.1GiB，服务器根约64.8GiB；实际长期占用仍随计算变化。

当前新TCAD使用 **2核×4并发**：本机 `local_runtime/cloud-benchmark/connection-centos79-guest-mc2-four.json`，服务器同目录 `connection-local-centos79-mc2-four.json`，显式 `parallel_capacity=4`、`requested_threads=2`、CPU集 `[[0,1],[2,3],[4,5],[6,7]]`；CPU8余量，服务器9–11仍留管理。新输入显式 `native_threads=2`、`native_cores=2`。旧3/7/9单核profile及全部原run保留。Geant4用policy/readiness固定的原nine单核profile，仅全部核验收集释放后的空闲池轮换，两类计算全局最多4任务，不另建池或混用活动容量。

七份1/2/4任务双核短探针均已正常收集、释放原槽，并通过原数值容差：单任务374.68秒，两任务383.08–387.28秒，四任务427.52–430.32秒；assembly和solver均2线程。四项完整重叠有211个采样点、70份完整fresh PSS，其合计峰值8.33GiB，guest MemAvailable最低17.8GiB、host最低1.44GiB，swap I/O与服务器VM cgroup OOM增量0。所观察native/TID均未越槽；虚拟机独立cgroup OOM未采，不能写成0。详见 `local_runtime/server-codex/operations/20261117T040500Z-mc2-benchmark/BENCHMARK-REPORT.md`、`resource-analysis.json` 和三份 `audit-n*.json`。历史单核参考不是本轮受控对照，短探针新增科研样本0，不线性外推真实事件长瞬态或扩大月度预算。

正式长任务输入另做了必要的PMI日志计数器最小修复：普通 `uint64_t` 计数改为 `atomic`/`fetch_add(relaxed)`，避免共享实例并发回调的数据竞争；头文件、载流子源数据、物理公式、mesh/deck和判据保留。原SDK编译、导出与依赖检查通过，原单核operation已收集释放；新源码SHA `6c2360c8b75840561fb61a61dccc8fddde0d4e14061f65cbd1a6f748bdb77b75`，新ELF SHA `ca05ab0350b27777fbce6a7aedea2b0c811bedb8bdee7581433af18804c98f65`。仅用于四个从未提交的 `mc2-r2` 修复输入，原任务及旧ELF不改；新ID与 `repair_of` 保留谱系。SDK内部并发实现和真实长瞬态的源/读出/数值一致性仍依原结果验收，必要的匹配对照由原队列准备，不放宽科学判据。

## r0.5 首月预算覆盖（2026-11-17）

首月按 [BUDGET-REDUCTION-20261117.md](../plans/dram-se-ddr5-lpddr5/BUDGET-REDUCTION-20261117.md) 执行：6个器件profile、16核心工况、最多2备用工况，核心384、最大432个 b0/b1 主响应，另12个可复用profile级无粒子对照。原3,072个独立统计补样和主动数值细化延期。逐例计划 `plans/dram-se-ddr5-lpddr5/month-one-cases-r05.json` 已部署并核验444个唯一case、216个主响应pair；它只定义计划与稳定ID，不替代原执行账本。新r0.5全部尚未绑定；历史r04一个基准器件已有event4 b0/b1两条有条件有效未翻转及匹配zero，不能把历史或性能probe填成新计划已完成。

状态页从原队列/runtime/manifest和最新observation投影；`<SERVER_STATE_DIR>/web-observation.json` 仅是本次有时效的维护快照，交回自主模式后读 `observation.json`，不能反复展示旧RUNNING。线上Codex展示注释接口见 `<PUBLIC_SITE_DIR>/ops/PROGRESS-INTERFACE.md`，通过正式CLI写独立私有展示库，不改原运行状态、科学验收或计划分母。每小时巡检已迁到本会话，使用既有automation `tcad`，4×2协议、首月预算及进展接口均由其最新提示接续。

## r0.4研究批已启动（2026-11-16 12:28 UTC快照）

用户已授权启动DDR5/LPDDR5计划中的r0.4质子批及必要修复、数据收集。`tcad-autonomy.service`于11:58:07 UTC启用，在原`<SIM_USER_HOME>/course-workspace`使用Magpie的`auto/gpt-6.1-sol / high`推进；本轮唯一调度者为服务器Codex控制器，本地只读跟踪并提供研究决定与必要修复，不并行另投求解。

仍使用原九槽profile、runner、owner、账本和共享锁，最多9个独立单核任务；当前快照不表示已有9项科研任务同时运行。首批六个新L08质子输运输入已实际执行，但因固定Geant4 10.7.3路径缺失而失败，已沿原ID全部收集为`FAILED_COLLECTED`。指定软件及四套配套数据已恢复，等待服务器以`repair_of`生成修复输入，禁止原ID重复提交。

独立TCAD任务`auto-r04-l08-p000-electrical-v1-0ab40348a7d84362`已完成SDE几何和snmesh网格，原账本及虚拟机实际进程均确认进入`sdevice`求解。此处证明原生研究计算已经开始，不代表电学校准、截面或错误率已完成。

控制器在模型轮次自然结束后的12:27:03 UTC重载，保留全部运行状态；已加载模型工作期间持续监督同一runtime的既有改进，以及有完整身份的快速失败应进入原status/collect的局部修复。40项runtime离线测试在本地和服务器通过，原生求解结果另行验收。计划与逐次执行记录见`plans/dram-se-ddr5-lpddr5/EXECUTION.md`，本地启动证据见工作区`output/server-start-r04-20261116/`。正式训练和网页部署尚未启动。

## 12核扩容与九并发短探针验收完成（2026-11-16 UTC）

**当前推荐：服务器12vCPU／32GB，完整CentOS7.9虚拟机9vCPU／28GiB，最多9个独立任务各1核。** Rocky9.8服务器SSH、Tailscale、Codex及Magpie已恢复复核；QEMU有效CPU集0–8，CPU9–11不分配给QEMU以留管理余量，MemoryHigh29GiB／MemoryMax30GiB。服务器管理进程未全部强制绑至9–11，不称完全独占。原硬件身份保持，源VM保持挂起。

原runner九槽r3已部署：本机profile `local_runtime/cloud-benchmark/connection-centos79-guest-nine.json`，服务器profile `local_runtime/cloud-benchmark/connection-local-centos79-nine.json`，slot0–8共享同一池。旧3/7配置与原结果保留，禁止用旧可执行备份另开池或新投任务；按已授权批次和依赖填槽，内存／许可不足降并发。

九份`20261116-capacity-n9-probe-s0-r1`至`s8-r1`均COLLECTED／exit0／归档核验及槽位释放通过。每份21点，gate0.3V／drain0.1V；工程与数值重复性审计通过，共3024电流值与历史真实n1最大差0A，固定容差不变。这是短探针重复计算，不计新增科研样本。

闭合监控实测：平均原生wall731.44s、保守吞吐39.75同类探针／小时，完整同时PSS峰18.232GiB、VM服务器侧采样峰20.598GiB，虚拟机／服务器最低可用8.252／9.663GiB，swap及换页0、服务器和cgroup OOM增量0；虚拟机OOM字段缺失=null。全9重叠时虚拟机CPU约99.78%。相对扩容前七并发31.69任务／小时，描述性增加25.41%，属于跨扩核重启历史参考，受控加速与效率仍null。一个采样tick有两次退出竞态，不完整样本已排除完整峰；PSI及部分cgroup配额／I/O缺失，不推断这些指标。

10:27Z最终复核无活动solver／wrapper，九租约均COLLECTED、相关锁空闲，五项通用及虚拟机服务active／enabled、SELinux Enforcing。服务器根可用122.21GiB，有界overlay可用60.70GiB，两者不可相加，暂不加盘；32GB内存先保留。监控正常闭合并冻结SHA，未再启动仿真或11并发。

**未通过／未验证：** 原`许可校验工具` exit255／文件完整性失败仍未解除，实际短求解不能替代正式许可验收。旧七份长D2按要求中止并保留FAILED_COLLECTED／143，不重投；完整两条201点D2、长任务全程峰值／总工期及11并发未验证，不由21点探针外推。下方8核／七槽及运行中快照均为历史，由本节覆盖。

证据根`local_runtime/server-rocky9-recovery-20261116T043810Z/`：`nine-vcpu-guest.json`、`nine-slot-deployment.json`、`closed-nine-capacity-monitors.json`、`final-nine-capacity-verification.json`；资源`capacity-analysis/n9-closed-analysis-20261116T102109Z.*.json`及`n9-compact-metrics-20261116T102109Z.json`；数值`capacity-audit-work/n1-n9-real-audit.json`。完整报告位于工作区`output/server-benchmark-20261115/CAPACITY-12CPU-REPORT-20261116.md`；文档／本地及云端两技能同步以`nine-guidance-sync.json`收据为准。

## 扩容前已停妥（2026-11-16 09:40 UTC）

本节覆盖下方运行中快照。用户准备在控制台把服务器从8核扩到12核，32GB内存和170GB订单磁盘保持；截图新费率$0.0179/小时、差额+$0.0008/小时（页面估计+$0.58/月），仅为用户提供的本次报价，尚不表示配置已生效。用户自行控制台重启，主代理不关闭或重启Rocky服务器。

- 7个原长D2于09:24Z按用户要求中止，全部由原runner收集为`FAILED_COLLECTED`、exit143，归档SHA核验、collection_verified和slot释放全部通过；未完成两条201点扫描，不计完整D2通过或成功吞吐。
- 09:27Z两端资源监控正常写footer、error=null、stop_reason=signal；闭合原日志已冻结并逐件核验SHA，路径见`resize-ready.json`。
- 09:40:39Z CentOS虚拟机经原服务ACPI正常关闭，ExecStop0、Result=success、inactive/dead、原QEMU已退出；overlay `qemu-img check` exit0。关机前无活动solver/wrapper，7槽租约均COLLECTED，9个相关锁可独占取得。Rocky服务器仍在线，未禁用虚拟机、SSH、Tailscale或通用服务自启。
- 16个1/3/5/7并发探针全部原runner收集exit0，完整数值审计通过：每份21唯一点，15候选各336电流值与n1完全相同；不是新增科研独立样本。
- 建议12核/32GB扩容后先测9个单核任务；相对7任务的理想吞吐上限+28.57%，11任务为+57.14%，均未实测，不能承诺线性收益或直接开启11槽。现有真实部署仍为7槽/7vCPU/28GiB，扩容生效后先核对服务器CPU、boot、自启和许可，再按空闲池约束调整；不提前改上限、不重投旧run。

证据：工程`local_runtime/server-rocky9-recovery-20261116T043810Z/resize-ready.json`、`closed-capacity-monitors.json`、`post-stop-long-status.json`和`capacity-events/`；16探针数值审计`capacity-audit-work/n1-n3-n5-n7-real-audit.json`。许可原`许可校验工具` exit255/完整性失败仍未解除，实际求解不能替代正式许可验收。源VM保持挂起。

## 当前架构与验收边界（2026-11-16 UTC）

Rocky Linux9.8服务器已重装为 **8vCPU/32GB**；SSH、原Tailscale身份、Codex、Magpie和回环代理已恢复并实测。仿真保留在完整 **CentOS7.9虚拟机**内，用户最新授权虚拟机 **7vCPU/28GiB**、最多7个独立单核任务；QEMU仅可使用服务器CPU0–6，CPU7留系统和管理。28GiB是整台虚拟机内存，包含虚拟机系统、许可服务和所有任务，不是每任务4GiB的保证。

完整基础盘已上传并通过整件SHA与QCOW2检查；源VM已挂起，禁止恢复源VM与同身份云副本并开。普通硬盘内核、7vCPU／28GiB虚拟机资源、普通ACPI正常关机及服务器重启后的服务／overlay／虚拟机自动恢复均已实测。首次rescue ACPI超时的失败证据保留；后来普通内核正常关机与QCOW2检查通过。重启后PN在slot6执行、收集及数值审计通过，证明该短工程可在云端独立运行。**7并发长期峰值、吞吐和完整DRAM长解按当前容量测试实测，不由配置或PN通过推断。**

虚拟机原许可服务的 `许可状态工具` 已观察到server/vendor up，但原厂 `许可校验工具` 退出255并报告文件完整性失败，**正式许可完整性尚未通过**；后续短求解成功也不能覆盖此失败。保留原文件与证据，不修改签名、时间或硬件标识绕过校验。

权威进度：工作区 `output/server-benchmark-20261115/CURRENT-DECISIONS.md`、`HANDOFF.md`；本次恢复证据：工程 `local_runtime/server-rocky9-recovery-20261116T043810Z/`。其中上传/staging状态文件名是旧脚本固定终态，判断运行态须结合最新guest证据与实时进程。

## 接入与原运行器

| 用途 | 入口 |
|---|---|
| 本机工程与版本 | `E:/TCAD-Workspace/tcad-research-training` |
| TCAD 管理 | `ssh 管理入口` |
| TCAD 仿真用户 | `ssh 仿真入口` |
| 原公网回退 | `公网回退入口` / `公网仿真入口`，仅按已有任务配置使用 |
| 服务器独立控制工作区 | `<SIM_USER_HOME>/course-workspace`，执行前读其 `CLOUD-ENTRY.md` |
| 求解入口 | 原 `scripts/tcad.py`；Geant4原 `transport-probe/operation.py` |
| 本机到完整虚拟机九槽profile | `local_runtime/cloud-benchmark/connection-centos79-guest-nine.json` |
| 服务器到虚拟机九槽profile | `local_runtime/cloud-benchmark/connection-local-centos79-nine.json`，位于服务器控制工作区 |
| 虚拟机工程根 | `<SIM_USER_HOME>/research-training` |
| 服务器内部虚拟机SSH | `虚拟机管理入口` / `虚拟机仿真入口`，按 `<VM_SSH_CONFIG>` 固定公钥 |
| 服务器到虚拟机转发 | 仅 `127.0.0.1:22279`；虚拟机隔离，不对公网提供CentOS7服务 |
| 虚拟机服务 | `tcad-centos79-vm.service`，自启及重启验收见最新交接 |
| 云端技能 | 仿真用户 `~/.codex/skills/`，以本次部署验证记录为准 |

服务器运行原runner使用 **`python3.12`**；系统Python3.9保留，不把服务器Python版本当成虚拟机工具依赖。连接文件含本机状态路径，不公开或跨机器直接照抄。新profile须经主代理核验并完成实际部署后使用，不覆盖历史作业连接。

业务服务器 `业务服务器入口` 与 TCAD 是两台机器，不可混用。
SSH 使用既有别名、专用密钥和严格主机校验；不传入 GitHub 本机代理配置。
重装前服务器 `/opt/tcad-centos79` 与 `/srv/tcad-migration/minimal/scripts/enter-runtime.sh` 已被清盘，仅为历史路径，不能作为现环境入口。

## 每次实际执行
1. 读本仓库 AGENTS、目标实验计划、最新交接；核对原 run ID、目录、进程与锁。
2. 使用既有 connection、runner 和 owner；由本批授权的唯一调度者执行，先核对各slot及所有活动求解器。本轮由server-codex接任，不另开本地调度。
3. 输入、参数和实际源码SHA冻结后才提交新ID；每任务1数值线程/1核，有依赖的网格、初始化、电学和提取仍按序。
4. 断连后定位原作业并恢复状态/收集；不重复提交，不清锁，不覆盖结果。
5. 保存退出码、完整日志、输入输出哈希；再检查收敛、单位、守恒与模型适用性。
6. 课程共用索引引用审核后的摘要；`COLLECTED` 不表示科学结论合格。

可读入口帮助：服务器用 `python3.12 scripts/tcad.py --help`；具体参数沿用实际部署和原任务记录。
不要为了解目录执行 `doctor` 或 `sdevice -v`：历史环境中版本检查也可能签出许可。

## 七槽调度

新虚拟机profile显式设置 `parallel_capacity=7`，使用原runner的 `--parallel-slot 0` 至 `--parallel-slot 6`；槽号对应虚拟机CPU号。原 `transport-probe/operation.py` 共用同一池，**两接口合计最多7任务**。没有容量字段的旧profile继续缺省3槽；底层CLI未指定slot时仍为旧串行模式。既有记录、连接、wrapper和运行中affinity不改。

示例仅说明参数位置，先核对帮助、实际profile及源码，不将占位符直接执行：

```powershell
python scripts/tcad.py --connection <本批次已绑定profile> run <冻结工程目录> --run-id <新ID> --detach --parallel-slot 0
```

对已授权且依赖就绪的任务，按已验证容量填槽；内存余量、许可容量或科学依赖不足时主动降并发。不能把28GiB平均分配所得数字当作安全峰值，也不能由7槽上限声称7倍吞吐。新任务使用独立profile，已有任务的公网profile、身份、远端目录不改。

待收集的终态任务保留槽租约，归档验签、原身份闭环与receipt确认后才释放并补下一项；状态不明或失败先保留证据，不自动重投。锁模型沿用全局gate共享锁、每槽独占锁及allocator锁；旧串行任务持全局独占锁，与并行批次互斥。池容量切换只能发生在全部租约已收集、槽锁空闲且无未登记求解器时；活跃池不同容量混用须拒绝，不能以另建profile得到第二套7槽。

每任务冻结原PID/start_ticks/boot、CPU、脚本SHA和连接身份，status/collect核对同一原始身份。配置授权、协议测试、真实并发与性能评估分别记录。七槽实现及空闲协议测试已通过、代码已部署，slot6短PN实跑／收集通过；长期性能按本轮容量基准实测。短PN与探针只支持其测试范围，不能代替完整DRAM扫描、长期峰值或科研验收。此前中止D2保留失败归档；用户新授权的长基准用新run ID和冻结原输入，不重投旧ID。

## 存储、维护与许可

基础盘只读；guest可写overlay位于有明确上限的独立文件系统，2026-11-17已从64GiB在线扩至71GiB，服务器保留至少20GiB缓冲并预留待收集归档空间。guest磁盘逻辑500GiB不代表可写500GiB；观察overlay及服务器两层物理余量并及时归档，不能按guest的 `df` 余量填满服务器。已收集归档的虚拟机 `.collection/results.tar` 副本只可在服务器原归档、receipt和双方SHA一致后删除；保留原run输入、原始输出、日志、身份和receipt，不删除服务器权威归档。

Rocky9服务器与CentOS7虚拟机分别维护；升级服务器不能消除旧虚拟机或原软件依赖中的漏洞。保留隔离、SELinux和回环SSH，不为兼容直接升级guest大版本。当前软件记录为Sentaurus W-2024.09、Geant4 10.7.3；实际工具、许可签出与求解能力以本轮日志为准。

旧Windows许可relay只在新虚拟机独立签出及恢复验收后由主代理核对身份再撤除，不因daemon up就自行停止。源VM保持挂起，旧结果、失败证据与长期登录设置保留；不要自动启动或停止历史脚本。

原始日志、受限软件、许可证、密钥、虚拟机不纳入课程包或技能包。
完整软件性能、内存需求与科学验收以主任务报告和真实终态为准。


## 2026-11-17 05:14 UTC actual native restoration receipt

05:12:28 UTC原observation已更新为active/running=4、max_parallel_jobs=4、r4双核、discovery_uncertain=false且无新任务blocked/pending。05:12:49 UTC四个新mc2-r2原生SDevice均在运行，原wrapper PID/start_ticks/boot及父子链已核验，全部实际TID在各自CPU集内；当时两秒CPU采样约100/142/100/147%，并非持续两核满载。05:13:56 UTC四份原生日志均明确assembly/solver threads=2，新atomic PMI实际加载、日志及BE时间步推进。四项为同一基准器件的c00/event7377与c01/event0各b0/b1，科学新增仍0，完整长瞬态性能和验收待完成后更新。

同期空间：guest /home可用56.93GiB，overlay实际余量41.91GiB，host根可用64.61GiB。新增40GiB已落实，guest未重启、host总盘仍170GiB；这些读数不是整月全部原始数据的容量承诺。automation tcad已核验ACTIVE/每小时/当前会话。完整本轮收据见local_runtime/server-codex/operations/20261117T040500Z-mc2-benchmark/FINAL-RECEIPT.json；服务器同名收据在local_runtime/mc2-benchmark-20261117/。


## 2026-11-17 成功结果保留与空间循环实际验收

用户授权成功组仅留关键数据并回收大文件，32GB服务器内存上限不变。存储策略见RESULT-RETENTION.md，
最新成本见RUN-TIME-ESTIMATE-20261117.md。原runner、manifest、输入、数值判据及r0.5清单SHA未改。
13:11 UTC四份原mc2事件已由原Runtime串行完成保留事务；原归档SHA、压缩恢复SHA及全部新产物校验通过。
已回收guest重复件20.942GiB、host未压缩归档净节省12.794GiB。
四份关键数据合计147.66MiB，单份34.16–39.78MiB；
待zero及科学解释的临时无损备份合计0.989GiB，未提前finalize。
同规模300个单状态响应的host关键包约10–12GiB；guest非日志小文件及活动归档缓冲另计。

四条事件缓存继续复用，标签unknown；两个原mc2 zero仍在运行，四条r04不填进r0.5完成。
读取已回收的原tar必须使用result_maintenance.py read包装入口，完整maintain/finalize/read事务有同一run锁。
后续新成功结果提取缓存后ready；原Runtime负责单worker回收。对照及科学解释结束才按release契约finalize，
zero须等全部依赖事件比较完成。不能直接对已缺原tar的目录重复collect或提取已有缓存。

guest /home、实际overlay及host根可用分别约52.04/37.53/58.99GiB。
guest与host原fstrim.timer已启用为每小时10/15分，分别只处理/home和有界overlay。
首次额外host根trim等待超时并已撤下，原service的停止/缩小范围证据保留；最终双层trim均Result=success/exit0。
管理链路一次超时后已恢复，未重投仿真、未重启VM或结束求解器。

本地64项Runtime测试及14项归档/6项事务兼容测试通过；Linux20项存储测试通过。
控制器release为<AUTONOMY_INSTALL_DIR>/releases/20261117T1230Z-result-retention，事务补丁未重启控制器。
每小时automation tcad仍ACTIVE且绑定本会话，提示词已缩至659字符。
CPU建议暂不加预算：四条完整wall均值5.809h、CPU/wall约1.4，四槽持续有就绪任务时保守350–420响应/月；
300单状态响应21–26天，300对响应43–52天，384核心+12zero约28–34天。
保持12vCPU/32GB服务器、9vCPU/28GiB虚拟机及2核×4并发，归档串行；host和guest可用内存不相加。

完整收据：local_runtime/server-codex/operations/20261117T1230Z-result-retention/FINAL-RECEIPT.json；
服务器<SERVER_STATE_DIR>/operations/20261117T1230Z-result-retention/FINAL-RECEIPT.json。
