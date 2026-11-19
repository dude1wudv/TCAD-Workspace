# 服务器Codex执行设计与后续交接

> 2026-11-18 本轮资源测试按用户最新决定执行 5×2 → 10×1，取消 6×1+2×2。服务器已为 14 核，虚拟机 11 核 / 28 GiB。四项 5×2 已成功收集，D1 b1 仍自然运行。一次性衔接服务 `tcad-r06-ten-one.service` 已启动等待，原 `tcad-autonomy.service` 维持维护暂停。最后一项终态后沿原 ID 收集、验签、释放槽位并核对全池空闲，再安装候选 runner，启动两端资源采样及十项匹配性能副本。原控制器正式支持十并发的适配及最终配置选择待比较结果。实时证据在服务器 `local_runtime/r06-compare-20261118/ten-one-events.jsonl`，十项谱系在同目录 `comparison-inputs.json`。当前执行说明见 [服务器流程](../../docs/server-workflow.md)。

2026-11-18 14:18 UTC 分析快照保存在服务器同目录 `analysis-final.json`，本地为 `analysis-subagent.json`。五项重叠期约 4 小时 6 分钟，服务器可用内存 17.96–24.50 GiB，虚拟机可用内存 19.03–23.25 GiB；已覆盖采样内交换读写为 0，内核及计数证据范围见 JSON。四份完成归档的 SHA、35 ns 终点和严格 PLT 解析均已核查。通用 BE/PLT 时间步关联仍有三份待审警告，保留原诊断。0.1 mV 为展示目标，科学判定待审。5×2 尾段采样在 14:02 UTC 恢复，中间缺口保留。十项结束并收集后，衔接程序调用同目录 `summarize-comparison.py` 更新各类耗时比、批次吞吐及指定时刻的电压差，再据此决定正式配置。

> 2026-11-17 r0.6整套计划已获用户执行授权，当前依据为[执行授权与上线约定](EXECUTION-AUTHORIZATION-r06-20261117.md)。原唯一Runtime接续，P0按证据自动放行；不再等待用户逐阶段批准。13个profile/396个槽位，4×2批量，214为统计用途上限而非已合格样本。以下旧r0.5预算、O1拒绝和未授权训练文字仅保留历史，新训练须在开发数据及防泄漏门禁具备后执行。

研究入口：[PLAN.md](PLAN.md)；任务设计：[matrix.yaml](matrix.yaml)。当前研究revision为0.5，`execution_authorized=true`。控制器v2最初以禁用状态部署，原实现证据见[IMPLEMENTATION.md](IMPLEMENTATION.md)；2026-11-16已按用户指令在原工作区启用。2026-11-17 起首月预算按[BUDGET-REDUCTION-20261117.md](BUDGET-REDUCTION-20261117.md)执行。实际唯一调度交接、范围与运行证据见[EXECUTION.md](EXECUTION.md)。旧“尚未启动”措辞是设计阶段记录；模型训练和产品交互的新决定见[POST-DATA-WORKFLOW.md](POST-DATA-WORKFLOW.md)。

## 1. 工程师的目标

优先完成导师四项任务：文献/数据路线、Geant4/TCAD数据集、截面与错误率训练/CV、独立验证与因素分析。DDR5工程数据与LPDDR5器件路线各自推进。网页、接口和自动化服务于产出有效研究结果，不能成为无限扩展的软件项目。

计划是目标和初始方法。理论不符、个别不收敛、资料暂缺，均优先转化为具体下一步，不阻塞整个研究队列。

## 2. 首次启用时只做一次交接

后续获得启动指令后：

1. 从最新服务器工作区入口取得实际路径、原runner、profile和资源容量。
2. 核对原作业ID、目录、进程身份、槽位/租约及唯一调度方；有旧任务时接续原任务，不另投同输入。
3. 将本计划版本、预算/资源范围、当前批次及待收集清单登记到现有交接机制。
   原共享池上限仍为9核/9个独立单核任务；首月实际按有研究价值的任务填槽，当前四项活动任务不改。当前批次排空后，另行验证4并发、每任务2核心的候选 profile；内存或许可不足时降并发，不新建第二个资源池。
4. 对需要重构的旧控制策略做一次映射：保留任务身份/锁/归档，把科学假设判断改为分项研究决策。
5. 仅对新任务采用新策略。旧冻结输入、历史阈值和失败记录不改；不通过改历史标签制造新计划“通过”。

目前服务器软件安装、资源扩容与控制器离线代码的状态分别以各自证据为准。本计划不重复安装环境，也不默认旧控制器已经支持这些行为。

