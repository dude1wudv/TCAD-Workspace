# Codex 展示进展接口

此 SQLite 库只保存公开展示注释。任务运行、收集、求解结果与科学验收仍来自原账本及证据。注释通过 `case_id` 关联正式清单或基准测试，不能改变这些事实或统计分母。

首月私有 case 索引及波次诊断见[操作手册](../../tcad-research-training/automation/server-codex/MONTH-ONE.md)；不复制其原始字段到公开页面。

## 生产命令

运行环境为 Python 3.9 及以上，仅使用标准库。默认库为 `<STATUS_STATE_DIR>/progress.sqlite3`。初始化创建目录 `0750`、库 `0640`；生产应由有权更新进展的 Codex 身份持有该目录，状态投影进程通过同组权限读取。该目录必须独立于网站静态根目录。

以下命令供部署负责人配置完成后执行。此次模块实现不安装服务或修改现有服务账号。

```sh
python3 <PUBLIC_SITE_DIR>/status-checker/progress_store.py init

python3 <PUBLIC_SITE_DIR>/status-checker/progress_store.py set \
  --case BENCH-mc2-four-task-01 \
  --issue newton_nonconvergence \
  --action investigating \
  --phase device \
  --note '牛顿不收敛' \
  --next-step '检查迭代残差'

python3 <PUBLIC_SITE_DIR>/status-checker/progress_store.py set \
  --case BENCH-mc2-four-task-01 \
  --issue newton_nonconvergence \
  --action retesting \
  --phase device \
  --note '求解策略已调整' \
  --next-step '核对原任务复验记录' \
  --evidence 'audit:mc2-four-task-fix-01'

python3 <PUBLIC_SITE_DIR>/status-checker/progress_store.py set \
  --case BENCH-mc2-four-task-01 \
  --issue newton_nonconvergence \
  --action resolved \
  --phase device \
  --note '本次问题处理结束' \
  --next-step '继续观察后续任务' \
  --evidence 'audit:mc2-four-task-review-01'

python3 <PUBLIC_SITE_DIR>/status-checker/progress_store.py list
python3 <PUBLIC_SITE_DIR>/status-checker/progress_store.py clear \
  --case BENCH-mc2-four-task-01
```

示例 ID 只用于说明；真实使用须从正式清单或基准测试映射取得公开 ID。
正式清单默认采用 r0.6 的 `r06-z-d0-nominal-b0`、
`r06-s-d0-nominal-p00-b1` 等 `r06-...` 安全 ID；
同时保留 r0.5 的 `m1-r05-d0-c0-p00-b0` 和 `r05-...` 兼容格式；
`BENCH-...` 对应测试。当前开发任务采用网页给出的 `DEV-P000-C00-E7377-B0`
等稳定别名，按器件、工况、事件与存储状态生成，重试沿用。
投影展示正式清单中的 case_id、观测记录中存在的 DEV 别名，
以及测试命名空间的公开记录。HR/HP 案例允许在私有 SQLite
登记处理说明，但公开投影始终过滤其逐例注释和关联的 DEV 别名，
网页只显示安全区块汇总。留出响应和阈值不得用于开发或展示未解封结果。
不得将旧 r04 真实 run ID 换个前缀发布。

`--db PATH` 和 `--timeout SECONDS` 可放在子命令之前或之后。超时默认 10 秒，可选范围为大于 0 且不超过 60 秒。成功输出 UTF-8 JSON，退出码 0；输入、锁超时、数据库或文件系统错误退出码 2。SQLite 失败信息不回显证据、路径或原始输入。

`init` 可重复执行；`set` 和 `clear` 要求库已经初始化。缺失数据库的 `list` 返回 `[]`，不会创建文件。`clear` 删除当前注释、保留历史；重复清理不存在的 ID 返回 `{"cleared": false}`。

## 字段契约

SQLite `user_version=1`。所有时间由模块产生，使用 UTC ISO 8601 格式及 `Z` 后缀；不接受操作人员传入时间或任务成功状态。

| 字段 | 接受内容 |
| --- | --- |
| `case_id` | `r06-`、`m1-r05-`、`r05-`、`DEV-` 或 `BENCH-` 前缀，后接 ASCII 字母数字和分隔连字符，最长 96 字符 |
| `issue` | `newton_nonconvergence`、`mesh_quality`、`license_wait`、`resource_pressure`、`input_validation`、`solver_failure`、`none` |
| `action` | `investigating`、`fixing`、`prepared`、`retesting`、`monitoring`、`resolved` |
| `phase` | `preparing`、`transport`、`device`、`analysis`、`validation` |
| `note` | 最长 180 字符的公开短说明，可留空 |
| `next_step` | 最长 180 字符的公开下一步，可留空 |
| `evidence` | 最长 512 字符的私有证据引用；`resolved` 时必填 |

