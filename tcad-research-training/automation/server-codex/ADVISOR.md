# Sol 的原生 Astra 顾问

Sol high 继续负责研究、修改和验证；`astra_advisor` 固定
`auto/gpt-6-astra`、`high`，通过同一个 Magpie provider 请求。
不改变主模型、Magpie路由组、科学队列、原runner或共享九槽。

## 实际使用

服务器 Codex 0.169.0 已实测支持以下原生流程：

1. Sol调用 `spawn_agent`，指定 `agent_type="astra_advisor"`、
   `fork_turns="none"`，提交精简问题包。
2. 接收原生 `task_name`，例如 `/root/issue_name`；同时底层有独立会话UUID。
3. 顾问计算期间处理独立工作。用 `wait_agent` 接收完成通知，不短间隔轮询。
4. 同一问题续问用 `followup_task(target=原task_name)`。
   `send_message`仅投递消息，不唤醒已空闲代理。
5. Sol记录采用决定、实现和实际验证结果。Astra的答复不能替代物理验证。

旧版工具可返回 `agent_id` 并提供 `send_input`、`wait`、`resume_agent`；
使用本轮实际schema，不假设各版本名称一致。

## 自主性与费用

复杂建模、日志难以区分的故障、结果矛盾、关键方法权衡均可立即请教，
不用先失败几次，无分数门槛、固定会诊轮数或顾问审批。
一般先使用一个顾问会话；已有答复能解决就直接推进，有新证据再续问。
需要材料时先回答可解决部分，指出具体缺口，不把资料齐全设为交流门槛。
问题包包含目标、必要证据/来源/单位、已尝试方法和当前约束，避免整段历史。
咨询失败只影响该问题，可处理的其它任务继续。

顾问沿用父会话的provider和权限，角色文件禁用本版支持的shell、apps、
plugins、memory和权限申请能力；角色指令要求只提供建议、不递归派发。
不能把角色文件写成独立OS权限隔离。真实验证额外使用整个会话的read-only
沙箱、空工作区、禁用shell/apps/plugins，并限制在服务器管理CPU9–11。

## 持久化与恢复

Codex持久化原生会话。`advisor.py`从原生记录提取：

- 父/子UUID、task_name、角色、实际模型和effort；
- 最近答复、原生状态和usage；
- 原始rollout路径和本轮events文件SHA。

控制器私有状态目录的 `advisory-sessions.json`保留最近128项会话导航，
每轮另有完整本轮索引；旧轮和Codex原生日志不删除。该索引不替代科学账本。
正常轮结束、模型超时及控制器恢复未完成轮时均尝试提取。
索引写入失败不把成功咨询当作需要再次付费重试的模型失败。

`task_name`只对所属代理树有效。跨根会话先读取原答复；若本版提供原生恢复
工具，恢复原UUID。没有恢复工具时，只在确有新咨询需求时用精简证据接续，
注明旧UUID；不声称任意新根会话都能发送消息到旧task_name。
断线状态未知时先核对原日志，不能盲目新建同样问题。

## 保持原九槽监督

新版控制器在等待模型子进程期间按原poll间隔调用同一个Runtime：
先对账和收集，再通过原`can_submit`判断填槽。原owner、intent、锁和
原runner保持唯一。模型提示所见的观察仍作为事件基线，咨询期间完成的
任务会触发下一轮，不会被错误标记为已处理。

活动旧控制器不会热加载Python函数。因此无重启部署时：
私有CODEX_HOME中的独立角色和追加操作说明供下一次新Codex会话使用；
异步监督和索引代码在下一次正常启动控制服务后生效。
不为功能验收重启活动控制器、终止模型/求解器或另建监督进程。

## 验证入口

离线测试（无API、SSH或求解）：

```bash
python3 -B -m unittest discover -s automation/server-codex -p 'test_*.py' -v
```

真实验证脚本只有显式 `--live-model-check` 才会执行付费请求：

```bash
python3 -B verify_advisor.py --policy <SERVER_CONFIG_DIR>/policy.json \
  --output /var/lib/tcad-advisor-validation/<唯一新目录> --live-model-check
```

使用独立CODEX_HOME和空只读工作区，不调用控制器serve或原runner。
核验原生spawn/追问记录、子会话turn_context和实际答复，不只相信最终自述。
2026-11-16已完成一次Sol→Astra→同一顾问追问的真实验证，约75.5秒；
主路由 `auto/gpt-6.1-sol/high`，子路由 `auto/gpt-6-astra/high`。
人工零计数示例只验证交互链路，不是DRAM实验或预测模型的科学验证。
该次Magpie链路未严格遵循最终JSON schema的字段形状，因此顾问答复按原生
会话内容读取；控制器原有研究报告校验保持不变，不依赖顾问的JSON自述。
