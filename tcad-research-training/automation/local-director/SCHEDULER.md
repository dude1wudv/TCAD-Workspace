# Windows 计划任务（Phase 0）

在本目录用 PowerShell 预览；把示例路径换成本机真实的 Python 解释器和配置文件的绝对路径。配置文件保留在本机。

```powershell
.\register_campaign_tasks.ps1 -PythonPath 'C:\Tools\Python\python.exe' -ConfigPath 'C:\TCAD\private\config.json'
```

自动化可用独立 PowerShell 进程执行无凭据预检。它检查文件路径，只运行 `python -B watchdog.py --help`，并在内存中检查任务 XML；不传入配置内容、不执行守护或脉冲动作，也不注册或触发任务。

```powershell
pwsh -NoProfile -File .\register_campaign_tasks.ps1 -PythonPath 'C:\Tools\Python\python.exe' -ConfigPath 'C:\TCAD\private\config.json' -Preflight
$LASTEXITCODE
```

预检通过时返回 `TaskXml=PASS`、`RegistrationAttempted=False`，PowerShell 进程退出码为 `0`；失败时退出码非零。预检确认 Python 帮助退出码为 `0`，且包含 `--config`、`--keepalive`、`--tick` 和 `--scheduled-pulse`；同时核对两个任务的触发器、周期、固定动作、工作目录和运行账户。输出仅含固定任务名、检查状态等摘要，不显示动作路径、用户 SID 或 Python 输出。

| 任务 | 触发 | Python 参数（在 `--config` 之后） |
|---|---|---|
| `TCAD-Codex-Watchdog-Keepalive` | 开机、当前用户登录、每 10 分钟 | `--keepalive` |
| `TCAD-Codex-Progress-Pulse` | 每 2 小时 | `--tick --scheduled-pulse` |

普通预览只在内存里构建定义和 XML，不启动 Python。正式注册前先通过预检，并另行验证 Python 的锁行为。

正式注册时，用**预定运行任务的同一账户**以管理员身份打开 PowerShell，在预览命令后加 `-Apply`。Windows 要求管理员权限才能注册开机触发器；脚本不提权。两个任务以该账户的最低权限运行，只使用已有的交互登录令牌。任务注册不需要提供或保存口令；打开管理员窗口时的 UAC 验证仍由 Windows 决定。重启后尚未登录时任务无法运行，登录触发器会补起看门狗。若要求登录前运行，需另行确定非交互账户及其权限、凭据和访问范围，本工具不配置。

`-Apply` 按固定名称创建或更新两个启用的任务，重复执行不会新增副本；不会主动调用启动命令。两个更新分别提交，出现失败时保留已成功的更新。脚本不修改系统电源计划、不唤醒电脑，保留 Windows 任务默认的电池条件。相同任务正在运行时跳过重叠实例，守护进程的单实例仍由 Python 负责。

脚本不读取配置内容，不导出任务 XML 或收集 Python 输出。Windows 会保存任务动作中的绝对路径，启用任务审计时可能记录任务定义；路径和参数里不要放令牌、口令等秘密，也不要共享导出的任务定义。Python 自身的日志由 Python 入口负责脱敏。

## 进程与限制核对

本轮验证环境为 PowerShell 7.6.9、非管理员。`Schedule.Service` 可在内存中建立任务定义，XML 核对确认 `InteractiveToken`、`LeastPrivilege`、`IgnoreNew` 和 `WakeToRun=false`。脚本的权限检查在接触注册 API 前拦截非管理员；只读查询中两个目标任务前后均不存在。本轮没有真实任务启动、运行退出码或 `LastTaskResult` 证据。

主代理完成真实注册后，可用以下只读命令核对任务定义和最近一次结果，不会主动启动任务。

```powershell
$names = 'TCAD-Codex-Watchdog-Keepalive', 'TCAD-Codex-Progress-Pulse'
Get-ScheduledTask -TaskPath '\' |
  Where-Object TaskName -in $names |
  Get-ScheduledTaskInfo |
  Select-Object TaskName, LastRunTime, LastTaskResult, NumberOfMissedRuns
```

本轮观察到帮助进程退出码为 `0`；参数解析拒绝独立的 `--scheduled-pulse` 和 `--daemon --scheduled-pulse`，退出码均为 `2`。独立 PowerShell 预检只运行帮助检查。真实验收时，核对 `--keepalive` 动作快速退出、同一配置只保留一个守护 PID，且已有守护时 PID 不变；核对 `--tick --scheduled-pulse` 退出码和脱敏处理结果。任务的 `LastTaskResult=0` 表示进程返回成功，后台守护仍在运行或脉冲已处理需分别核对。

## 给看门狗实现的建议

当前 daemon 长期持有 `watchdog.lock`，定时脉冲也尝试同一把锁；若锁仍被占用，脉冲会退出 `1`。建议把 `watchdog.lock` 留给 daemon 和 keepalive 的单实例控制；用现有 `state_lock` 串行化两种 tick 的状态读取、修改和派发，并在锁内去重当期脉冲。锁竞争超时要返回可辨别、可重试的结果；成功应对应实际处理或确认已处理。并发验收至少覆盖：守护 PID 不变、同一期脉冲只处理一次、锁超时后可重试。任务 XML 的 `IgnoreNew` 只挡同名任务重叠。
