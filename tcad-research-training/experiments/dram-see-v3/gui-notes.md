# v3 原生电场导出与真实 SVisual 窗口取证

状态：2026-10-10 15:18 UTC，两个原计划选定的已VERIFIED对象已通过本脚本实际启动SVisual、原生导出和自有窗口截图，并由主代理逐一查看四张PNG。详见[native-visual-review.md](native-visual-review.md)及其来源/视觉检查JSON。以下mock测试保留原验证范围；历史只读调查见 `local_runtime/dram-see-v3/gui-investigation-notes.md`，不能把旧版图件计为新版完成证据。

## 显式入口

由主代理在已核实求解空闲时，指定确切新版 run ID：

```powershell
python -B experiments/dram-see-v3/gui_evidence.py <真实且VERIFIED的v3-run-id>
```

Python 接口为 `main(run_id)`，返回证据字典；没有默认选样、批量按结果挑选或 `--resume`。只接受精确绑定到一项 v3 ledger `VERIFIED`、非 inherited 的新版 run。该输入仍需原 v3 `audit(run_id, export=False)` 重新通过，并核对归档 `final_access_des.tdr` 的 SHA 与审计结果一致。继承的 v2/D1 成果保留在原实验，不通过此入口重新包装成新v3求解。

入口内部持有原 `common.controller_lock()`，调用 `common.preflight()` 拒绝活动/不明 solver、其他控制器或未结 manifest。不要在调用者中重复取得同一锁。预检会按原规范写 `local_runtime/dram-see-v3/preflight/`；GUI本身只写以下新目录：

```text
experiments/dram-see-v3/figures/native/<run-id>/
local_runtime/dram-see-v3/gui-operations/<run-id>/
${remote_root}/dram-see-v3/gui/<run-id>/
```

本地输出或操作目录存在即拒绝，包括失败留下的半成品。远端目标目录同样采用独占 `mkdir`。不能删除目录或另起相同run来绕过保护；恢复先只读核对旧PID、日志、TDR、窗口与输出，不自动重新launch。该脚本从不调度solver、transport，不关闭任何窗口。

## 复用与依赖

实现沿用 D1 已验证的独立会话、Tcl 和逐操作日志机制，但不调用 v2/D1 的 main 或 operate。v3 audit/common通过唯一模块名加载，避免旧模块缓存混用；旧目录保持只读。

原截图 helper 为 `experiments/dram-see-v2/capture_guest_window.py`，固定 SHA-256：

```text
4fbdf4bd625bb3a9faf1ed0c73cf7b9cf9fbfb213d1f4814529ea8ac8ae7d280
```

脚本仅 `read_bytes()`，保持原字节上传到新的 v3 GUI 目录为 `capture.py`，禁止 import 此文件（其顶层直接执行参数解析与 X11 操作）。依赖客户机现有 `/usr/bin/python`、`gi`、Gdk/GdkX11 3.0、libX11、可读/proc以及已登录用户的X11会话。现有helper使用`GdkX11.X11Window.foreign_new_for_display`，避免历史旧Gdk.Window版本的失败；不安装或更改系统环境。

沿用已实测 Visual 路径 `/usr/synopsys/sentaurus/W-2024.09/bin/svisual`、参数 `-tcl -script view.tcl`、`DISPLAY=:0`、`XAUTHORITY="$HOME/.Xauthority"`。使用现有严格SSH连接，不输出连接配置/密钥，不调用会签出SDevice许可证的doctor。历史Visual日志显示Mesa、默认8线程，因此在solver空闲期间持锁完成取证，不把“不调用solver”当作并行无影响的保证。

## 原始来源与窗口保护

加载前与截图后都只读核对 `${remote_root}/runs/<run-id>/final_access_des.tdr` 的SHA，必须等于审计归档成员。原run目录不写入。Tcl唯一目标是4 ns信号支路最终TDR，显示 `Abs(ElectricField-V)`，V/cm，坐标µm；先隐藏默认字段，开启指定电场的log色带，导出1400×1000原生PNG。

新会话用nohup启动一次，保留launch PID。捕获前、中、后核对 `/proc/<pid>/stat` 启动时钟及cwd，要求对应v3新GUI目录且命令含svisual/view.tcl。实际窗口PID另行记录；当前helper只接受launch进程树的已映射窗口，拒绝无自有窗口时退回整个桌面。启动PID复用、cwd不同、连接中断或proof未完成均保留失败，不自动重启。

helper会把新自有窗口 `XRaiseWindow` 置顶，可能暂时遮挡旧窗口；它不会关闭或改写旧窗口内容。脚本不操作历史窗口ID，不清理用户会话，新GUI保持打开。历史PID/窗口ID不能用于当前控制权限判断。

每个远程操作保存command、stdout.bin、stderr、开始/结束时间、脚本/stdin SHA和退出码。超时保存已有输出，状态记为 `REQUIRES_READ_ONLY_RECONCILIATION`。只有exact proof包含run ID和TDR SHA、确有电场字段、原生PNG与截图的PNG结构/CRC/尺寸有效且所有依赖源码未变化，才写最终evidence。

## 输出与验收边界

成功路径输出：

- `final-field-native.png`：实际TDR在SVisual中的原生导出。
- `own-window.png`：新自有SVisual窗口的原始像素截图。
- `view.tcl`、`native-proof.txt`、`visual.log`、`own-pid.txt`。
- `evidence.json`：schema `dram-see-v3-native-field-evidence`，含run/tag、归档与TDR哈希、加载前后源哈希、参数、源码/helper依赖哈希、操作记录、PID启动身份、实际窗口ID、图像尺寸、Visual版本日志行及各输出文件哈希。
- runtime `completion.json`：状态 `CAPTURED_PENDING_VISUAL_REVIEW` 和 evidence SHA。

`visual_review_status` 明确保持待目视检查。主代理还须实际查看两张图片，核对图中run ID、4 ns、信号支路、色标变量、单位、图形，以及无无关隐私，再将结果链接入课程交付索引。若显示回退到掺杂、空图或错误窗口，保留原证据并报告失败；不能靠Tcl文字或PNG存在宣称目视通过。

这张图是 **4 ns 电场分布**，不是读出瞬态曲线，不替代粒子/对照读出指标、数值精度、参考零源验证或真实Workbench Run按钮证据。DATA PLOT仍由已有绘图模块独立生成和标注。

## 已做测试与未做项

命令：

```powershell
python -B local_runtime/dram-see-v3/gui-fixtures/test_gui.py
```

5项隔离fixture测试通过，退出0：完整mock取证来源/自有进程/原字节helper/PNG链；活动solver或无效ledger在连接前阻断；TDR不符、PID复用、ready连接失败和错误marker保留失败且拒绝再次launch；Tcl路径/进程ID/PNG损坏拒绝；超时日志完整保留。完整日志为`local_runtime/dram-see-v3/gui-fixtures/test-output.txt`。

测试中的所有连接、远程执行与审计均替换为mock，目录和合成PNG只在fixture临时目录，不写生产ledger或GUI成果；没有启动真实SSH/X11/SVisual。真实VM依赖、窗口cwd/进程身份、Visual许可/导出、图片内容和对正在运行系统的影响仍需主代理在实际空闲窗口执行后确认。
