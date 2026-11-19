# r0.5首月服务器执行交接

2026-11-16，用户指令：“启动服务器仿真，我们这边继续商量获得仿真数据后怎么完成自然语言处理和预测模型训练”。

## 授权范围

本次授权服务器自主准备模型、生成输入、启动并推进r0.4质子首批、修复真实失败、收集和整理数据。2026-11-17 起按 [BUDGET-REDUCTION-20261117.md](BUDGET-REDUCTION-20261117.md) 收敛为首月16个核心工况、最多2个备用工况，主响应上限432个；12个 profile 级无粒子对照可复用。原384工况和3,072个独立统计补样延期，新增粒子、不同研究对象或改变最终测试用途另行决定。

自然语言产品设计和正式预测网络训练方案继续由本地对话讨论。本次可完成数据格式、提取与数值诊断，不因现有总计划写有后续训练而立即启动正式超参搜索、揭示盲测标签或部署网页。

## 唯一运行入口

- 服务器工作区：`<SIM_USER_HOME>/course-workspace`。
- 控制器：`<AUTONOMY_INSTALL_DIR>/current/controller.py`，状态在`<SERVER_STATE_DIR>`。
- 原九槽profile：`local_runtime/cloud-benchmark/connection-local-centos79-nine.json`。
- 原runner：`scripts/tcad.py`与`experiments/dram-see-v4/transport-probe/operation.py`。
- profile原状态根、虚拟机目录、owner和槽位不迁移；控制器改用实际原工作区，不在开发安装快照中建立第二套运行账本。
- `server-codex`接任本批唯一调度者；本地代理随后只读状态、提供研究决定与必要修复，不并行直接提交求解。
- 模型沿用Magpie的`auto/gpt-6.1-sol / high`。

## 首月预算与切换边界

- 当前已运行的四项原任务不改、不杀、不重投，沿原身份收集并释放槽位。
- 当前预算按四个单核长任务的6.42–6.48小时实测 wallclock 估算；核心16工况=384个 b0/b1 主响应，最多18工况=432个主响应。
- 当前批次排空后，才验证4并发、每任务2核心的候选 profile；单任务→双任务→四任务阶梯验证通过前，不提交多核任务，也不把潜在加速计入工期。

首次实时检查：九个旧租约均为COLLECTED，原gate及各槽锁可独占取得，虚拟机无活动原生求解进程，控制器未运行。此记录是启动前检查，不用于推断启动后的状态。

## 第一个实际工作包

当前没有已建成的L08/saddle-fin deck。旧BCAT几何、固定入射位置、30 nm源核和旧门禁不能直接冒充新模型。

1. 以L08原PDF、已核表图与原文提取建立新参数化几何和参数来源表，保留14 nm Lgt、8 nm Wfin、6 nm Tox等原定义；未公开参数列为明确代表假设和待校准量。
2. 在新结构材料/尺寸明确后，准备基准profile的真实Geant4输入；改为有面积定义的均匀源位置、保留所有primary及零沉积。记录实际Geant4版本、物理列表与选择理由，不将现有QGSP_BIC配置描述成Bertini复现。
3. Geant4可先于全部电学校准运行；同时推进TCAD几何/DC/写保持读基线。缺掺杂剖面只影响相应结论，不把旧BCAT浓度伪装成论文参数。
4. 沉积到TCAD源项采用有单位、积分、空间时间依据的映射，旧核不能无比较直接用于L08。真实事件到位后逐批生成匹配响应，持续补就绪任务。

第一轮应交付至少一个实际新输入包和队列提案，或有日志/来源依据的具体局部缺口及已推进的独立分支。不要重跑PN/旧短探针、创建重复审计文档来表示新研究已启动。

## 本地资料到服务器

L04/L05/L08论文及原文提取、L08结构图、导师题录将按SHA移交至本工作区`docs/sources/r04-start/`；这些是研究输入，不是已校准模型。以移交清单记录文件来源和哈希。

模型源码可以从旧工程复用实现方法，但新研究输入使用独立目录。既有实验、失败、原始归档和所有提交身份保留。只通过队列交给监督调用原runner。

