# r0.6 P0 收尾与 D0–D3 第一波 admission 准备

初始证据快照：2026-11-20 02:04 UTC；交接前更新见本文最后一节。  
对应本机日期：2026-11-19  
执行原则：沿用 `tcad-autonomy.service` 的原 Runtime；本文件是准备与审计清单，不是新的队列、运行账本或科学通过记录。

## 当前判断

P0 还没有形成可供 production admission 引用的
`tcad-r06-p0-scientific-gate-v1` 文件。线上原 Runtime 在
2026-11-20 02:04 UTC 仍处于运行态，观察到 4 项在途、4 项排队、
8 个修复请求，`scientific_acceptance=not_assessed`，本轮新增正式提案为
0，统计合格为 0。

因此当前动作是把证据、输入和 admission 骨架准备齐，并让线上 bot
继续收尾 P0。P0 gate 的四项共同证据和目标 profile 资格真实满足后，原
Runtime 按 r0.6 授权自动进入 P1；其余 profile 的局部问题只暂停相应分支。
不需要重新询问用户，也不在本地另建提交器。

## 一、P0 收尾清单

状态词的含义：

- `已收集`：原任务归档和收集链路已有证据。
- `部分证据`：有局部结果，但还不能写入 gate 的 `status=passed`。
- `待验收`：需要线上 bot 继续提取或比较。
- `阻塞`：缺口会阻止依赖它的正式 admission。

| 项目 | 需要形成的正式证据 | 当前状态 | 当前证据和责任方 | 放行条件 |
|---|---|---|---|---|
| P0-1 数值重复性 | 短诊断、代表性长任务、源前/读出段比较、误差上界和粗细步敏感性；保留实际输入与日志 SHA | 部分证据，待验收 | 最新 checkpoint 记载源前严格电流仍有 471 项超限；读出误差上界和步长敏感性未完成。责任方：线上 bot + 原 Runtime | `numerics.status=passed` 且 evidence 完整、可复核 |
| P0-2 PMI 日志链 | 新 PMI 原生日志、计数上限/丢失检查、短/长配对和代表性任务的日志行序 | 部分证据，待验收 | `r06-p0-o2-cmi-build-r1` 已收集成功；prefix/short 任务已有局部归档，但没有共同 gate 记录。责任方：线上 bot | `logging.status=passed`，引用的新 PMI、短/长日志均可验签 |
| P0-3 时序和保持窗 | b0/b1 的写入、保持、31.9 ns 读出、附近时刻敏感性、固定 `deck_timing_version` | 候选，未冻结 | 旧 D0 包是 r04 prototype/旧 PMI/旧时序；新 D0 写 0 只覆盖一个事件和一档步长；D0 写 1 在途；22 ns 仍是候选 | `timing.status=passed`，并明确冻结 `source_time_ns`。当前清单中的 22 ns 只有在证据满足后才能成为正式值 |
| P0-4 源积分 | 非零源的有限相对误差、源数据/公式/时间窗/网格绑定 | 阻塞 | 旧零源分析的 `relative_error=null`，只能说明零源；不能替代新 PMI 非零源积分 | `source_integral.status=passed` 且 `0 <= relative_error < 1e-9` |
| 13 profile 的 Z 体检 | 每个 profile 的 b0/b1 写入、保持、读出、数值收敛；证据绑定到 r0.6 deck/mesh/PMI/timing | 未完成 | D0–D3 有部分 zero 任务；H0 两状态在途；LHS05 有失败修复请求；其余已收集结果仍需科学验收 | `profiles[profile].status=passed`，`qualified_bits` 恰为 `[0,1]` |
| P0 gate 封装 | `manifest_sha256`、四项共同证据、`p1_authorized=true`、各 profile 资格 | 未生成 | gate 文件应放在 r06 gate 约定的证据目录中，由执行方按证据生成；目标 profile 按本身资格判断 | production admission 能通过 `r06_gate.verify` |

必须保留的工程事实：

- P0 诊断单独计成本、失败和来源，不计入 396 条正式计划，也不给统计资格。
- `COLLECTED`、退出码 0 和 service active 只代表工程状态；正式 gate 仍要读科学证据。
- 已失败、未收集、启动未知和数值未决的任务继续保留原 ID、原日志和 repair lineage。
- P0 不能使用旧 r04 的 15.003 ns 写入期标签替代 r0.6 保持期标签。
- 交接前原 intents 已使用 45/64 个 P0 诊断额度，余 19；其中粒子类
  recipe 使用 2/12。优先复用已收集证据和匹配基线，后续诊断按原预算
  逐项安排，保留 contract 原上限。

