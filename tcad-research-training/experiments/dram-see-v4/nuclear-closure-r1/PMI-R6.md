# 原始 PMI 编译结果的独立工程接续

2026-10-15，当前自然核事件已按完整 N3 阶段后的固定顺序选定：`nc-r1-h-008 / event 5893`。P0、N1、N2 和 N3 的已执行事件全部保留；不进入 N4。首次器件里程碑尚未达到。

原 `nc-r1-pmi-build` 的 Cmi 编译和链接成功，ELF 导出了 `new_PMI_Recombination` 与 `PMI_Recombination_ElectricField`。紧接着的裸 `ldd` 使用了旧系统 `libstdc++`，缺少 `CXXABI_1.3.9` 和 `GLIBCXX_3.4.21`，按原严格门退出。原 SSH/远端/归档退出 `78/78/0`、本地适配器退出 `1`、23 个归档文件和全部输入均保留，不改判原操作成功。

同版本已安装的 `GENERIC` 启动脚本为其子进程设置 SDK 库目录；父 shell 随后的裸 `ldd` 不继承子进程修改。严格 SSH 只读探针已确认，同一原始 ELF 在该 SDK 环境内解析所有依赖。库和启动脚本的路径、SHA 及原始输出见 runtime `pmi-build-r2/`。这只是工程依赖证据，不证明 SDevice PMI ABI 或物理有效性。

独立实现 `native_compile_r2.py` 和 `pmi-recovery-r2.json` 只允许新工程标签 `nc-r1-pmi-link-r2`：

- 核对已知原失败、原归档全部成员、原输入、源码和二进制哈希；未知状态不能进入恢复。
- 逐字节复用原 Cmi ELF，不重编该库，不重放原失败标签。仅将已观察的 SDK 库路径设在新任务自己的环境中，不安装、不改全局搜索路径、不使用 `LD_PRELOAD`。
- 重新严格检查 ELF、两个符号、实际 `ldd` 退出、缺失符号版本、所解析库路径及库哈希。保留原失败门，不忽略错误。
- 用原样源码编译 standalone 算术探针，完成原定六个向量；向量身份、参数和原 Python 比较阈值全部不变。
- 新证明同时关联原失败和新补完结果，固定 `compiled=true, qualified=false`。真实加载、负复合符号、xyz、时间及电子/空穴响应仍必须由两个原生资格案例验证。
- 复用已成功的新操作只核验，不再次启动；已存在未知或失败操作不重提。同根因修复后再次失败暂停该依赖分支。

接续入口 `continue_pmi_r6.py` 由独立 `release-pmi-r6.json` 和 runtime `active-entry.json` 放行。它只切换 PMI 工程模块和顶层发布文件，其余 `audit-index-r5 + storage-r4` 输运/选择、原 `campaign_index_r5.py`、源数学、器件及验收门保持原字节。原 `continue_index_r5.py` 和发布记录完整保留，不再作为新调度入口。

新补完任务计一次独立编译/工程成本，不计输运事件或 TCAD。原失败编译调用仍在账本。实施前快照：输运正常 17/107、纠错 1/2、不同初级 100008/1000008、重放 0、TCAD 0/18、编译/工程 4；后续以全部 attempt 和最新现场报告重算。

所有者仍为原 continuation/owner.lock，远端仍用原共享 solver 锁、单计算线程和 CPU0。现有真实进程健康时不另起调度；启动新入口前核查旧 owner 退出和原目录真实结束。工程发布不替代科学验收。
