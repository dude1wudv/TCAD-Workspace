# 状态展示数据链路

公开入口为 `https://status.xjtu.shop/`，科研首页为 `https://tcad.xjtu.shop/`。
状态看板每 15 秒获取同源 `/live.json`，手动刷新时立即获取。
服务器的 `xjtu-shop-status.timer` 每 15 秒生成轻量 `/live.json`；
`xjtu-shop-research.timer` 每 60 秒独立生成全量 `/status.json`。
两条路径各自带 `generated_at`，科研摘要由 `research_hash` 对齐。

## 实时仿真与资源采集

`scheduler_observation.py` 通过现有虚拟机连接执行一次只读探针。探针读取进程树
（`comm/cmdline/exe/ppid`）、每核的 0.4 秒 CPU 差分、进程内存和 CPU 绑定、
虚拟机内存与 Swap、虚拟机内文件系统和许可进程心跳。任务优先读取
`<run>/progress.json`（上限 64 KiB）；缺失时自动发现 `transient_des.log`、
最新 `*.log` 或 `*.out`，只读末尾 128 KiB。协议和设备参数按白名单提取。
服务器通过全池 manifest 和 Runtime 意向识别原任务。近期已核验收集的任务也可从原无压缩归档读取日志尾部。

私有快照格式为 `tcad-scheduler-observation-v2`，默认保存到
`<STATUS_STATE_DIR>/scheduler-observation.json`，读取器兼容 v1。
采集失败保留上一份快照。观测超过 180 秒或超前 60 秒时标记过期、冻结时长，
活动核数、活动任务数及许可进程存活态显示未知。封存留出任务和未登记任务仅以
本次观测的匿名编号链接任务与槽位，公开通用状态和 CPU 绑定。近期流水与任务趋势均排除这两类任务。

## 公开 JSON 契约

两路输出各自带 `generated_at`。`/status.json` 保留所有 v2 顶层字段及完整
`research`；`/live.json` 使用聚合的 `research_summary` 和 `research_hash`，
并增加 `history`。快路径只读上一份成功科研缓存，不重扫验收哈希；
慢路径失败时回退 `last-good-research.json` 并标记 `projection_state:"cached_stale"`。

