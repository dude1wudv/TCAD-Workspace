# 既有原档与新S2审计的证据兼容表

本次只读既有归档用于格式调查，不把旧几何、旧事件或旧资格作为S2样本。原runner、原S2代码与数值门保持。

| 项目 | 现有事实 | 新适配器处理 |
|---|---|---|
| solver SSH退出 | manifest.ssh_exit_code | observed，非零/未知拒绝 |
| 远端总退出 | results.tar内exit-code.txt | observed；与manifest已有值矛盾拒绝 |
| solver收集退出 | 原manifest没有独立collection_exit_code | unavailable；COLLECTED仅列inferred成功，绝不填0 |
| SDevice逐工具退出 | 原run.sh set-e及完成链，没有独立raw文件 | unavailable；未来未应用补丁按step记录真实wait结果 |
| solver CPU | 原日志只显示父shell 0–7，native命令taskset单核 | 只保留推断；不改写成实测0。未来需精确native PID/proc事实 |
| native进程身份 | 仅Name或单核status不证明其来自本次原生命令 | 新adapter校验process-observation中的PID/PPid/starttime链、精确exe、安装目录和status SHA；solver另验独立admission及其真实退出 |
| SVisual CPU | 原affinity.txt是Threads:1/Cpus_allowed_list:0两行wrapper记录 | 正确解析，明确wrapper，不能冒native PID观测 |
| 工具计算线程/版本 | 原native log中W-2024.09、assembly/solver threads或SVisual multithreading | 直接读取，缺失或非1拒绝 |
| shared lock | 原脚本flock-n9与完成链；无独立raw收据 | inferred不能代替observed；未来候选在真实成功后落盘 |
| 几何 | review包geometry-contract仅名义CAD | 不重命名为native报告；需实际mesh、材料/接触/掺杂校验及其原始证据 |
| 来源 | 原生执行与合成单测必须分开 | public native入口拒绝synthetic/historical/unknown origin；fixture入口只作解析测试 |

真实格式样本：`local_runtime/dram-see-v4/transport-probe/operations/nc-r1-fields-qualification-zero-trace-r10`。其7,567,360字节results.tar SHA为`27b31c17dad02a8e227166c9910b9f7d6ca7aa79e28509771b3ba19c7eedf332`，69帧、原始TDR不复制；新版collector对缺失native PID/锁事实继续报告缺口。

原普通solver样本`20261014T002741Z-v4-source-interface-r5-a8s4-b1-main-b3d433fb`的634,449,920字节results.tar SHA为`8a0aa7af0eaea8ca3c0c5071d2dfc6eaf1c13eb23193c76d91745fb752fa0cb6`；只证明旧生产链格式。S2原生正常路径仍未运行。

`evidence.py`只读检查完整输入/结果归档，不解包、不写receipt、不调用进程或网络。每fact记录observed/inferred/unavailable、source和SHA。`audit.py`复用旧S2的全BE/PLT/TDR索引、四阶段原路径身份校验、逐帧释放和全部数值门；自己的接口层增加直接观测、发布/授权/预算引用与实际几何证据绑定，不修改旧函数全局。

F5交付包含未应用capture补丁候选。它不表示已经修改生产runner或新建另一套运行器；future原生需单独审查发布，实际native PID捕获/厂商launcher行为/归档正常路径仍待测。短暂或无法唯一识别的进程保持未知，不猜值、不终止健康任务、不自动重跑。

主审后按E010补齐collector与capture之间的身份链和独立准入接线；原始格式报告`existing-extractor-format.json`是补接前的离线记录，旧档本来就缺少这些观测，不能因此升格为S2资格。最终实现仍只读原档，合成夹具公开native入口仍须拒绝。
