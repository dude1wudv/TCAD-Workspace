# R50-main 原生取证入口

`gui_evidence.py <真实run_id>` 从原v3取证器显式派生，只接受冻结的两个对象：`v3-r50-main-physical-l018-b1`、`v3-r50-main-l018-alpha-a30-s202610311-b1`。调用前必须完成对应真实求解，验证ledger、R50 schema/revision、原始输入和结果归档哈希、主执行plan/case-freeze与源码快照；旧100Ω、probe、FAILED及未提交不符合条件。当前只有开发验证，尚未执行此版本GUI或产出R50图件。

入口沿用原共享controller.lock及实际主机/VM/manifest预检。只有正常求解结束、没有活动调度者的安全边界才能调用；不得为了截图打断主控制器或SDevice。运行无新求解、无自动样本选择/重试/关闭窗口；任何已存在或部分取证目录只读核查，不覆盖或重新启动。

真实取证将加载对应run的4ns最终信号`final_access_des.tdr`，显示`Abs(ElectricField-V)`、V/cm和µm坐标，保留原生1400×1000 PNG及新建自有SVisual窗口像素。目录为本目录`figures/native/<run_id>/`，操作日志为`local_runtime/dram-see-v3/r50-gui-operations/<run_id>/`；远端独立`dram-see-v3/r50-main-gui/<run_id>/`。加载前后TDR哈希、自有进程启动时钟/cwd、窗口ID和PNG内容完整性沿用已验证原流程；未修改旧GUI代码及旧图件。

`CAPTURED_PENDING_VISUAL_REVIEW`仅代表取证器完成。root还须使用实际PNG逐张核对run ID、变量/单位/色标、时刻和窗口内容，另存目视验收记录；图件不能替代瞬态读出数据、全矩阵完成、Workbench按钮操作或课程教师/学生活动。此入口不假定其它阶段已完成。

源码及依赖绑定于`gui-source-manifest.json`；明确差异与原始哈希见`gui-derivation.json`/`gui_evidence.py.diff`。它不进入首段求解manifest，不改活动依赖。root完成5项隔离测试（`local_runtime/dram-see-v3/r50-gui-dev/check.py`）：35依赖与保留函数AST、Tcl字段及路径、错误对象/状态、私有正例冻结链及逐项篡改拒绝、来源归档不一致时在preflight前停止。命令退出0，未接触生产ledger/archive、锁、SSH或GUI；实际GUI/原档仍待条件满足后验收。原计划中的独立worker尝试因并发名额不足未启动，由root接管验证。