| JSON 路径 | 字段与口径 |
| --- | --- |
| `system.cpu`、`system.memory` | 服务器 CPU 和内存。`memory.available_bytes` 为服务器可用内存 |
| `system.storage.server_root` | `total_bytes/used_bytes/available_bytes/used_percent`。`available_bytes` 为服务器剩余空间，`warning_below_bytes` 为 20 GiB，低于阈值时 `low_space` 为 `true` |
| `system.storage.vm_disk_growth` | 同四个空间字段。`available_bytes` 为服务器上虚拟机磁盘文件可增长空间。独立挂载不可用时各字段为 `null` |
| `simulation.scheduler.virtual_machine` | `observed_at/cpu/memory/swap/storage/daemon_health` |
| `…virtual_machine.cpu` | `cores/usage_percent/load_1m/load_5m/load_15m/per_core_percent`，每核百分比以 `cpu0`、`cpu1` 等为键 |
| `…virtual_machine.memory`、`…virtual_machine.swap` | `total_bytes/used_bytes/available_bytes/used_percent`。内存的 `total_bytes` 与 `available_bytes` 分别为虚拟机分配内存和虚拟机可用内存 |
| `…virtual_machine.storage` | `total_bytes/used_bytes/available_bytes/used_percent`。`total_bytes` 为虚拟机分配空间（逻辑容量），`available_bytes` 为虚拟机剩余空间 |
| `…virtual_machine.daemon_health` | `lmgrd`、`snpslmd` 各含 `alive/elapsed_seconds`，表示进程存活和运行时长 |
| `simulation.scheduler` | 新增 `schema/label_en/layout_widths/active_groups/active_solvers`。`layout_widths` 为每个配置槽位的核数，缺配置时按实际绑定推导。`active_slots` 按绑定核心去重，`active_groups` 按任务目录计数，`active_solvers` 按求解进程计数 |
| `simulation.dispatch_flow` | 可选。取自控制器私有观测的 `scheduler.flow`，沿用该观测的 `utc` 与有效期。两路输出均包含 `schema:"tcad-dispatch-flow-v1"/state/observed_at/fresh_max_age_seconds`，新鲜时附白名单 `slots[{slot,threads,state,reason}]/collection{pending,oldest_wait_seconds}`。`slot` 为槽位序号，每条槽位最多计一个运行任务。过期或结构未知时省略槽位和积压数，旧观测省略整个字段 |
| `…scheduler.slots[]` | 新增 `usage_percent/task_ids`。单一占用者时 `task_id` 和 `cluster` 均为任务 ID，同一多核任务的各核共享 `cluster`。重叠绑定时 `task_id` 为 `null`，`task_ids` 含全部占用者 |
| `…scheduler.tasks[]` | 新增 `case_id/device/stored_bit/batch_label/batch_label_en/finished_at/health/collection_result`，以及任务级 `cpu_percent/rss_bytes/hwm_bytes/threads` 和 `processes[]`。每进程含 `engine/cpu_set/started_at/cpu_percent/rss_bytes/hwm_bytes/threads`，进程 CPU 百分比按单核为 100 |
| `…tasks[].parameters` | v2 白名单为 `node_count/integrator/temperature_K/stored_bit/source_variant`，缺值时可省略 |
| `…tasks[].progress` | `simulation_time_ns/goal_time_ns/stepsize_s/newton_iterations/error/assembly_s/solve_s/step_wall_s/log_updated_at/updated_at/phase/whr/whr_segments/whr_phase`。可采集任务趋势时再增加 `rate_ns_per_hour` |
| `simulation.recent_runs[]` | 最近至多 20 个公开任务。字段为 `id/label/kind/batch_label/batch_label_en/case_id/device/stored_bit/state/health/requested_threads/started_at/finished_at/elapsed_seconds/collection_result/simulation_time_ns/final_time_ns` |
| `simulation.active_batch` | `kind/label/label_en/total/running/collecting/completed/failed/pending/unknown/collected/completed_24h`，以及 `summary_zh/summary_en/pause/daemon_health`。暂停对象含 `active/recorded/reason_zh/reason_en` |
| `health.services` | `state` 与 `items[]`；每项含 `id/kind/state/detail`，许可守护进程另含 `elapsed_seconds`。任务失败只进仿真推进态，不把整站判成离线 |
| `health.freshness` | `state/scheduler_age_seconds/scheduler_threshold_seconds/scheduler_probe_ok/research_age_seconds/research_projection_state` |
| `health.simulation` | `state/active_tasks/stalled_tasks/fine_step_tasks/uncollected_tasks/summary_zh/summary_en`；状态为 `progressing/slow_convergence/stalled/awaiting_collection/paused/idle/unknown` |
| `activity_feed` | `mode(active/idle/stale)/live_items[]/recent_outcomes[]`。当前任务含引擎、阶段、物理时间或通用进度、CPU 集合、日志心跳和结构化诊断原因；近期结果按完成时间倒序 |

三层存储空间分别采样，双层内存也分别采样。未知值以 `null` 表示，各层余量不合计。
磁盘保留块可能使总容量大于已用量与可用量之和。

- 普通任务的 `kind` 为 `benchmark/formal/diagnostic/research`。封存和未关联任务
  分别为 `sealed/unmatched`，仅含 `id/kind/label/state/cpu_set`。
- 任务级 `health` 为 `healthy/fine_step/slow_convergence/stalled/collecting/collection_overdue` 或 `null`。微步表示当前步长
  小于 1 ps 或最近已收敛一步超过 30 秒。停滞表示日志超过 15 分钟未更新，
  且进程 CPU 偏低；直流初始化/网格阶段允许更长的日志静默窗口。连续约 30 分钟
  记录的物理时间零推进也会给出结构化原因。日志打印精度决定可见的时间分辨率。
- `phase` 为 `dc_init/transient/mesh/post` 或 `null`。`whr.write` 含
  `sn2_start_ns/sn1_start_ns`，`whr.hold` 含 `start_ns/end_ns`，`whr.read` 含
  `start_ns/end_ns/sample_ns`。协议边界齐全且递增时生成 `whr_segments[]`
  （`id/start_ns/end_ns`），段 ID 为 `initialization/write_sn2/write_sn1/hold/read/tail`。
  `whr_phase` 为当前物理时间所在段。
