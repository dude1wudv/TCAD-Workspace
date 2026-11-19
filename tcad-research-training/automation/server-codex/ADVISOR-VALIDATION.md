# 原生顾问验收记录（2026-11-16）

## 已完成

- 服务器Codex 0.169.0：Sol `auto/gpt-6.1-sol/high` 主会话创建一个
  `astra_advisor`；子会话实际 `auto/gpt-6-astra/high`。
- 原生 `spawn_agent`使用独立上下文，返回任务路径。
  Sol通过`followup_task`向同一顾问续问，收到两次真实答复。
- 根UUID：`01a1e43e-d378-74d3-a907-23df24f60824`。
- 顾问UUID：`01a1e43f-03a0-78b1-ae1a-d853cde961ad`。
- 顾问任务路径：`/root/advisor_validation_9669bf55f896`。
- 一次完整验证耗时75.547秒。使用人工零计数问题及给定公式，不是科研数据。
- 两个会话均为独立空目录、read-only沙箱；根会话仅使用原生协作工具，
  顾问没有工具执行；未提交仿真。
- 服务器109项离线测试全部通过；包括模型等待期间原九槽收集/补位、
  disarm阻止新提交、原ID保持、超时、原生路径/UUID/答复持久化。
- 本地八项部署源码SHA与服务器版本全部一致。

## 初次部署与当时生效范围（12:11 UTC）

版本：`<AUTONOMY_INSTALL_DIR>/releases/20261116T121146Z`。
部署前后控制服务PID均为16658且active；未重启。
原`runtime.py`逐字节保持，策略文件部署前后相同，并发上限9。
QEMU仍为PID2757、CPU0–8；独立咨询验证限定服务器管理CPU9–11。
部署后只读观察到原监督记录6个活动任务，未修改队列、原run或槽池。

角色文件位于私有`<SERVER_STATE_DIR>/codex-home/agents/`；
使用说明追加到原操作任务文件；生产新轮次
`20261116T121217Z-e47ee751`的prompt已实际加载该说明。
**已在运行的旧Python进程不热加载代码：模型等待期间继续监督、自动会话索引
在下一次正常启动控制服务后生效。**本次未为激活它们重启主线程服务。
未把隔离咨询成功称为主线程已经实际使用顾问，也未执行生产断线故障注入。

## 原证据

- 服务器咨询目录：`/var/lib/tcad-advisor-validation/20261116-r1/`。
- `verified-evidence.json`：11项原生链路检查、实际模型/会话、答复和usage。
- `events.jsonl`及隔离CODEX_HOME内的父/子rollout：原始调用与答复。
- 服务器部署目录：`/var/lib/tcad-advisor-validation/deployment-20261116T121146Z/`；
  包含部署前操作任务备份及`deployment.json`。
- 本地已收集证据：
  `local_runtime/server-codex-advisor-20261116/{verified-evidence,probe-result,advisory-sessions,deployment}.json`。

结构化输出限制与跨根会话恢复边界见[ADVISOR.md](ADVISOR.md)。

## 安全启用与生产接续（12:27–12:31 UTC）

2026-11-16 12:27:03 UTC，主线程在Sol本轮自然结束、checkpoint为`reported`、
控制器没有活动子进程的窗口，完成已有修复的重启。本侧线程跟随该次切换验收，
没有追加重启、投递仿真或调用模型做重复验证。

- 生效版本：`<AUTONOMY_INSTALL_DIR>/releases/20261116T122703Z-runtime-failure-fix`；
  控制器PID由16658变为22575，服务active。新版保留原顾问及异步监督代码，
  并包含主线程已通过40项测试的运行失败识别修复。
- 原策略、readiness、连接身份和9槽容量不变；只有一个控制器持有原
  `controller.lock`。QEMU仍为PID2757，start_ticks及CPU0–8亲和性保持。
- 原6项Geant4失败按原run ID完成收集，没有改成成功或重复提交。
  TCAD作业`auto-r04-l08-p000-electrical-v1-0ab40348a7d84362`
  于12:26:34 UTC提交，跨重启后原进程身份仍存活、仍在原槽0。
  12:31:24 UTC快照为1项运行、0项待提交；容量9不代表当时9项满载。
- 新生产轮次`20261116T123045Z-ba59ed8e`的原生日志确认Sol high；
  私有配置显式注册`astra_advisor`，角色为Astra high，实际prompt含顾问说明。
  同一个Sol进程持续运行期间，原监督观察从12:30:45更新到12:31:17，
  验证模型工作期间调度监督继续运行。
- 复用此前一次Sol→Astra→同一顾问追问的真实验证，11项检查和父子原生日志SHA
  再核对一致。本次没有强制生产会话咨询，也没有新增付费验证。

本轮22项生效与保留检查通过，记录见
[activation-verification.json](../../local_runtime/server-codex-advisor-20261116/activation-verification.json)；
同目录保留重启回执、前后状态、虚拟机槽池及同一模型轮次的两次观察。
之前109项离线测试与主线程40项运行修复测试有覆盖交集，不相加计数。
没有为本次验收另做九路满载仿真或生产断网故障注入；本记录不代表科研结果验收。