### P0 gate 最小检查

线上 bot 封装 gate 前按下面顺序复核：

1. 读取当前 `contract.json`、授权文件和 `month-one-cases-r06.json`，确认 SHA
   没有漂移。
2. 确认四项共同证据的 `status=passed`，每项 `evidence` 非空且每个引用的
   文件 SHA 一致。
3. 确认源积分相对误差是有限非负数并严格小于 `1e-9`。
4. 确认 `deck_timing_version=r06-hold-window-v1`，并将真实冻结的
   `source_time_ns` 写入 gate；候选值不能直接当成冻结值。
5. 按 profile 记录 `qualified_bits={0,1}`，持续补齐全计划 26 条 Z 体检。
   正式提交时检查目标 profile，独立 profile 的失败按原授权局部暂停。
6. 四项共同证据和本次目标 profile 资格满足后记录放行，由原 Runtime
   消化该分支 production proposal。全量 P0 收尾与分支可提交状态分别记录。

对应实现约束见：

- `plans/dram-se-ddr5-lpddr5/r06-gate/contract.json`
- `automation/server-codex/r06_gate.py`
- `plans/dram-se-ddr5-lpddr5/r06-gate/README.md`

## 二、D0–D3 第一波正式范围

### 推荐范围

第一波只覆盖 4 个开发锚点：

| profile | 结构变化 | CRN 组 |
|---|---|---|
| `D0-nominal` | 基准 | `crn-geometry-source-d0-d3` |
| `D1-short-channel` | `Lg=0.8×` | `crn-independent-d1-short-channel` |
| `D2-narrow-fin` | `Wfin=0.8×` | `crn-independent-d2-narrow-fin` |
| `D3-low-acceptor` | `NA=0.5×` | `crn-geometry-source-d0-d3` |

准备清单覆盖开发侧 `T/S/R`，共 104 个响应槽位；它们分批 admission，
不作为一次性全量提交：

- `T`：4 个 profile × 8 条 = **32 条**，用于两个参考事件形状和 3/10/30
  初始缩放档位及已规划的 b0 对照。
- `R`：4 个 profile × 3 条 = **12 条**，覆盖 8 个开发辐照池中的轮转位置。
- `S`：4 个 profile × 15 条 = **60 条**，保留每个 profile 的 12 条 b1
  和 3 条匹配 b0。
- 开发锚点响应准备范围合计 **104 条正式 case**。

全部 `T/S/R` 需要的输运准备范围为 24 个去重后的 Geant4 池：

- 3 个 CRN 组 × 8 个开发辐照池（`G0–G5`、`C0`、`C1`）= **24 池**。
- 初始 `primary_count=100000`。
- 必须固定正的 `source_area_cm2`、整数 `seed`、均匀源面积采样并保留
  zero-deposition primary。
- 只有出现可审计的统计缺口，才另建 `1000000` 请求并附 `expansion_need`
  的 passed 证据。

Z 的 8 个 D0–D3 b0/b1 对照是 P0 到正式计划的桥接项。已有 P0 zero 结果
需要通过明确的 `z-baseline-reuse` 记录绑定 profile、stored bit、完整输入
SHA、结果 SHA、timing SHA 和验收证据；不能仅因 P0 任务收集成功就把它们
直接改成正式 accepted。

### 推荐提交顺序

1. 四项共同 gate 和对应 profile 双状态资格通过后，先处理该 profile 的
   Z 复用绑定；已有完全匹配且通过科学验收的基线直接复用。
2. 优先准备 `G0/C1` 参考模板所需池：3 个 CRN 组 × 2 个辐照条件，合计
   6 池候选，分波按实时空间和资源 admission。其余 18 池按后续 S/R 需求
   准备；已有完整匹配的合格输运池可复用。
3. 固定真实参考事件及 source 输入，先接纳每个已合格 profile 的
   shape-a/shape-b 首个 b1 探针（最多 8 条）。实际倍率和执行 ID 在提交前
   冻结，之后依据反馈准备余下 T 槽位；32 条 T 是阶段上限。
4. 在完整 frame、选择概率和匹配 b0 记录冻结后，准备 `R` 和 `S`。
5. 每个 case 单独绑定输入目录、`case_id`、profile、radiation、stored bit、
   block 和事件；修复只能沿同一 case 的显式 repair lineage 继续。
6. `HR/HP` 继续封存；`LHS01–06` 和 `AL` 放到后续阶段，不能因 D0–D3
   的首轮结果提前解封。