- `collection_result` 为 `awaiting_collection/verified_success/verified_failure/verified_interrupted`
  或 `null`。`final_time_ns` 来自原日志或明确记录的终止时钟，缺证据时为空。
  `completed_24h` 统计跨池最近 24 小时已核验成功收集的公开任务。

### `/live.json` 专有字段

```json
{
  "research_summary": {
    "schema_version": 1,
    "available": true,
    "revision": "<plan revision>",
    "projection_state": "fresh",
    "projected_at": "<ISO-8601>",
    "totals": { "planned": 0 },
    "counts": {},
    "blocks": [],
    "budget": {},
    "diagnostics": {},
    "statistics_snapshot_status": "not_connected"
  },
  "research_hash": "<64-character SHA-256>",
  "history": {
    "system_fields": [
      "ts", "server_cpu_percent", "vm_cpu_percent",
      "server_available_memory_gib", "vm_available_memory_gib",
      "server_remaining_gib", "vm_disk_growth_available_gib", "vm_remaining_gib",
      "active_solvers", "active_cores"
    ],
    "system_recent": [],
    "system_5m": [],
    "task_fields": ["ts", "simulation_time_ns", "stepsize_s", "rss_bytes"],
    "tasks": {}
  }
}
```

`research_summary` 可另含 `updated_at/observed_at/observation_stale`，仅复制已有研究字段。
`projected_at` 与 `projection_state:"fresh"` 表示本份科研数据的新鲜度；缓存回退时为
`cached_stale`，无缓存时为 `unavailable`。
`research_hash` 为完整 `research` 对象排序键名后紧凑序列化所得的 SHA-256。
趋势行按对应 `*_fields` 定义解码，`ts` 为 UTC Unix 秒。`system_recent` 是最近两小时
每分钟一条的最多 120 点，`system_5m` 是最近 24 小时每五分钟一条的最多 288 点。
`history.tasks` 按当前公开活跃任务 ID 索引，每任务最多 60 点。
每个时间桶使用最近一条采样。私有历史保留最近两小时原采样（每 10 秒桶至多一条），
推进速率使用最近约 30 分钟连续样本的物理时间差与实耗时间。样本断开或时钟回退时重新起算。

### 配置与写入

- `scheduler_observation.py --pool-root` 或 `TCAD_STATUS_POOL_ROOT` 覆盖运行池根目录。
  `--runtime` 或 `TCAD_STATUS_RUNTIME` 覆盖 Runtime，`--output` 或
  `TCAD_STATUS_SCHEDULER` 覆盖私有快照。`TCAD_STATUS_VM_SSH_CONFIG`、
  `TCAD_STATUS_VM_SSH_ALIAS` 可沿用其他已登记虚拟机连接。
- `status_checker.py --output` 写全量，`--mirror-output` 重复添加全量镜像，
  `--live-output`、可重复的 `--live-mirror-output` 写轻量输出。
  `--mode live|full|both` 控制快/慢路径；`--research-cache` 或
  `TCAD_STATUS_RESEARCH_CACHE` 覆盖最近成功科研缓存，默认
  `<STATUS_STATE_DIR>/last-good-research.json`。
  `--history-path` 或 `TCAD_STATUS_HISTORY` 覆盖私有历史文件，
  默认 `<STATUS_STATE_DIR>/history.json`。文件权限 `0640`，损坏后从新采样恢复。
  `TCAD_STATUS_VM_OVERLAY` 覆盖服务器上虚拟机磁盘文件所在的独立挂载点，
  未设置时自动探测 `/srv/tcad-isolated-vm/*/overlay` 的唯一挂载点。
  `TCAD_STATUS_STATS_SNAPSHOT` 可选接入外部统计资格快照。
- 一次调用构建一份状态，先暂存全部目标，再逐个原子替换。快慢路径分别生成、各自原子替换。
  部分路径替换失败时日志会明确报告，未替换的文件保留上一版。

## 权威来源