## 3. 日常推进循环

```text
状态变化/新资料/待补任务触发
→ 读取增量摘要与最近决定
→ 先恢复原任务查询和收集
→ 找到依赖就绪且有研究价值的任务
→ 在原共享资源池中提交一次
→ 收集并提取实际结果
→ 更新结果用途、训练快照及下一步
→ 有新问题就修复/实验，无变化就等待
```

轻量监督负责进程状态、终态通知、槽位和超时线索；Codex负责需要推理的建模、故障诊断、取样和解释。长任务正常运行时无需LLM持续盯日志。

任务依赖按具体输入产物判断：文献整理未全部结束也可用已核对结构建模，矩阵未全部完成也可用已获得开发数据训练基线。数据不足的结论暂不发布，不把整个工作包“全部完成”当下游开始的通用门槛。

建议初始策略：终态任务批量收集、队列不足或异常时唤醒；普通状态查询采用退避；15–30分钟无事件复核只能检查是否有新信息，不默认发一次大模型调用。实际间隔按任务耗时调整，不把定时频率当科学进展。

## 4. 避免空转的具体规则

- 已核查模型/源映射/环境以版本和哈希关联检查结果；输入不变时复用。只重验受变更影响的部分。
- 一次诊断要产出可执行修复、新证据或范围调整。相同失败签名连续修复无新信息时，暂缓该工况并处理其他任务，汇总尚缺信息。
- 可先约定同一失败签名两次有理由的修复，之后转为更换方法或独立诊断；这只是控制重复消耗的默认，不限制有新证据的有效修复。
- 不以API心跳、审计次数、空报告或重复冻结文件作为研究产出。
- 高价值新事件和有变化的工况优先；完成目标后停止扩增，不为填满槽位做重复样本。

## 5. 不同问题如何处理

| 问题 | 自主动作 | 影响范围 |
|---|---|---|
| SSH断开/包装程序超时 | 查原run和远端目录，恢复原status/collect | 只恢复原任务，不自动重投 |
| 单点数值不收敛 | 保存日志，调整步长/网格/初始化/求解配置，建立有区别的新尝试 | 相关工况 |
| 内存/许可/磁盘暂不足 | 降并发、等待/收集可释放资源，记录限制 | 资源相关新提交；正常任务继续 |
| 输入单位/坐标/参数不合法 | 修复转换器或该输入，定位受影响结果 | 相关工况/版本 |
| 理论趋势不一致 | 保留观察，检查数值与条件，提出竞争解释及有区分力的小实验 | 不阻塞无关参数点 |
| 文献缺内部参数 | 建代表假设与敏感性分支，标明来源 | 限制产品校准结论 |
| DDR5缺注量/bit-time | 继续原始计数整理、LPDDR5和训练框架，登记需交接字段 | 相应截面/率标签待补 |
| 全部错误标签为同一类 | 保留真实分布，扩大有物理依据的开发采样或改用连续目标 | 分类模型暂不声称有效 |
| 需要改变目标器件、读出含义或最终测试用途 | 提交简短决定请求，继续其他可做任务 | 仅依赖该决定的任务等待 |
| 原任务身份不明或可能覆盖原始数据 | 停止该提交/写入并核对；继续安全独立工作 | 有风险的局部操作 |

## 6. 自主调整与科学记录

网格、时间步、求解策略、顺序、资源退避可以自主调整。结构/工艺在研究范围内的变更作为新模型/工况；近似源作为不同精度层。采用新物理模型或简化时写清理由、适用范围和对比需求，不把探索值回填为论文事实。

读出判据是标签定义，不能为降低失败率静默改动。调整判据有研究价值时新建标签版本和比较结果；原标签保留。试验参数不满足理论趋势不构成删除样本的理由。

主动学习使用开发数据与模型不确定性，不能偷看最终测试标签选点。样本增加可动态安排；真实截面估计保留独立统计抽样及其权重，不能以训练样本的错误频率冒充总体概率。

## 7. 状态和报告

原runner状态原样保存。研究层可以另外记录：

- `progress`：planned / ready / active / waiting_for_input / deferred / complete。
- `use_scope`：raw_only / exploratory / response_model / representative_statistics / engineering_validation。
- `uncertainty`：数值、模型、统计和观测缺口；不能只用一个success字段混合。
- `next_action`：执行什么、为何有价值、依赖什么。

这些字段是研究摘要，引用原run，不复制创建另一个作业账本。

正常运行不逐条发消息。阶段完成、影响目标的异常、需要决定时汇报：新获得的数据/结论、已完成与未完成、当前任务、下一批及成本。没有新信息时不改写一份“再次验证通过”的长报告。

