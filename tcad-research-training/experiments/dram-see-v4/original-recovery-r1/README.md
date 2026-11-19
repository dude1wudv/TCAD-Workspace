# 原 A1 的单次工程恢复例外

本修订仅处理 `r5-a1-b1-time-r1` / `20261014T040702Z-v4-source-interface-r5-a1-b1-time-b8fc5db7`。用户在 2026-10-14 明确答复“授权该单次工程恢复例外”。原远端退出 0，完整原生日志与两条 PLT 到 4 ns，但原 SSH/本地 runner 退出未知，包装日志缺少强制完成标志。

原执行合同没有通过。本修订用独立的、精确绑定原件 SHA-256 的恢复合同确认工程证据，保留原 `manifest.json`、`execution.json`、归档、冻结代码及合同。没有把未知退出写成 0，也没有改写 `ENGINEERING_RUN_COMPLETED`。原调用仍只计一次；恢复、传输、后处理不新增 TCAD 调用。

`recovery_proof.py` 验证同一原始输入、849 个原始文件的归档、原远端退出、全部声明输出、完整有限曲线、404 个接受步及 1 个边界帧。`fields_bridge.py` 使用原 Tcl 和 operation 适配器取得真实原生字段，`recovered_audit.py` 组合原冻结物理函数并保留新报告身份。`acceptance.py` 保留匹配 A0、场积分、时空分布、守恒和数值细化比较，全部物理门槛原样适用。

新增控制器是可审查的静态修订；不修改原模块全局对象、不在运行时替换源码。`dispatch.py` 和 `pilot_control.py` 仅为该精确历史记录接受恢复证明，其他未知记录继续阻断。`make_report.py` 能重放恢复结果并显示原退出未知，不将历史 RUNNING 记录误报成正在运行。

`continue.py` 持有唯一接续所有权，顺序等待二维子调度退出，再启动三维/固定输运子调度；两者仍使用原锁、预算、单 CPU 和单计算线程。任何阶段非零退出即保存状态，不重试。三维前必须全部 17 项通过、二维进程退出并释放锁。原 A1 后处理副本暂保留，未复用旧清理证明。

启动前必须有通过独立验证的 `release.json`，且 `recovery_proof.check_release()` 同时核对原冻结发布和本修订。活动所有权和原始日志位于 `local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/continuation/`。既有旧入口不支持本次恢复；不可修改原记录使其勉强通过旧入口。

这项例外不授权新工况、额外事件、种子搜索、训练、软件安装、Git 提交推送、对外消息或心跳。