| 内容 | 服务器来源 | 写入者 |
| --- | --- | --- |
| 正式逐例计划 | `/home/tcad/course-workspace/plans/dram-se-ddr5-lpddr5/month-one-cases-r06.json` | 科研计划维护者 |
| 科学案例绑定 | `<SERVER_STATE_DIR>/runtime.json` 的 `intents[task_id].scientific_admission.case_id` | 原 Runtime |
| 旧任务绑定 | 计划目录 `work-items.json` 中任务的 `case_id`，仅无科学准入对象时兼容回退 | 原调度流程 |
| task → run 连接 | `<SERVER_STATE_DIR>/runtime.json` 的 `intents[task_id].run_id` | 原控制器 |
| 实际观测 | `<SERVER_STATE_DIR>/observation.json` | 原控制器 |
| 维护期观测 | `<SERVER_STATE_DIR>/web-observation.json` | 维护负责人 |
| 原执行证据 | `/home/tcad/course-workspace/local_runtime/cloud-benchmark/centos79-guest-20261116/runs/*/manifest.json` | 原 runner |
| r0.6 逐例科学验收 | 计划目录下 `r06-gate/results/case-acceptance/<case_id>.json` | 具备实际验收证据的科研维护者 |
| 处理说明 | `<STATUS_STATE_DIR>/progress.sqlite3` | 线上 Codex |

SQLite 只存展示注释；原计划、队列和归档继续维护各自事实。
接口命令见 [PROGRESS-INTERFACE.md](PROGRESS-INTERFACE.md)。
消费路径可通过 `TCAD_STATUS_PLAN`、`TCAD_STATUS_WORK_ITEMS`、
`TCAD_STATUS_OBSERVATION`、`TCAD_STATUS_WEB_OBSERVATION`、
`TCAD_STATUS_RUNTIME`、`TCAD_STATUS_RUNS_ROOT`、`TCAD_STATUS_PROGRESS_DB` 覆盖。

## 自动连接

稳定公开案例 ID 默认采用 r0.6 的 `r06-...` 格式，例如
`r06-z-d0-nominal-b0`、`r06-s-d0-nominal-p00-b1`。
通过 `TCAD_STATUS_PLAN` 显式选择 r0.5 清单后，
继续支持原 `m1-r05-d0-c0-p00-b0` 和 `r05-...` 格式及三分组布局。
新任务从 Runtime 科学准入对象取得 `case_id`，并用同一 intent 的 `run_id`
查原 manifest，不依赖 work-items 是否复制案例 ID。
科学准入对象存在时，其案例绑定优先，缺少案例 ID 也不会采用旧任务标签。
无科学准入记录的旧任务仍支持 work-items、manifest、观测中的
`case_id`，以及计划显式 `run_ids`。
修复任务继续引用原 case_id。重试尝试数增加，计划分母保持不变。
已有 r04 任务与双核性能探针未绑定新清单，单独展示历史与性能记录。
当前开发任务使用 `DEV-P000-C00-E7377-B0` 等稳定公开别名，分别编码
器件序号、工况、事件与存储状态。修复沿用别名，不公开原 run ID。
Codex 对该别名的说明会同时显示在研究动态与对应运行卡片中。

计划与参数只是计划值。器件参数使用 `{value, unit:"1",
representation:"baseline_multiplier"}` 的相对倍率。绝对长度、掺杂浓度
和来源未确定的工作条件保持未知。运行卡支持实际观测附带的白名单参数。
同时只读原 manifest 的服务器 `project_directory`：按 `SHA256SUMS.json`
校验冻结的 `device.cmd`、`provenance.json` 和 `native-event-manifest.json`，
提取明确的温度与存储状态。源能量和方向来自原输运归档中的
`request.json`，按 native manifest 中记录的 SHA-256 核对。
只读取小型普通文件成员，保留未知参数；不解压、不调用虚拟机或仿真运行器。
因此 r04 原输入的 1 MeV 与 r0.5 计划的 5 MeV 会分别展示。