## 三、正式 production admission 预检

### 每个 response case 的共同字段

使用 `tcad-r06-production-admission-v1`，至少准备：

- `plan_id=dram-se-ddr5-lpddr5`
- `revision=r0.6`
- `owner=server-codex`
- `task_id`、`backend=tcad`、独立 `project`
- `created_at`
- `input_sha256`：提交时项目目录内每个真实文件的完整 SHA 映射
- `manifest_sha256=ab1b6a44b5d965e249695b32b504248428c35aa0262a405a6e5b0f5232a930c6`
- `p0_gate`：当前 contract 绑定的 gate 引用
- `scope=development_production`
- `case_id/profile_id/radiation_id/stored_bit/block`

输入项目在生成 admission 前必须具备可追溯的：

- r0.6 profile 参数和几何/网格基线；
- `deck_timing_version` 与冻结 `source_time_ns`；
- 新 PMI/编译物和其依赖；
- response source 或 zero source 的明确物化状态；
- transport frame、事件来源、事件 ID、seed 和输入哈希；
- port/branch current、charge balance、读出波形和原始结果的观察计划。

### T 额外检查

- `source_shape_id`、实际 `scale_factor`、参考 radiation 和事件 ID 先冻结。
- 3/10/30 只是候选档位；每次实际提交的倍率、事件、波形和 input hash
  形成独立记录。
- b0 对照沿用计划指定的 matched 规则，不把增强事件当自然发生统计样本。
- 每个 profile 使用自己的真实参考事件来源，不能用两个全局模板替代十个
  profile 的 provenance。

### S/R 额外检查

- 先冻结完整 primary frame：`N_primary`、zero-deposition 数、source area、
  seed、geometry hash、候选池 SHA 和全部事件列表。
- `R` 使用 `simple_random`，materialize `n/N_primary`。
- `S` 使用预声明的粗层分层抽样，每个非空层配额为正，materialize
  `q_h/N_h`。
- b0 必须从同 cell 已抽出的 b1 中随机匹配，保存 `rho0` 和总纳入概率。
- 生成 `tcad-r06-cell-case-binding-v1` 的 `case_draw_map`，覆盖 cell 内全部
  planned statistics-intent case；每个 `(event_id, stored_bit)` 唯一，匹配 pair
  使用同一个 event。
- selection、frame、case_draw_map 的 SHA 在第一个 case 提交前冻结；同一 cell
  的后续 repair 必须沿用相同 selection binding。

### 可提交判定

只有以下条件同时满足，case 才能从 `prepared` 变成 `submit-ready`：

1. P0 gate 的 `p1_authorized=true` 且目标 profile `qualified_bits={0,1}`。
2. response 输入目录完整、无 symlink、所有文件 SHA 已记录。
3. `case_id` 与 profile/radiation/stored bit/block 完全匹配冻结 manifest。
4. `deck_timing_version` 和冻结 source time 与 gate 一致。
5. T 的事件/倍率/波形已冻结，或 S/R 的 frame、selection、case_draw_map
   已冻结并通过 `scripts/r06_sampling.py`。
6. 现有 case 没有提交 intent；若是修复，父 intent、case 科研对象和事件/
   sampling binding 完全一致。
7. 由原 Runtime 生成唯一 run identity、记录 admission SHA、执行后完成
   observation、manifest、collection 和 slot release 对账。

尚未满足上述条件时，预检状态写 `pending` 或 `blocked`，不写
`submit-ready`，不创建 production admission 文件，不占用正式队列。

## 四、status 公网页面衔接

当前线上检查（2026-11-20 02:04 UTC 附近）：

- `https://status.xjtu.shop/` 返回 200，静态页面加载 `status.json/live.json`。
- 研究投影为 `r0.6`、`396 planned`、`0 solved`、`0 accepted`、`396 remaining`，
  `projection_state=fresh`。
- 页面已公开显示 D0–D3 四个 profile 及其参数；Z/T/S/R/HR/HP/AL 区块存在，
 其中 HR/HP 仍标记 sealed。
- P0 单独显示为诊断区块，不并入正式 396 计数；当前线上快照显示 P0
  `planned=45`、`archived=36`、`solved=33`、`running=3`、`failed=4`。
- `https://tcad.xjtu.shop/status/` 返回 404；公开状态入口继续使用独立的
  `status.xjtu.shop`。

