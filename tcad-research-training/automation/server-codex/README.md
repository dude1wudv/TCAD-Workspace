# 服务器 Codex 自主推进 v2

按需原生 Astra 顾问见 [ADVISOR.md](ADVISOR.md)：Sol保持主模型，
顾问使用 `auto/gpt-6-astra/high`，通过原生子代理及同会话续问工作。
新控制器在模型等待期间继续使用原Runtime收集、补槽；顾问不占求解槽。
活动服务采用无重启部署时，监督循环改进在下一次正常启动后生效。

当前实现对应 [DRAM 新研究计划](../../plans/dram-se-ddr5-lpddr5/PLAN.md)：DDR5负责工程截面、错误率和外部验证，LPDDR5负责TCAD代表结构与机理。服务使用服务器现有 Magpie 路由。开发与验证期间保持禁用，不启动仿真。实际验证与部署状态见 [VALIDATION.md](VALIDATION.md)。

## 先查看或迁移，均不启动任务

在服务器用独立 Python 运行（系统 Python 3.9 不用于原 runner）：

```bash
<AUTONOMY_INSTALL_DIR>/python/bin/python3 -B <AUTONOMY_INSTALL_DIR>/current/controller.py \
  --policy <SERVER_CONFIG_DIR>/policy.json status

# 旧 v1 策略迁移：保存原始备份，生成 disabled v2，清除旧准入引用。
<AUTONOMY_INSTALL_DIR>/python/bin/python3 -B <AUTONOMY_INSTALL_DIR>/current/controller.py \
  --policy <SERVER_CONFIG_DIR>/policy.json migrate
```

`status/check/plan` 只读本地配置与状态，不执行模型、SSH或求解。`init`只建私有状态目录。迁移保持原工作区、解释器、模型路由和任务文件路径；并发上限设9，补新计划/队列路径；原科学账本不迁移、不清理。安装器仅在 task.md 与旧安装默认模板字节完全相同时，备份并更新为本版说明，保留权限及所有者；自定义内容保持不变，并返回需要对齐的提示。单独执行 `migrate` 只迁移策略。

未来获得整套研究执行授权后，只做一次实际工作区、原作业及唯一调度权交接，填写readiness示例中的范围/原profile/SHA，并用 `arm --readiness <实际文件>` 固定执行身份。`arm`不启动；服务启动是另一个明确操作，本次开发不执行。计划、任务书里的“未授权”声明也应在那次交接按真实授权更新，不能把本次软件开发当作研究执行授权。

## v2 的运行分工

| 层 | 工作 | 状态依据 |
|---|---|---|
| Codex | 读计划、准备冻结输入、分析数据、训练数值预测器、提出有理由的修复 | 研究计划、原产物与本轮事件 |
| controller.py | 单实例、事件唤醒、模型退避、暂停/恢复、凭据隔离 | 私有checkpoint和配置 |
| runtime.py | 对账原run、收集、按依赖填空槽、记录提交前意图与修复谱系 | 原manifest、原收集回执和归档SHA |
| 原TCAD/Geant4 runner | 冻结输入、共享池0–8、远端启动、身份验证、收集/释放原槽 | 原owner、gate、槽锁及原账本 |

`work-items.json`是任务提案，`runtime.json`是提交意图索引；两者不替代原科学账本。Codex不直接启动求解或另建后台调度器。原runner仍是唯一执行接口，保留原输入、结果、失败、目录、run ID、连接与锁身份。

原共享锁同时约束 TCAD 和 Geant4。心跳、容量和槽宽由当前已交接的策略/profile 决定；历史 9 单核示例不是生产上限。冻结宽度与实际空槽匹配，原租约未释放不补位。首月例程和发布验收见[首月操作手册](MONTH-ONE.md)。

模型仅在首次规划、原作业/输入/计划发生变化、实际工作产物需要接续，或模型失败退避到期时调用。稳定的waiting/blocked不会按固定间隔重复调用；持续追加日志及更新时间不作为唤醒理由。默认最小模型间隔300秒，单轮最多1200秒。`maximum_cycles_per_start=0`表示持续监督，不再每288轮要求人工续期。大队列在模型提示中只给有界摘要，完整原状态文件可按需读取。

已授权计划内自动跨研究阶段，有输入产物即可启动下游，不要求整包上游关闭。理论偏差、缺失论文参数、局部数值失败由研究工程师记录假设、诊断和修订；不再每轮重新验七项passed，也不把P0→P1当全局门禁。执行授权、唯一调度权和原身份核对仍保留。