原 manifest 的 `COLLECTED/FAILED_COLLECTED` 且
`collection_verified=true` 才计归档；`COLLECTED`、远端与收集退出码均为 0，
以及非空 `tool_exit_codes` 全部为 0 才计求解完成。
旧 r0.5 科学验收仍需计划维护者明确给出 `accepted=true` 和私有
`acceptance_evidence` JSON 文件路径（绝对或相对计划目录）。
该记录需 `status:"accepted"`、同 `case_id`、同已成功收集的 `run_id`，
以及与原 manifest 一致的 64 位 `input_sha256/results_sha256`。
字段或证据缺失时保留求解完成状态。这表示已记录科学验收，领域证据另行审查。
Codex 的 `resolved` 只改变说明，不能改变求解完成和科学验收。

## r0.6 外部逐例验收协议

r0.6 冻结计划中的 `accepted:false` 和计划 SHA 保持不变。
读取器仅从计划目录下的私有固定位置
`r06-gate/results/case-acceptance/<case_id>.json` 读取验收，不使用计划内
`accepted/acceptance_evidence` 修改或替代该协议。该目录属于 `results`，
不进入 source pack；不得把记录或引用文件发布到静态站点。

每份 JSON 必须包含下列字段：

| 字段 | 必需内容 |
| --- | --- |
| `schema` | `"tcad-r06-case-acceptance-v1"` |
| `status` | `"accepted"` |
| `case_id` | 与文件名及被冻结计划中的案例完全一致 |
| `run_id` | 已绑定该案例的真实 run；P0 排除规则仍有效 |
| `input_sha256` | 直接复制原 native manifest 的完整非空文件名 → SHA-256 map，不汇总成单个字符串；每个值为 64 位十六进制，键和值须完整一致 |
| `results_sha256` | 与该 run 原 manifest 完全一致的 64 位十六进制 SHA-256 |
| `evidence` | 1–16 项，每项为 `{"path": 私有证据文件路径, "sha256": 该文件的64位SHA-256}`；每条引用均须存在、文件不超过 4 MiB 且实际字节哈希匹配 |

只有同案例、同绑定 run、原 manifest 的 run 身份一致，并且已真实成功收集
（`COLLECTED`、`collection_verified:true`、远端/收集/非空工具退出码均为 0），
再加全部输入 map、结果哈希和非空证据引用核验通过，才能增加 `accepted`。
至少需要一份真实证据；空引用、占位哈希、缺输入文件键或错误 run 都不能通过。
验收 record 不超过 1 MiB；证据引用最多 16 条、每条文件不超过 4 MiB。
证据只应指向小型验收报告或冻结读取器输出。原始大归档只通过 manifest
中的 `results_sha256` 绑定，网页每分钟投影不会读取或重新哈希 GB 级 tar。
引用存在及哈希匹配只是证据完整性核验，科学结论仍由维护者按实际标准审查。

证据的相对路径以计划目录为基准，绝对路径只能位于同一科研工作区内
（正常目录结构为 `<workspace>/plans/<plan>/`）；非标准计划目录仅允许自身范围。
路径不得含任何 `..` 分量；记录、引用文件及其上级目录均禁止软链或 Windows
reparse point，只接受普通文件。不读取工作区外的文件，不随链接访问其他位置。

记录或引用文件缺失，以及身份/哈希/字段要求不匹配时，保持工程状态并不给验收数。
超过大小上限、损坏 JSON、重复字段、`NaN`/`Infinity` 等非有限 JSON 常量、
非法编码、非对象记录、非法路径/链接或无法读取的文件会
使本轮投影失败；现有发布流程保留上一份 JSON 并由生成时间提示过期，
不以空结果覆盖。写入者应先完成实际验收和哈希核查，再在私有目录内原子替换记录；
不能为了改变网页数字制造记录、科学数据或复制旧诊断为新正式成果。
本次代码不创建任何实际验收记录；P0 到正式 Z 的复用规则没有放宽。

该协议只授予逐例科学验收计数，不能授予 `statistics_eligible`。
统计资格仍需抽样、源定义、完整分母和权重等齐备的外部快照，本读取器尚未接入。

## r0.6 Z 基线复用协议

完整 WHR 基线如果已经作为 P0 诊断真实完成，可以复用到对应的正式 Z 槽位，
但必须由科研维护者在私有目录原子保存独立绑定：
`r06-gate/results/z-baseline-reuse/<case_id>.json`。这条绑定只解决
“哪个完整 P0 结果对应哪个 Z 槽位”的身份问题，不把普通 P0 诊断自动变成正式结果，
也不增加 396 分母或统计资格。

