# 成功结果的分层保留与空间循环

2026-11-17 用户授权：成功组保存关键数据，清理仿真大文件；服务器内存上限仍为32GB。
本规则覆盖旧文档中“所有成功结果永久保留未压缩大日志和原tar”的描述。
失败谱系、活动作业、输入、锁、虚拟机和许可不在清理范围。

## 保留什么

每个成功结果保留原manifest和SHA、输入deck/参数/源数据/PMI、原始数值PLT、
初态/源前后/关源/末态TDR与SAV、完整非回调日志和原行号映射、
成员SHA清单、提取缓存、关键指标/波形、匹配对照与验收说明。
科研失败、未知标签和未完成对照保持原含义；存储收据不是科学验收。

当前四份长瞬态归档每份约3.6–3.9GB，主要由两份重复记录海量
`R04_QY_CALLBACK`的日志组成；数值和场快照远小于日志。
精简日志明确标为投影，保存未删行的原行号及全部原日志SHA，不能冒充完整原文。
所有非大日志成员逐字节保留；本版不自动丢弃任何TDR或数值列。
若后续某种场输出本身变大，先提取冻结判据需要的场量，再另定该版本快照范围。

## 两步回收

1. 原runner已成功收集、exit0、原归档验签且槽释放，研究读取器已生成绑定原SHA的
   完整数值缓存后，用`ready`移交。原Runtime一次最多启动一个低优先级存储worker。
   worker生成并验证`results.essential.tar.gz`及`retention.json`，同时生成
   **能逐字节恢复原tar的`results.raw.tar.gz`**，解压SHA必须等于原manifest。
   全部验证通过才删除服务器未压缩`results.tar`；再逐文件验核虚拟机对应大日志和
   `.collection/results.tar`后删除这些重复件，保留虚拟机输入、数值、场、身份及receipt。
2. 对照比较、波形/判据解释及必要图表已完成，将绑定原manifest、archive和证据SHA的
   `tcad-result-retention-release-v1`文件交给`finalize`。
   将最终证据复制到该结果目录并验核关键包后，才移除无损大备份。
   之后只保留关键包、数值缓存、解释和来源；不能再宣称完整回调日志仍可恢复。

四条mc2事件当前仍待各自新zero的严格比较与数值解释，**只允许第一步**。
对照完成求解不自动构成科学验收；比较未通过时继续保留无损备份。不为省空间提前赋予
valid_nonflip、翻转或总体统计标签，不删除唯一尚需读取的证据。
保留策略不增加独立primary、不改变DEV/m1-r05/BENCH分母或原判据。

## 操作入口

所有命令在TCAD服务器原工作区内由唯一研究消费者执行；不会提交或收集求解任务：

```text
python3.12 automation/server-codex/result_maintenance.py ready <原RUN目录> --evidence <缓存/extraction.json>
```

启用`result_retention_enabled`的原Runtime处理ready项。人工恢复维护只用：

```text
python3.12 automation/server-codex/result_maintenance.py maintain <原RUN目录> --connection <原profile>
```

冻结旧读取器仍要求原tar；通过包装入口按需恢复**完全相同字节**、读取后立即回收，
不修改旧reader或缓存版本。新zero首次提取和event/zero比较都使用同一包装入口：

```text
python3.12 automation/server-codex/result_maintenance.py read experiments/dram-se-r04/electrical/multicore-response-reader-r1/extract.py extract <RUN> <INPUT> --output-dir <新缓存>
python3.12 automation/server-codex/result_maintenance.py read experiments/dram-se-r04/electrical/multicore-response-reader-r1/extract.py compare <EVENT_CACHE> <ZERO_CACHE>
```

`finalize <RUN> --evidence <RELEASE.json>`只用于完整结束的组；release必须明确
`scientific_review_complete=true`、`release_original_archive=true`、run_id、
manifest_sha256、original_archive_sha256，以及非空`key_evidence`路径/SHA清单。
对照自身需等所有依赖该对照的事件完成比较后才finalize。

原manifest不改，Runtime同时识别原tar及已验证的保留收据，不能因回收空间重收、
重投旧任务或错误占槽。若恢复读取失败，保留原错误，不能换旧对照或放宽判据。
每份结果的完整维护、最终释放与“恢复→原reader→回收”共用
`.retention-transaction.lock`；比较两份结果时按固定目录顺序取锁。
归档worker使用流式处理，服务器管理CPU、单worker、低优先级，不占求解槽。
巡检继续核对guest /home、实际overlay和host根三层；预留至少20GiB服务器缓冲及
待收集/按需恢复空间，不把逻辑分区容量当成物理容量。在线discard及原trim流程沿用。
原fstrim.timer已启用为每小时回收：虚拟机每小时10分只trim /home，
服务器15分只trim实际overlay，将已释放空间归还物理写入池。
服务器根分区的额外全盘trim因耗时过长已撤下；写入池回收会直接归还服务器根的文件占用。

## 当前规模的长期占用

15:40 UTC按四份已回收事件的虚拟机原目录逐文件统计，保留的输入、数值、场和
身份资料每条实际分配38.81–45.57MiB；服务器关键包及提取证据每条34.16–39.78MiB。
300个单状态响应的服务器关键包约10–12GiB，虚拟机保留件再占约12–14GiB，
两处长期合计按22–26GiB预留；300对b0/b1为600响应，约44–52GiB。
这是已完成完整验收、允许finalize后的同规模估计，不含活动任务、失败保留件、
按需恢复空间、共用数据及系统开销，也不把三层文件系统可用容量相加。

待验收无损备份当前每条约244–262MiB。如果300条一直未能结束验收，
临时备份本身将约74GiB，不能按长期关键包大小无限积压。
按原研究依赖及时消费和finalize；科学解释未闭合时限制新任务供给，
不能为了腾空间删除仍依赖的唯一证据。四条事件目前仍保留可恢复原包。
统计证据：`local_runtime/server-codex/operations/20261117T1530Z-snapshot-race/guest-footprint.json`
与原`20261117T1230Z-result-retention/FINAL-RECEIPT.json`。

预算清单和生成器的来源SHA保持冻结；新的吞吐估计另作日期记录，不改已冻结清单来源。