## 怎样准备任务提案

先实际创建符合原runner要求的独立输入目录，再原子替换配置中的queue_file。正式示例文件为空，避免误执行；下面仅说明格式：

```json
{
  "schema": "tcad-work-items-v1",
  "tasks": [
    {
      "id": "lpddr5-baseline-001",
      "backend": "tcad",
      "project": "experiments/dram-se-inputs/lpddr5-baseline-001",
      "depends_on": [],
      "requires": [],
      "repair_of": null,
      "repair_reason": ""
    }
  ]
}
```

- `id`：小写字母、数字和连字符，提交后不改。普通run由监督生成一次性ID；有冻结 `s2_geometry.run_id` 的旧项目保留其精确ID。
- `backend`：`tcad`或`geant4`。TCAD目录须有原格式project.json；Geant4目录须位于原 `local_runtime/cloud-benchmark/geant4-preparation/inputs/` 下且含task.sh。实际结构、物理/数值输入仍由原runner处理。
- `depends_on`：必须完成的具体任务ID（成功修复可满足父任务依赖）；`requires`：需要的工作区相对输入产物路径。只用真正必需的依赖，不把整个研究阶段设为依赖。
- 修复：新id、新目录、不同输入，`repair_of`引用已失败且收集的父任务，`repair_reason`记录日志依据与修改。默认每谱系最多2个修复尝试，超额只暂缓该谱系，独立任务继续。
- `adopt_run_id`可显式接续同一原profile下的已知任务，必须匹配原输入目录、原槽与身份；不生成新的提交。其它profile的外来任务仅占位，先用其原恢复流程交接，不能改绑。

任务提出后，不覆盖原输入、删除已提交任务的历史或篡改原账本。队列空不代表科研完成；`complete`只有在原队列无运行/待做/修复/局部阻塞且计划成果真实具备时进入idle，后续新事件仍可唤醒。工程收集完成不等于科学验收。

## 失败、断线和暂停

提交前先落盘run ID、原profile、槽和输入摘要。进程重启/SSH断线/提交返回未知后只查同ID的status/collect，不再次run。原manifest缺失也不猜测“未启动”。原archive已收集但槽释放未确认时，只重收原ID补闭环。原归档SHA、collection_verified与parallel_slot_released决定工程终态，SSH退出码不能代替远端退出码。

模型/API超时、非零退出或坏JSON进入300秒至3600秒指数退避；监督仍可收集、填已准备好的任务。模型恢复前再次对账。端点不可达也退避，避免一次断线让9项各等满超时。可验证的数值失败通知模型准备修复；未知启动/缺原身份不伪装成可重投的数值失败。无法安全恢复的那一项保留原占位并说明原因。

```bash
# 停止新工作，不杀原远端求解、不删锁。
<AUTONOMY_INSTALL_DIR>/python/bin/python3 -B <AUTONOMY_INSTALL_DIR>/current/controller.py \
  --policy <SERVER_CONFIG_DIR>/policy.json pause --reason '暂停新工作'

# 长期禁用；不停止已有远端任务。
<AUTONOMY_INSTALL_DIR>/python/bin/python3 -B <AUTONOMY_INSTALL_DIR>/current/controller.py \
  --policy <SERVER_CONFIG_DIR>/policy.json disarm
```

每项提交前重查pause/disarm，批次中途暂停也不会把后八项全部投出。`clear-pause`仅清人工暂停；旧版标记为需人工核对的pause仍兼容 `--reconciled`。正常的v2断线/坏报告无需人工clear。systemd异常退出可30秒后重启；配置/身份拒绝以退出码2阻止重启空转。服务退出不会停止原runner的远端后台作业。

## 安装与文件位置

默认工作区 `<SIM_USER_HOME>/projects/tcad-research-training`，已配置workspace优先；真实科研工作树若在其它位置，必须明确配置，不自动猜测。`state_dir`须在研究工作区外，默认 `<SERVER_STATE_DIR>`。配置在 `<SERVER_CONFIG_DIR>`，代码在 `<AUTONOMY_INSTALL_DIR>/releases/<版本>`。Codex以tcad非root运行，workspace-write和systemd权限限制沿用；模型只接收回环Magpie凭据环境，原runner不继承这些凭据及本机HTTP代理。

```powershell
python -B -m unittest discover -s automation/server-codex -p 'test_*.py' -v
python -B automation/server-codex/package.py --output <新的源代码包路径>
```

