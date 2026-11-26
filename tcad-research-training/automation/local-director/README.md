# Local Director

Windows 11、PowerShell 7、Python 3.13。核心包使用 Python 标准库。看门狗采集研究状态，按配额唤醒只读 Codex Supervisor，由 `director_ctl.py` 登记决策和派发本地 Codex Worker 工单。每次只运行一个 Codex 工单，队列可保存多个待办。

## 配置

在本目录复制 `config.example.json` 为 `config.json`，填写本机配置。`repo_root` 相对配置文件目录解析，`state_dir` 相对仓库解析。`remote_controller_cmd` 推荐使用 argv 数组，第一项填服务器上的 Python 可执行文件，随后填控制器路径及固定参数。默认时区为北京时间，Windows 缺少时区数据时使用 UTC+8。

运行数据放在 `state_dir`。其中有 `state.json`、`queue.json`、`orders/<id>/`、`briefings/`、`DASHBOARD.md` 和 `auto-director-public.json`。`notify` 将日报写入 `reports/daily-YYYYMMDD.md`，其他通知写入 `notifications/`。SEE Pulse 手机 App 读取服务器已发布的服务和自动化状态，在发现异常时发出 Android 通知。日报和手工通知的正文保存在本地。

例子在本目录执行，可用 `--config <path>` 指定其他配置。

```powershell
python preflight.py --offline
python preflight.py
python watchdog.py --tick --dry-run
python watchdog.py --tick --force-trigger REVIEW
python watchdog.py --daemon
```

`--tick --dry-run` 做只读采样并输出拟触发事件。正常 tick 保存简报、状态与收据，并按变化发布公开快照。每日最多使用 30 次 Codex，普通工单最多使用前 24 次，保留 6 次处理紧急运维、故障和阶段里程碑。

## 工单和决策

```powershell
python director_ctl.py status
python director_ctl.py dispatch --file order.json
python director_ctl.py accept --order task-1 --note "核对通过"
python director_ctl.py reject --order task-1 --feedback "补充验收命令的输出"
python director_ctl.py cancel --order task-1 --reason "工作目标已调整"
python director_ctl.py queue-add --file order.json
python director_ctl.py queue-list
python director_ctl.py queue-pop
python director_ctl.py log-decision --type strategy --title "调整推进顺序" --body-file decision.md
python director_ctl.py notify --level digest --subject "研究日报" --body-file digest.md
python director_ctl.py finish-turn --summary "本轮决策已登记" --next-wake-hint 600
```

工单字段见 `schemas.py`。`acceptance_checks` 每项填写一条实际执行的命令。填报的退出码与 Codex 命令事件一起核对。工单评审使用 `orders/<id>/receipt.json`，各次运行目录保存原事件流与验证记录。打回达到上限时登记熔断，触发告警和换策略事件。

验收可指定 `--commit-msg`。提交路径取自收据对应的工单差异，并在提交时复检。`--push-pr` 将配置的工作分支推送到 `origin`，已有 PR 随分支更新，新 PR 创建为草稿。`--force` 可在审阅后验收带失败项的收据，提交仍需通过文件安全检查。

## 服务器迁移和回滚

```powershell
python cutover_server_planner.py --dry-run
python cutover_server_planner.py --apply
python cutover_server_planner.py --rollback '<BACKUP_PATH>'
```

先查看 dry-run 列出的专用负责人单元、cron 项和阻塞原因。在原仿真任务收集完、资源池释放后的维护窗口执行切换。在线调度服务只有在无活动任务、无待派发工况且进程身份明确的情况下才会停后再启动。`--force` 只允许终止可归属到服务器负责人的进程。备份路径由 apply 输出，回滚使用该路径恢复保存过的配置。遇到断连，先重新运行 dry-run 核对实际状态与备份。

## 离线验收

从仓库根目录执行。

```powershell
python -m compileall tcad-research-training/automation/local-director
python -B -m unittest discover -s tcad-research-training/automation/local-director/tests -p "test_*.py" -v
```