公开文本禁止路径、IP、URL、HTML、常见运维命令、凭据模式、控制字符和不可见格式字符；检查涵盖全角兼容字符。拒绝输入时整次操作失败，不擅自修改文意。`accepted`、`succeeded`、求解成功、验收通过等声明也会被拒绝。公开说明应写处理动作，例如“检查迭代残差”“调整求解策略”“核对复验记录”。

私有 `evidence` 支持 `audit:...` 等稳定引用或内部证据文件路径，不允许凭据、URL、IP、HTML及控制字符。它不验证文件存在或证据结论；`evidence_recorded` 只表示填写了引用。实际任务成功和验收结论仍须独立验证。

写入 `progress` 当前行与追加 `history` 在一个 `BEGIN IMMEDIATE` 事务内完成。失败整笔回滚，多个 CLI 写入者按 SQLite 锁串行执行。历史记录保存 `set` 或 `clear` 操作及对应完整快照；触发器阻止普通 SQL 对历史执行 UPDATE 或 DELETE。拥有库文件写权限的管理员仍可改变结构，这不是防篡改审计系统。

## 只读投影

供主代理的状态检查器导入：

```python
from progress_store import load_public_progress

progress = load_public_progress("<STATUS_STATE_DIR>/progress.sqlite3")
```

返回值按 `case_id` 排序：

```json
[
  {
    "case_id": "BENCH-mc2-four-task-01",
    "issue": "newton_nonconvergence",
    "action": "investigating",
    "phase": "device",
    "note": "牛顿不收敛",
    "next_step": "检查迭代残差",
    "updated_at": "2026-11-17T05:00:00.000000Z",
    "evidence_recorded": false
  }
]
```

读取使用 SQLite `mode=ro`、`query_only` 和一个读事务；公开 SQL 不选择私有证据正文，只计算布尔值。读取时再次验证公开字段；未知 schema、损坏数据库、非法外部写入或读取失败均抛出 `ValueError`。主投影必须保留上一份有效公开 JSON 并标记进展数据过期，不能用空列表覆盖失败，也不能把此类异常归为仿真故障。缺失数据库返回空列表，代表尚未启用注释。

主代理负责把结果按公开 ID 与权威计划及运行证据关联，再原子发布到现有状态 JSON。网页继续定期读取公开 JSON。此模块不提供 HTTP 写入口、不运行轮询器、不连接仿真虚拟机，不触发调度、重投、收集或服务重启。`resolved` 仅表示注释所述问题处理结束；`prepared` 不代表执行，`retesting` 不代表通过。前端应单独展示进展更新时间和过期提示。

## r0.6 计数与绑定

`research.counts` 按 `Z/T/S/R/HR/HP/AL` 分块，计划数依次为
`26/68/150/12/28/30/82`；`research.totals.planned=396`，含全部 26 条 Z，
不能用 370、公开逐例列表长度或诊断尝试数代替正式分母。
`research.budget.statistics_intent_cases=214` 表示统计用途上限，
`statistics_eligible_cases=0` 是兼容静态值，不能作为动态科学合格数解读。
`manifest_eligible_cases=0` 是当前冻结清单中资格标志的事实；
`statistics_snapshot_status:"not_connected"` 表示尚未接入外部统计资格快照。
网页显示“统计资格快照待接入”并保留 214 用途上限。
计划里的 `statistics_eligible` 标志或逐例科学验收本身均不能授予统计资格。

Runtime 绑定优先读取
`runtime.intents[task_id].scientific_admission.case_id`，不要求
`work-items.tasks[].case_id` 存在。已存在的准入对象没有 `case_id` 时，
不得回退采用任务、manifest 或观测中的残留标签。
`scope=p0_diagnostic` 仅计入 `research.diagnostics.P0`，
不计正式完成或科学通过；该区块计数单位是 Runtime 登记的尝试，
不会将无 Runtime 记录的排队任务推定为已执行。
Z 基线只有正式 `case_id` 映射及原收集证据才可计工程完成，
科学通过仍独立核验原有验收 JSON 与输入、结果哈希。