包记录逐文件SHA，包含实现、空提案示例、新研究计划和YAML；不包含实际work-items提案、.git、local_runtime、VM、许可、密钥、原始数据和结果。它不是完整研究状态迁移。安装器拒绝覆盖未归属工作区或已改源码，保留既有配置和状态；v1会先备份再迁成禁用v2。新快照建立有明确来源标记的本地Git元数据供原runner读取；既有repo只验证HEAD，不改其index和提交。安装器校验/刷新unit并init，绝不enable/start。

完整安装仍用 `install.py --bundle <包> --sha256 <包SHA> --release <UTC版本>`；已有独立CPython3.11+保留，缺少时使用prepare_python.py的固定版本/SHA流程，不替换系统Python。源码、离线编排验证、真实服务沙箱/API联通、真实9并发及科研验证是不同验收层。当前范围与未做项以VALIDATION记录为准。


## 共享池异步调度（兼容 v2 策略）

十三槽独立派发、虚拟机封存与后台收集见 [十三槽派发与收集](SLOT-WORKERS.md)。

`SchedulerEngine` 继续使用原 `Runtime` 的科学准入、输入校验、repair 谱系和原提交意图。每轮只做一次有界只读 SSH 采样；原提交、取消和收集共用一个后台串行通道，保留全局 owner、gate、槽锁和原租约。原运行器验证归档并确认释放后才能补槽。未确认启动的原 ID 继续保留预约；只有原运行器出具、校验通过的未启动证明才可解除预约。

新策略示例见 `policy.example.json`。默认心跳 5 秒；内存估算只预留未被实测 RSS 覆盖的部分。服务器剩余空间、虚拟机剩余空间与服务器上虚拟机磁盘文件可增长空间分别准入，不能相加。实际配置要求磁盘文件增长核验时，设置独立的 `resources.backing_disk_path` 和 `require_backing_disk=true`。许可守护进程只影响 TCAD，席位数未知时保留原运行器验证。首版 `collect_concurrency` 必须为 1。

`planner_mode=disabled` 不启动模型，不要求模型二进制或配置；`on_demand_async` 保留原按需 Sol/Astra 规划，在后台去重运行，不持有原运行器所有者锁。自动排空受最短驻留和最长就绪等待控制；人工排空持久化到重启后，直至完成目标预约或明确撤销。隔离槽保留原证据与租约，并允许其它合格旧剖面空槽继续补位。看门狗始终只告警，兼容读取旧 `auto_stop` 也不会自动发信号。

```bash
python3 controller.py --policy <POLICY> reconcile --read-only
python3 controller.py --policy <POLICY> explain
python3 controller.py --policy <POLICY> cancel <ORIGINAL_TASK_OR_RUN_ID> --reason '<operator reason>'
python3 controller.py --policy <POLICY> drain --to geant4 --reason '<operator reason>'
python3 controller.py --policy <POLICY> drain --cancel
```

人工命令交给唯一服务消费；不会另起求解调度者。取消由原运行器验证 PID、boot、脚本及原身份，记录真实信号和最终静止证据；缺失的原始退出码仍为 null，派生退出码单列。旧 wrapper 只能沿独立验证过的原生进程取消，不能猜测作业组。

诊断仅扩展 `observation.json.scheduler`：池状态、资源阻塞、任务状态、单轮原因及真实累计指标；没有样本的平均耗时为 null。`metrics.jsonl` 有界轮转。公开状态检查器继续读取原字段，不能转发私有 scheduler 诊断。

发布必须同时交付新增 `scheduler_*.py` 与 `scripts/runner_termination.py`，并与两套原运行器版本绑定。先核验空闲池、全量原租约、内核锁和未登记求解器；使用原 SHA 清单和安装器暂存版本，备份原配置及受影响源码，再切换版本。验证只用 `check` 与 `reconcile --read-only`，`serve --once` 仍可能提交任务。回滚保留期间新增的原账本和失败证据，不恢复旧状态文件。

只读对账显式禁用旧存储维护与云盘侧车。已完整校验的原归档在私有 `verified-archives.json` 中保存有界缓存；复用必须同时匹配原 SHA、路径、设备/inode、大小、mtime 与 ctime。缺失或变化仍须完整复核，首次核验由独立维护步骤完成；只读路径本身不写缓存，也不以收集状态代替校验。

新增归档的完整校验与缓存写入也在唯一后台收集通道内完成；校验期间不在主循环重复散列。观察既有 intent 时不新增空诊断字段，保留原未启动回执的不可变身份校验。