## 启动后的记录

实际服务状态、第一轮模型产物及原生求解run ID在获得证据后追加。服务active、Codex正在准备输入、原生仿真RUNNING和结果已收集分别报告，不互相替代。

### 2026-11-16 11:58:07 UTC：控制器启用

- 资料包逐文件校验后移交，包SHA256：`99f26ce2dd7bf708a35c2cd5b928441f10cc296d539cd2419390ddca246c823e`。
- `tcad-autonomy.service`已enable并启动，实际WorkingDirectory为`<SIM_USER_HOME>/course-workspace`，模型`auto/gpt-6.1-sol / high`。
- 首轮cycle：`20261116T115807Z-13920ae5`。启动收据在服务器`<SERVER_STATE_DIR>/start-r04-20261116/activation.json`，本地副本在工作区`output/server-start-r04-20261116/activation.json`。
- 截至12:03 UTC已出现新`experiments/dram-se-r04/`结构来源、几何、TCAD候选deck及输运生成器；当时尚无队列任务。此处只证明自主准备已开始，原生求解证据另记。

### 2026-11-16 12:07 UTC：首批六项实际执行并失败

- 已生成L08新代表结构、TCAD电学候选及六个质子输运输入。六个开发工况依次为`(E/MeV, theta/deg, phi/deg)`：`(1,0,0)`、`(5,30,0)`、`(20,60,90)`、`(58,0,0)`、`(98,30,90)`、`(120,60,0)`，每项10000个primary。这是48个profile、384个工况设计的起步批，不是完整参数覆盖。
- 原runner确实分配slot0–5并执行了六份`task.sh`，均返回exit 1。原run ID以`auto-r04-l08-p000-c00-proton-v1-`至`c05`开头，完整身份保存在原operation账本；不得删除记录、原ID重复提交或把失败当成零沉积。
- 直接退出原因是任务固定引用的`Geant4-10.7.3-Linux/bin/geant4.sh`不存在。`/etc/profile`中的devtoolset与locale警告不是这次任务退出的直接原因，未修改系统profile。
- 该批尚未产生可用原生输运事件，不能据此宣称取得截面、错误率或训练标签。

### 2026-11-16 12:16:28 UTC：恢复计划指定的软件依赖

- 已从冻结来源恢复Geant4 10.7.3及G4EMLOW7.13、G4ENSDFSTATE2.3、PhotonEvaporation5.7、G4PARTICLEXS3.1.1，逐包记录SHA256；保留商业软件目录中独立的Geant4 11.1.2，不用于冒充计划版本。
- 虚拟机回执：`<SIM_USER_HOME>/research-training/software-restore-r04-20261116/install-receipt.json`；下载清单：服务器`/var/tmp/tcad-r04-geant4-restore-20261116/download-manifest.json`。
- 现有`/usr/local/bin/g++`为GCC 10.2.0。新修复输入应显式选择该编译器，并在`LD_LIBRARY_PATH`中前置`/usr/local/lib64`；已检查目标Geant4库的动态依赖解析。
- 恢复说明已交给服务器Codex。旧失败仍须按原ID收集，再以`repair_of`关联新输入和新运行，不改写旧输入。

### 2026-11-16：运行时修复验证与训练交互决定

- 已修复本地runtime把“有完整原任务身份的FINISHED/非零退出”误判为通用runner异常的问题；仅在原账本、目录、身份和退出码交叉一致时接受结构化失败，随后仍经原status/collect收集。未知启动继续保留原ID和退避。
- 40项runtime离线测试在本地通过，上传暂存目录后又在服务器Python 3.12下通过；此记录不等于修复已经加载，部署和实际恢复另行记录。
- 已部署的控制器源码包含模型工作期间持续监督同一runtime的逻辑，但11:58启动的进程未加载12:11切换的release。等待当前模型轮次自然结束，再安全重载；不另开调度者或中断远端求解。
- 用户已确认`auto`先预测、必要时后台补仿真，以及“分批训练候选版本、评价后替换稳定服务版本”。详细流程写入`POST-DATA-WORKFLOW.md`；本次仍未启动正式训练、超参搜索或网页部署。