r0.6 科学验收不再要求修改冻结计划的 `accepted:false` 或计划 SHA。
服务器模型有实际科学验收证据后，应在计划目录的私有
`r06-gate/results/case-acceptance/<case_id>.json` 原子保存记录：
`schema:"tcad-r06-case-acceptance-v1"`、`status:"accepted"`、
同 `case_id`、同绑定 `run_id`、原 native manifest 完整的非空
`input_sha256` 文件 → 64 位 SHA map、同原 manifest 的 `results_sha256`，
以及 1–16 项 `evidence:[{path,sha256}]`。record 最大 1 MiB，
每条引用文件最大 4 MiB，且必须存在、实际哈希匹配；引用应指向小型验收报告
或冻结读取器输出。原始大归档只由 manifest 的 `results_sha256` 绑定，
网页每分钟不会读取或重新哈希 GB 级 tar。
正式 run 还必须具有原成功收集证据；仅写记录或设置 `resolved` 均不能代替它。
不得写入占位哈希、编造验收或把短 P0 诊断变为正式 Z。

证据相对路径从计划目录解析，绝对路径仅限同一科研工作区内；
禁止 `..`、记录/证据及上级目录的软链或 reparse point，只读普通文件。
缺记录、缺引用或不匹配时不计科学通过；超过大小上限、损坏 JSON、非法编码、
重复字段、`NaN`/`Infinity` 等非有限常量、越界或链接等导致本轮投影失败，
保留上一份公开 JSON。
完整路径边界及字段契约见 [DATA-SOURCES.md](DATA-SOURCES.md) 的外部逐例验收协议。
`results` 不进入 source pack，记录、run 身份、输入 map、证据路径和正文均保持私有。
本接口不负责生成科学证据，外部验收通过也不会开启统计资格或解封 HR/HP。

如果某个完整 WHR 基线先作为 P0 诊断完成，可由科研维护者在私有
`r06-gate/results/z-baseline-reuse/<case_id>.json` 建立一次 Z 复用绑定。
记录必须是 `tcad-r06-z-baseline-reuse-v1`，声明 `run_kind:"full_whr_baseline"`、
`is_prefix:false`，并同时绑定冻结清单 SHA、Z 的 `profile_id/stored_bit`、
`deck_timing_version/hold_window_ns/timing_sha256`、profile 两个 bit 的资格、
原 manifest 完整输入 map、结果归档 SHA 和小型证据文件。读取器只接受真实
`scope=p0_diagnostic` 的成功收集 run；短 prefix、旧 r04 结果、错 profile/bit/时序、
错哈希或重复复用均拒绝。有效映射只让该 Z 获得工程 `solved` 状态，仍须独立
逐例验收记录才会显示 `accepted`，也不会改变 P0 诊断计数、统计资格或分母。

HR/HP 不出现在 `research.cases` 或 `research.progress`，
也不出现在 `simulation.current_runs/recent_activity`；
封存输运池的逐项参数同样不公开。区块汇总只含数量和工程/验收状态，
不含翻转标签、电压、阈值、事件选择或模型信息。
留出器件和辐照条件保留安全计划 ID 与 `sealed:true`，参数为空。
完整公开字段见 [DATA-SOURCES.md](DATA-SOURCES.md)。

## Codex 更新操作

1. 从原账本确认任务身份和最新事实，取得对应公开 `case_id`。
2. 问题出现时写入适当 `issue`，将 `action` 设为 `investigating`。
3. 实际开始处理后写 `fixing`；修改准备好写 `prepared`；已由原调度流程复验时写 `retesting`。
4. 有证据支持本次问题结束后填写私有引用并写 `resolved`；继续观察可写 `monitoring`。
5. 通过 `list` 检查公开投影。撤回注释用 `clear`，历史仍保留。

该接口本身不授予 Codex 修改仿真任务的权限。`set` 不修改运行、收集、成功、验收字段；公开文案过滤只覆盖常见模式，运营者仍需确保短说明适合公开。

## 本地验证

```sh
cd status-checker
python3 -m unittest -v test_progress_store.py
```

测试覆盖枚举、公开 ID、输入过滤、私有证据隔离、追加历史、失败回滚、并发、锁超时、只读打开、损坏库、外部非法写入及 CLI。目录与库文件权限测试仅在 POSIX 系统执行；Windows 上跳过该项。
