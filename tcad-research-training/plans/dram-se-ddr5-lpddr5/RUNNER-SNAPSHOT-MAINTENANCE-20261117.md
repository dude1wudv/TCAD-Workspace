# 2026-11-17 资源快照竞态维护

15:45:31 UTC 已原子部署到原工作区 `scripts/tcad.py`，没有重启控制器或虚拟机。
这是原运行器的局部维护，不是新调度器；原池、锁、连接、活动目录和原run均保持。

- 原源码 SHA：`d6f2a1ce48d6c6407a098ead2eec2c43594a1aa3b6dcc1a274c7c987021cbca2`
- 新源码 SHA：`7db31301877877464393d42b4d4d44c4d989e1dbb5b40a05380ed144dff8ccea`
- 原资源 readiness 内的 runner SHA 保留为原短测基线；本维护收据记录后续源码版本，
  不修改旧 readiness、原manifest、旧run脚本或其哈希。

原短诊断 `r04-l08-mc2-prefix-b0-event0-v1` 在admission读取其他native的
`/proc/<pid>/task/<tid>/stat` 时，线程已经退出，尚未启动SDevice即失败。
本次只修复资源观察：线程文件消失、已打开的线程文件返回ESRCH或成员变化时，
有界重取整份快照，最多8次、间隔10ms；不跳过单个线程。
重取期间锚定原进程start_ticks，CPU越界、身份错误、权限错误及原进程文件消失仍立即拒绝。
已观察到的CPU越界不能被后续线程变化掩盖。
不重试工具执行，不修改物理输入、数值判据或科学标签。

原15项资源回归及17项快照回归共32项在Linux全部通过，包含真实短线程退出测试；
本地Windows同一集合31通过、1项Linux测试跳过。
冻结存证验证函数`mc_validate`源码保持相同；嵌入代码通过Python3.6语法检查。
首次Linux测试复现额外ESRCH并阻止部署；修复后完整通过，首次失败日志保留。

原event0诊断失败及repair请求继续保留，不原样重投，不把基础设施失败当负例或数值失败。
研究消费者继续沿原队列消费共同状态诊断与b1对照；若后续确有必要修复原诊断，
使用新输入目录、task/run ID和明确的`repair_of`，`repair_reason`引用本维护，
不得为消费修复次数而随意改变物理参数。是否还需要该诊断由已有证据决定。

证据：
`local_runtime/server-codex/operations/20261117T1530Z-snapshot-race/deployment.json`。
服务器完整Linux日志在同名操作目录及
`<SERVER_STATE_DIR>/operations/20261117T1530Z-snapshot-race/`；
维护前源码保留为`tcad.before.py`。