## 8. 结题与停止

各阶段按PLAN中的证据定义完成；最终研究包至少覆盖导师四项任务。外部数据缺失、模型未优于基线、外推失败等如实写入，并提出可执行补救或收缩结论。

整套计划获执行授权后，阶段完成就汇总并自动进入范围内的下一阶段，不要求逐阶段再审批。只有超出授权范围/预算、需要改变科学定义时局部等待；完成整套授权目标后交回成果，不无限增加模型、平台功能或门槛。预算来自此次实际启动交接，不能借用历史“无限预算”自动扩大新计划。

电脑离线能力需要服务器实际完成：计划读取、唯一调度、真实工具调用、断连后收集及恢复验证。本设计文件本身不能证明已具备该能力。


## 9. r0.4的具体研究推进对象

当前采用[FIRST-BATCH-DESIGN.md](FIRST-BATCH-DESIGN.md)和[BUDGET-REDUCTION-20261117.md](BUDGET-REDUCTION-20261117.md)的质子宽能区、多器件几何/掺杂及方向联合设计，[MODEL-AND-TOOLS.md](MODEL-AND-TOOLS.md)的物理约束R/F神经网络与语言工具。撤回旧58 MeV单点预算，不能读取旧样本数直接物化任务。

启动授权后，先在原工作区解析有来源的基准及构型参数，生成版本化 profile、联合工况与预先划分；首月先计入16个核心工况，最多追加2个备用工况。就绪输入即可推进，原9槽只作为共享容量上限，不为占满槽位增加重复任务。缺基准剖面时限制相应模型结论并处理其它工作，不通过重复门禁耗尽API。

开发数据增量触发响应网络训练、折内聚合与宏观网络训练；只用开发结果决定补样和物理项权重。封存的域内组合、高能和Lg外推标签不供自主选参或挑选训练样本。若用户后续决定将已见测试转入训练，记录新版本并另留新测试。

自然语言请求显式选择predict/simulate/auto。predict调用真实权重，simulate沿原runner，auto只在已授权资源和预算内补仿真。未经训练的粒子、p沟道或新结构不能用类别字段伪装成已支持；错误率缺通量时返回已有截面结果与缺项。

首月核心384个、最大432个主响应和12个可复用对照是当前执行预算；原3,072次独立统计起步及数值细化延期。首月结束后由有效标签、失败率和学习曲线决定下一预算修订，不把小探针速度直接当DRAM预算。原任务身份、失败和收集方式保持。


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

## 2026-11-17 r0.6 本地设计决定（未同步服务器）

本地对话与二次对齐已冻结方案 B：13 个 profile（4 锚点 + 6 锚点感知 maximin LHS 开发、1 个长栅长外推 + 2 个逐轴范围内稀疏组合留出）、396 条 planned case（全部 `S/R/HR/HP` 显式绑定 `radiation_id`、`T` 块自适应试探并修正 `b0` 倍率、`AL` 82 条动态未绑定）、保持窗初始 22 ns（`18.2–30 ns` 内）、b1 优先并保留约 25% b0 匹配分层子集。H1/H2 不声明联合凸包内插值。清单、抽样契约、阶段门及下游适配/服务器交接详见 [DESIGN-REVIEW-20261117.md](DESIGN-REVIEW-20261117.md)、[BUDGET-REVISION-r06-20261117.md](BUDGET-REVISION-r06-20261117.md)、[R06-HANDOFF-AND-PREDICTOR-CONTRACT.md](R06-HANDOFF-AND-PREDICTOR-CONTRACT.md)、[month-one-cases-r06.json](month-one-cases-r06.json) 和 [build_r06_case_manifest.py](../../scripts/build_r06_case_manifest.py)。

用户批准 O2（PMI 全局原子计数 + 按 BE 步汇总）和 O3（新保持窗 timing deck 验证），保留 28 GiB 虚拟机设置，未批准 O1。P0 新增双核源前微差（`mc2-b0-zero-pairing-result-r1` `1e-19 A` 拒配对）根因排查及 13 profile `Z` 块全量无粒子写保持读体检；Geant4 采用 G0–G5 加 C0/C1 按几何分波次集中推进并即时压缩防爆盘，C2/C3 封存。本地计划不直接修改服务器队列、当前仍在运行的活动任务（`r04-l08-p000-nodal-whr-b1-zero-mc2-v1`）或运行器。P0 全套结果须由用户审阅后才能放行 P1，server-codex 不应按旧 `15 ns` 时序生成新的 r0.6 事件输入。