记录至少包含：

```json
{
  "schema": "tcad-r06-z-baseline-reuse-v1",
  "status": "validated",
  "case_id": "r06-z-...",
  "run_id": "真实 P0 run",
  "recipe_id": "zero_whr",
  "profile_id": "与冻结 Z case 相同",
  "stored_bit": 0,
  "plan_sha256": "冻结 r0.6 清单 SHA-256",
  "run_kind": "full_whr_baseline",
  "is_prefix": false,
  "timing_contract": {
    "deck_timing_version": "r06-hold-window-v1",
    "hold_window_ns": [18.2, 30.0],
    "timing_sha256": "实际时序证据 SHA-256"
  },
  "profile_qualification": {
    "status": "passed",
    "profile_id": "与冻结 Z case 相同",
    "qualified_bits": [0, 1]
  },
  "input_sha256": {"原 manifest 文件": "64 位 SHA-256"},
  "results_sha256": "原 manifest 结果归档 SHA-256",
  "evidence": [{"path": "小型私有验收证据", "sha256": "64 位 SHA-256"}]
}
```

读取器还要求 `run_id` 确实属于 Runtime 的 `scope=p0_diagnostic`，
原 manifest 已真实 `COLLECTED` 且求解、收集和工具退出码均为 0；所有输入 map、
结果哈希、时序版本、profile/bit、完整 WHR 标记和证据文件都必须匹配。
同一个 P0 run 不能复用给两个 Z case。`run_kind` 为短 prefix、日志探针、旧 r04
原型或任何不完整结果时拒绝映射；只改 JSON 字段而没有对应科学证据不能通过。
映射通过后，Z 仍需自己的 r0.6 逐例验收记录才能增加 `accepted`，统计资格仍保持独立。

网站不会公开上述记录、run ID、路径、输入 map 或证据正文；也不会读取或重新哈希
原始大归档。该协议不修改冻结 manifest、P0 admission、原始 run 或 gate 门禁。

## r0.6 公开 payload

外层 `schema_version:2` 与 `research.schema_version:1` 保持兼容，
r0.6 用 `research.revision:"r0.6"` 及下列扩展字段表示：

| 字段 | 精确含义 |
| --- | --- |
| `research.totals` | 全部正式槽位的 `planned/archived/solved/accepted/running/failed/remaining`；`planned=396`，`remaining=planned-accepted` |
| `research.counts` | 同样七个计数字段，键按 `Z/T/S/R/HR/HP/AL`，`planned` 分别为 `26/68/150/12/28/30/82` |
| `research.budget` | `total_cases:396`、`zero_cases:26`、`profile_count:13`、`radiation_count:10`、`statistics_intent_cases:214`、兼容静态字段 `statistics_eligible_cases:0`；新增 `manifest_eligible_cases` 为冻结清单中资格标志为 true 的数量，当前为 0 |
| `research.blocks[]` | `id/sealed` 与七个计数字段；HR/HP 为 `sealed:true`，只公开此类安全汇总 |
| `research.diagnostics.P0` | `planned/archived/solved/running/failed` 为 Runtime 中 `scope=p0_diagnostic` 的尝试计数，`count_basis:"runtime_intents"`、`included_in_formal_plan:false`；无科学通过字段 |
| `research.cases[]` | 只含 Z/T/S/R/AL 的 338 个公开条目；字段为 `case_id/block/cohort/kind/profile_id/radiation_id/condition_id/stored_bit/primary_index/pair_id/state/attempts/statistics_intent/statistics_eligible` |
| `research.profiles[]` | 13 个计划器件，字段 `id/sealed/parameters`；3 个留出器件只保留 ID 与空参数 |
| `research.radiations[]` | 10 个计划辐照条件，字段 `id/sealed/parameters`；2 个留出辐照条件只保留 ID 与空参数 |
| `research.conditions` | r0.6 无旧版复合工况列表，返回 `[]` |
| `research.progress` | 过滤 HR/HP 与关联 DEV 别名后的公开注释，字段沿用 SQLite 公共接口 |
| `research.acceptance_basis` | `"original_collection_and_scientific_evidence"` |
| `research.statistics_basis` | `"external_qualified_snapshot_required"` |
| `research.statistics_snapshot_status` | `"not_connected"`；尚未消费动态统计资格快照 |