第一波 production intent 出现后，页面现有投影可以沿用以下字段显示 D0–D3：
`case_id`、`block`、`profile_id`、`radiation_id`、`stored_bit`、
`statistics_intent`、工程 state 和 attempts。D0–D3 的 `r06-*` case ID
满足公开 ID 规则；P0 admission 沿现有规则隐藏在诊断计数中。

需要持续验收三件事：

1. 第一条真实 D0–D3 production intent 出现后，正式区块从全 pending 变为
   对应 case 的 running/archived/solved 状态，P0 诊断计数仍独立。
2. 收集完成但没有科学 acceptance evidence 时，页面只显示工程状态，不能
   增加 accepted。
3. S/R 的统计快照未连接前，页面保持统计资格为 0，不因 case 已提交或
   solver exit 0 自动增加统计资格。

本地页面源码和状态检查已覆盖这些字段；新增 production admission 后只需
复查真实投影和线上 `live.json`，不需要为 D0–D3 另建页面或另建计数器。

## 五、线上 bot 交接点

原 Runtime 当前已满足继续运行所需的工程条件：服务 active，唯一调度者仍是
`tcad-autonomy.service`，观察显示 `blocked_tasks=[]`、`needs_planning=true`、
`queue_complete=false`。最新 checkpoint 的下一步是继续验签收集、提取 D0 写 1
保持/31.9 ns 读出、定位 D1 CNorm 拒步，并单独验收 H0。

线上 bot 后续动作按下面的顺序自然衔接：

1. 先完成 P0 证据提取和 gate 复核；
2. gate 通过后物化 transport frame 和 D0–D3 第一波 inputs；
3. 只通过原 Runtime 发布 admission；
4. 发布后回读 case/run lineage、collection、slot release 和 status 投影；
5. 任何证据缺失保持 pending/unknown，独立分支继续推进。

本地清单不改变线上队列或已有运行身份。交接时只发布准备文件和原
`PLAN.md` 的导航追加段，由原控制器监测到计划变更并交给线上 bot。

可供后续 bot 或人工预检读取的机器清单见：
`plans/dram-se-ddr5-lpddr5/r06-gate/d0-d3-first-wave-preflight.json`。
该文件只列出 104 个 D0–D3 `T/S/R` case、8 个 Z 桥接槽位和 24 个输运池，
首轮池优先 G0/C1 的 6 个候选。所有条目初始为 `pending_p0_gate`，
不包含 production admission，也不代表已经入队。这里记录本次准备时
观察到的缺口；线上 bot 按当前真实证据更新自己的准备结果。

## 交接前状态更新

2026-11-20 02:21 UTC 的原 observation 为 3 项运行、4 项排队，
`blocked_tasks=[]`、`discovery_uncertain=false`。原 bot 02:19 UTC 完成的
checkpoint 报告 D0 写 1 已验签收集并释放，三路生成率均为零，
到达 35 ns，31.9 ns 的 SN1 方向化读出裕量为 +26.214 mV。
两态波形支持保留 22 ns 为候选；471 项源前严格电流超限、
共同数值验收和正式时序冻结仍待完成。依据：
`experiments/dram-se-r06/p0-d0-hold22-b1-zero-r1/b1-h2-extraction.json`。
该段是原 checkpoint 报告的状态摘要，完整波形及 gate 验收由线上 bot 负责。
交接前核对的两份服务器原产物：

| 证据 | SHA256 |
|---|---|
| `experiments/dram-se-r06/p0-hold22-native-reader-r2/readout-charge-balance.json` | `e4c876dbfdcc72bc8099fec5480df5fd5113603d9b6ff88c93cacfe6d037d8da` |
| `experiments/dram-se-r06/p0-d0-hold22-b1-zero-r1/b1-h2-extraction.json` | `bb6065d5aea6bb664f132695e1c26649f93ada839a4c7ac7c7135db0105d562f` |

后者完整缓存约 10.6 MB，留在服务器原位。公开状态验收引用应使用符合
状态页大小限制的小型证据摘要，并绑定其对应的原始缓存身份。

## 关联文件

- `plans/dram-se-ddr5-lpddr5/month-one-cases-r06.json`
- `plans/dram-se-ddr5-lpddr5/BUDGET-REVISION-r06-20261117.md`
- `plans/dram-se-ddr5-lpddr5/EXECUTION-AUTHORIZATION-r06-20261117.md`
- `plans/dram-se-ddr5-lpddr5/r06-gate/contract.json`
- `plans/dram-se-ddr5-lpddr5/r06-gate/README.md`
- `automation/server-codex/r06_gate.py`
- `scripts/build_r06_case_manifest.py`
- `xjtu-shop-site/status-checker/research_projection.py`