### 2026-11-16 12:27–12:28 UTC：重载完成，真实TCAD进入器件求解

- 第二轮模型于12:25:37 UTC自然结束；12:27:03 UTC在轮次间隙安全重载，旧PID16658退出，新PID22575。未另建执行者，未修改状态根、连接或原任务身份。
- 新release：`<AUTONOMY_INSTALL_DIR>/releases/20261116T122703Z-runtime-failure-fix`。在服务器现有release上仅替换已验证的`runtime.py`及其测试文件，保留现有controller、advisor等其它线程改动。
- 回执：`<SERVER_STATE_DIR>/start-r04-20261116/runtime-fix-reload.json`。runtime SHA256为`091116f0260a15e55e55f9fe05a09113ee1443acc0c88876f3d536e17be2d81a`。
- 重载后observation持续更新；六个原失败输运任务已全部按原ID收集为`FAILED_COLLECTED`，槽位释放并生成修复请求。恢复依赖不等于已经取得修复后的输运结果。
- 新TCAD原run：`auto-r04-l08-p000-electrical-v1-0ab40348a7d84362`，slot0，目录`<SIM_USER_HOME>/research-training/runs/auto-r04-l08-p000-electrical-v1-0ab40348a7d84362`。原日志确认SDE几何及snmesh网格步骤通过；12:28 UTC实际观测到`sdevice` PID30623运行，已进入原生器件求解。
- 此时尚未获得可用的SEU截面、工程错误率或正式训练标签；继续由服务器监督收集、分析真实结果并接续修复，不把进程启动当成科学验收。
- `POST-DATA-WORKFLOW.md`已单独同步服务器，并追加两项已确认决定；没有覆盖服务器正在维护的HANDOFF、matrix或工作队列。

### 2026-11-16 12:32 UTC：启动验证落盘

- 服务active/enabled，实际隔离配置为`magpie / auto/gpt-6.1-sol / high`。第三轮模型已于12:30:45 UTC开始；模型运行期间observation仍于12:31:50 UTC更新，确认监督不再随模型轮次停顿。
- 虚拟机`sdevice` PID30623继续运行，已出现真实的耦合方程收敛步骤和接触电流值；完整DC扫描仍在进行，尚未形成已验收的辐照效应标签。
- 本地证据：工作区`output/server-start-r04-20261116/launch-verification.json`、`runtime-fix-reload.json`及`download-manifest.json`；重载回执与实际runtime SHA一致。
- 本快照为1项TCAD原生任务运行、6项原失败输运待新修复输入；并发上限9不等于此刻已有9项正在计算。后续实时状态以服务器observation及原runner账本为准。


## 2026-11-17 UTC MC2 resource and month-one handoff

本日期块覆盖旧九并发单核与“等待四项自然结束”的执行描述，保留历史记录：