公共 `state` 仅为 `pending/running/failed/solved/accepted`，
`kind` 为 `control/response`，r0.6 的 `cohort` 与 `block` 相同，
`condition_id` 为空；空 profile/radiation 表示 AL 尚未物化或 Z 无粒子。
参数同时兼容旧版 `unit:"1", representation:"baseline_multiplier"`
和 r0.6 的 `unit:"baseline_multiplier"`；五个相对参数投影为 `*_relative`，
明确使用 `nm` 的结深投影为 `Hjc_nm`，不推算未知绝对掺杂和长度。

P0 诊断始终独立，不用来填 396 的完成数。Z 是 396 中的正式基线，
仅在明确映射到正式 case 后计工程状态，科学通过仍需原验收证据。
当前仅 P0 入队且未绑定正式案例时，所有正式完成和通过计数保持 0。
214 是统计用途槽位上限，既不是已合格数，也不是正式计划分母；
当前只读计划不能授予统计资格，兼容字段 `statistics_eligible_cases` 和公开案例的
`statistics_eligible` 保持 `0/false`，不能解释为实时计算的统计合格数。
网页明确显示“统计资格快照待接入”“清单资格标记 0”，同时保留 214 用途上限。
实际统计资格须由抽样记录、源、
完整分母、权重与科学验收齐备的外部数据快照授予；本读取器尚未接入该快照。

HR/HP 的明细、标签、阈值、选择记录与注释全部封存。
运行卡和最近动态也过滤留出案例及带冻结模型关联的封存输运池，
避免从研究区块之外泄露。封存规则不因工程完成或计划中的标志自动解除。

## 新鲜度与隐私

两种观测选择 UTC 时间较新者；维护观测可声明 30–180 秒的
`fresh_max_age_seconds`，默认 180 秒。过期运行显示快照，
时长冻结在观测时间；正式计划当前运行数仅从新鲜观测计算。
控制器主动停止且来源声明 `controller_mode:"maintenance"` 时标注维护。
若控制器服务停止但 `<SERVER_STATE_DIR>/pause.json` 含非空暂停原因，公开投影同样标注维护；没有暂停证据的停止仍标注不可用。
控制器恢复并产生新观测后自动使用新观测。
`capacity` 和 `requested_threads` 来自实际观测，缺失显示未知。

公开 JSON 的 `schema_version:2` 增加 `research`；
`research.schema_version:1` 包含 `counts/profiles/conditions/cases/progress`，
r0.6 的扩展字段与准确计数见上表。
原首页继续兼容原有服务状态字段。公网只投影安全 ID、白名单数值、
预定义状态、处理短说明、UTC 时间和证据是否关联。
内部 task/run ID、路径、PID、命令、原始输出、输入哈希、许可与证据正文保持私有。

源 JSON 损坏或 SQLite 无法读取时，本轮发布失败并保留上一份完整 JSON。
页面根据生成时间和观测时间提示过期；网络失败保留画面并提示过期。
所有说明按纯文本呈现。写入采用 fsync、0644 和同目录原子 replace。

## 发布

Windows 构建并核验后提交 `dist/`；将完整 SHA 的 Git bundle 上传至
`/tmp/xjtu-shop-web-<SHA前8位>.bundle`，使用 `ops/deploy-bundle.sh <完整SHA>`。
脚本保留前版资源 URL、恢复 SELinux 文件标签、运行 Python 测试、
校验现有 Caddy 配置，仅运行网页投影服务。正式计划须先由科研维护者部署。
不启动或重启调度器、虚拟机和仿真任务。回退时保留私有 SQLite 和研究账本。

部署负责人须更新 `ops/deploy-bundle.sh` 的验收断言：
旧版 `core:384/reserve:48/control:12` 和 `len(cases)==444` 不适用于 r0.6。
应核对上述七块计数、`totals.planned==396`、`len(cases)==338`、
13 个器件、10 个辐照条件以及 HR/HP 明细和敏感数据均未公开。
本次适配不修改该部署脚本，也不提交或上线。
