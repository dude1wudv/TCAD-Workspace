<!-- COURSE_PLAN_R13_CURRENT -->
## 当前方向：课程项目 + 先进DRAM选型补充（r13）

用户明确课程项目仍为主任务；LPDDR5/6相关工艺选型为新增方向，α与质子为当前粒子，质子使用Geant4，指定轨道仅为可选。按无粒子基线→α响应→质子耦合→多参数拟合/外推→作品展示推进。详见 `experiments/dram-see-v4/course-plan-r13/README.md` 与其计划/跟踪表。

当前仅规划与离线准备：原active-entry仍READ_ONLY_HOLD；R12 QY候选未编译、未发布、未运行，15项Python离线检查通过不等于原生资格。原PMI失败与全部历史结果/账本保留；新几何、新源接口和新矩阵须分别冻结合同、预算与执行发布。半小时任务已改为精简的新方向提示词；下文是原阶段历史，不能据旧“运行/授权”快照恢复旧队列。
<!-- COURSE_PLAN_R13_CURRENT_END -->

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

# 自然核次级三维闭环：独立修订 r1

当前资格状态更新：r8读档评估通过工程接口核验，但原零源69帧PMI时间/步长/步型全0，414项原门失败。当前候选continue_values_r8.py及release-values-r8.json为READ_ONLY_HOLD、execution_enabled=false，不启动接续；r7已退出，正点未提交。见 [FIELD-VALUES-R8.md](FIELD-VALUES-R8.md) 与 [PMI-QUALIFICATION-R9.md](PMI-QUALIFICATION-R9.md)。下文r7/r6作为历史实施说明保留，最新active-entry与现场优先。


用户已授权实施新计划。旧二维批次为 **SUPERSEDED_PARTIAL**：15/17 角色通过、16 次新调用、含历史21次，细网格A1失败保留，原A5不再接续。旧合同、代码、gate、账本及原档均不改写。

当前状态以原始进程、调用账本和最新现场报告为准；`status.json` 仅作调度状态参考。准备期间不能因新目录存在而执行；各阶段须有对应 `release-<stage>.json` 和独立/根验收记录。唯一所有者继续使用原 recovery continuation 的 owner.lock；求解和原生后处理仍受远端共享锁、单线程、单核约束。

当前有效入口已推进到本目录 `continue_fields_r7.py`，由 runtime 的 `active-entry.json` 绑定。原 `continue.py`、`continue_material_r2.py`、`continue_audit_r3.py` 和首次 H 初始化失败均保留，不再启动旧入口。当前三段 release 已发布，原生资格与科学验收仍分别由实际结果决定。现场报告入口为 runtime 的 `latest-progress-check.txt`；`observe.py` 只核查并留档。`status.json` 的初始计数字段和历史 error 不作为最新预算，全部调用以 `attempts/` 重算与 `budget.json` 为准。

射偏审计修订见 [AUDIT-R3.md](AUDIT-R3.md)：严格零器件步数/能量与完整 World 微小能量账本分开检查；旧失败保留，新审计只重用原档，不重放。`release-fields-r7.json` 冻结当前入口及完整依赖，`release-audit-index-r5.json` 继续绑定未改的输运依赖；原 `release-audit-r3.json` 保留；原 implementation-decisions.md 中旧入口和旧 release 作为历史保留，以此处和 active-entry.json 为准。

材料工程修订见 [MATERIAL-R2.md](MATERIAL-R2.md)：默认 NIST SiO₂ 2.32 g/cm³ 不满足原共享合同 2.20；独立实现恢复合同密度并保留原生核验一致的自然组分与电磁材料属性。H 初始化仅通过单列纠错请求重做；原失败没有删除、改判或从账本扣除。

目标是同一材料几何内的自然核见证及整个事件联合三维首次读出响应；电子事件只能作前置验证。新调用上限由 contract.json 和 transport-contract.json 精确冻结：14次必做TCAD+4次纠错；107次正常输运请求、1,000,008个不同初级事件；2次工程修复输运请求最多重放20,000初级，不算新的独立样本。新采样48小时窗口只限制后续提交，不结束健康运行的批次。

保留所有已开始阶段的事件。按固定请求顺序、event ID选择首个合格核见证，不看TCAD响应、不强制反应、不移动厚靶事件。先冻结真实事件，再冻结覆盖它和人工验证源的公共网格。新矩阵独立验证自己的源项、匹配对照、完整接受步及四边和对角数值比较。

源采用空间 Gaussian w=30nm、时间sigma=2ps，逐步原始端点和时间的相关积分；真正点沉积不补长度。t_device=1ns+t_Geant。只计算首次0–4ns响应，晚沉积、非Si和核越界分账，不重新归一化。此为代表模型的源映射假设，不是器件工艺校准。

PMI接口需原生验证编译/ABI/加载、R=-G、ReadTime秒单位和三维坐标；原字段HeavyIonGeneration的gate不作为PMI验收。原始退出未知就保持未知，工程完成与科学验收分开。修复需精确失败、根因、独立修订和离线验证，同根因修复再失败暂停分支，不盲重跑。

首次核闭环通过后才设计器件校准、正式事件分组和预测实验；本批没有训练、持久翻转标签、发生率或空间谱推断。保留v3和原交付，不安装、不提交推送、不外发。

后续研究依赖和结论边界见 [研究后续路线](RESEARCH-ROADMAP.md)。所有故障测试使用隔离目录；原生编译、材料探针、输运、TCAD与后处理成本分开保存。

当前组合修订：[STORAGE-R4.md](STORAGE-R4.md) 记录固定输入成本分拆和资源门；[AUDIT-INDEX-R5.md](AUDIT-INDEX-R5.md) 记录等价索引及实测成本。storage-r4入口仅作为已验证依赖，未单独启动。新入口继续使用同一原运行器、原owner锁、冻结种子/请求和source/device验收链。

P0与N1共1008个初级已完成记录验收，尚无合格核见证。下一请求为既定N2的9000个初级。48小时窗口从2026-10-15T04:49:03.864893Z计时，不因工程修订重置。运行中的进度以runtime latest-progress-check.txt为准；本段只记截至首次N2接续的阶段事实。

PMI工程接续见 [PMI-R6.md](PMI-R6.md)。P0/N1/N2/N3现已全部通过；N3完整结束后选中h-008/event5893自然核见证，不进入N4。原PMI Cmi编译成功而裸ldd库环境失败，原78/78/0保留；r6仅复用原ELF补完SDK依赖和六oracle验证，之后仍需两个原生PMI资格案例。14项隔离测试和独立静态审查已通过。当前实际运行和预算以runtime现场报告与attempt账本为准。

全帧索引接续见 [FIELD-INDEX-R7.md](FIELD-INDEX-R7.md)：原qualification-zero已正常完成4ns，旧解析器漏认精确原生RHS收敛句；r7保留全部69帧（含0000），9项定向测试通过，仅切换后处理绑定，复用原结果不重算。PMI工程补完六oracle已通过；原生全帧/配对资格和科学门仍须真实结果。