- 用户已授权立即中止原四项；03:10:40 UTC退出143，沿原ID全部FAILED_COLLECTED、归档核验及原槽释放完成。原输入/ELF/日志/归档保留，不把中止计为成功，不重投旧ID。
- `/home`原地在线增加40GiB至约87GiB；虚拟机未重启。底层有界写入池64→71GiB，15份重复归档逐项核验服务器权威归档/receipt/SHA后仅回收虚拟机副本。实际空间核对虚拟机、overlay、服务器三层，不把逻辑df当物理余量。
- 七份原runner的1/2/4任务双核短探针均正常收集和释放；原数值容差与闭合资源分析通过。四并发每项427.52–430.32秒、CPU/wall1.819–1.824，fresh PSS峰8.33GiB；guest可用最低17.8GiB、host最低1.44GiB，swap I/O与服务器VM cgroup OOM增量0。guest独立OOM未采，保持未知。证据在local_runtime/server-codex/operations/20261117T040500Z-mc2-benchmark/，服务器原操作目录local_runtime/mc2-benchmark-20261117/。
- 当前TCAD为mc2-four/r4，最多4项各2数值线程/核心，CPU集0–1/2–3/4–5/6–7，CPU8余量；QEMU仍限host0–8，host9–11留管理。旧3/7/9单核profile和原池/gate/锁/owner/收集租约保留。Geant4用policy/readiness明确固定的原nine单核profile，仅全部核验收集释放后的空闲池轮换，两类全局最多4任务。
- 原控制器已于05:05:26 UTC恢复，release为20261117T045000Z-mc2-four，policy/readiness上限4，auto/gpt-6.1-sol/high路由保留。启动时会首次读取旧归档建立哈希缓存；不因暂未更新observation重启进程并丢失缓存。真实运行以新时间戳observation和原生进程/日志为准，不能用service active或旧03:06维护前快照代替。
- 原四项的继续输入为新mc2-r2目录/ID及repair_of，已加入原队列，由Runtime独占提交。PMI只改日志回调计数器为atomic/fetch_add relaxed，已通过原SDK编译、导出及依赖检查；新源码SHA6c2360c8b75840561fb61a61dccc8fddde0d4e14061f65cbd1a6f748bdb77b75，新ELF SHAca05ab0350b27777fbce6a7aedea2b0c811bedb8bdee7581433af18804c98f65。只改从未提交的新输入，物理公式、源数据、mesh/deck/判据和旧源码/ELF均保留。真实长瞬态的源积分/关源/时钟/匹配对照/读出及数值一致性仍待原结果，必要匹配控制走原队列，不放宽标准。
- 首月执行范围以BUDGET-REDUCTION-20261117.md为准：6profile，16核心工况384主响应，最多2备用48主响应，另12复用zero；原3072独立补样及主动数值细化延期。短测不增加科研样本，不据此扩大预算或线性外推长任务月产能；保守仍350–420主响应/月。
- month-one-cases-r05.json及CASE-MANIFEST-CONTRACT.md已正式部署，444唯一case、216主响应pair、384/48/12层、16/2工况；全部planned且task/run/baseline/验收映射未绑定。primary_index是计划位置，b0/b1是同源配对；增强、随机、对照、各类留出不混计，connected provenance分组不泄漏。该清单不是新执行账本。历史r04一个基准器件的event4 b0/b1两条有条件未翻转与性能probe独立展示，不填进r0.5分母。
- 网页状态从原queue/runtime/manifest和新observation投影，维护web-observation只按时效使用，自主恢复后回归原observation。线上Codex可按<PUBLIC_SITE_DIR>/ops/PROGRESS-INTERFACE.md正式CLI写私有展示库的issue/action/phase、短说明、下一步和证据；它不修改运行事实或科学验收，不需手改status.json/前端。公开只用正式case_id或BENCH别名，不把真实r04 run_id换前缀公开。
- 既有automation tcad已迁入本会话并恢复每小时ACTIVE，接续最新4×2和预算；复用已确认结果，不重复探针/API/环境验证。当前不启动正式训练、超参搜索或新网页部署。


## 2026-11-17 05:14 UTC actual native restoration receipt

05:12:28 UTC原observation已更新为active/running=4、max_parallel_jobs=4、r4双核、discovery_uncertain=false且无新任务blocked/pending。05:12:49 UTC四个新mc2-r2原生SDevice均在运行，原wrapper PID/start_ticks/boot及父子链已核验，全部实际TID在各自CPU集内；当时两秒CPU采样约100/142/100/147%，并非持续两核满载。05:13:56 UTC四份原生日志均明确assembly/solver threads=2，新atomic PMI实际加载、日志及BE时间步推进。四项为同一基准器件的c00/event7377与c01/event0各b0/b1，科学新增仍0，完整长瞬态性能和验收待完成后更新。

同期空间：guest /home可用56.93GiB，overlay实际余量41.91GiB，host根可用64.61GiB。新增40GiB已落实，guest未重启、host总盘仍170GiB；这些读数不是整月全部原始数据的容量承诺。automation tcad已核验ACTIVE/每小时/当前会话。完整本轮收据见local_runtime/server-codex/operations/20261117T040500Z-mc2-benchmark/FINAL-RECEIPT.json；服务器同名收据在local_runtime/mc2-benchmark-20261117/。
