# r3 之后的实际接续入口

本文件是交接说明，不是求解完成证明，也不属于活动控制器的代码依赖。

- 当前测试结果应从 `local_runtime/dram-see-v3/physical-revisions/r50-main-restart-r3/` 读取。只有实际生成且原档重审通过的 `test-result.json` 才表示64个逻辑测试响应完成；`prediction-scores.json` 和 `metrics/` 也位于该目录。不能用旧 canonical 导出覆盖新结果。
- 模型及64条逐测试预测仍是 `r50-main/data/predictions/` 的原冻结文件；新计划只引用，不重新拟合。原失败和 retry 在 `raw_submission_index` 中各占一条，但逻辑事件/响应分母不增加。
- 全128个主响应的解析必须包含三项明确 alias：r2 的一个训练工程重试，以及 r3 的两个测试工程重试。先核实原 FAILED 被保留，再用已 VERIFIED 的唯一对应新采集提供逻辑响应。失败原档不能用于评分或边界排序。
- 现有 `extensions.py` 与 `delivery.py` 为旧 r1 接口，仍有旧计划路径、成功前缀、预算/截止和 canonical-only 假设。不能直接启动或声称其已兼容 r3。应新增版本化适配层，保留旧源码，独立验证之后才激活。
- 扩展仍按原科学设计执行：14项氧化层，然后从完整128主响应按原规则冻结两个边界目标并做匹配细化。未知失败阻断依赖，连续数值门槛不得调整。新版本仅使用现有无上限资源授权，并保持实际逐次计费。
- 原生图件仅取原预定两个R50对象，实际查看每张PNG并核对源、物理量和单位；报告、PPT与课程材料必须引用真实结果，学生操作、教师审核、答辩及考核未发生则保持待完成。

自动检查可使用 `local_runtime/dram-see-v3/live-checks/inspect_r3.py <唯一证据标签>`。它只记录进程/创建时间/命令、锁、VM实际求解目录与CPU、计划来源和原账本保护；不启动、收集或改判求解。

控制器由 Windows Task Scheduler 的 `DRAM-SEE-v3-R3-Controller` 按需启动。任务无周期触发，`IgnoreNew`、隐藏、无执行时限；Codex的20分钟心跳负责后续检查。检查必须看实时 `task-launch.json`、实际进程和VM，不能只看调度器的Running或旧PID。正常求解不停止或另启。若控制器退出，先保存task-exit及原档，只有确认无旧所有者和求解器才处理接续。
