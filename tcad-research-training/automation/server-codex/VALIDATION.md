# 自主推进 v2 验证记录

日期：2026-11-16。范围：实现与必要验证；用户明确要求暂不启动仿真。

本次对应 [研究计划 revision 0.2](../../plans/dram-se-ddr5-lpddr5/PLAN.md)，保持
`execution_authorized: false`。自主服务的代码能力不等于已生成科研数据、预测器已训练完成或课题已验收。

## 已验证的行为

| 项目 | 检查结果与边界 |
|---|---|
| 九任务并发 | 同一原槽池 0–8；10 个就绪提案只提交 9 个，第 10 个等待，原任务收集释放槽后补入。 |
| 失败修复 | 原失败先收集；新 ID、新目录、不同输入和修复理由形成谱系。默认每谱系 2 次修复，独立任务继续。该检查验证机制，未证明真实模型的修复成功率。 |
| 断线与重启 | 提交前保存意图；未知启动、坏模型报告、进程重建后沿原 ID 查询和收集，不重投。 |
| 调度与模型解耦 | 模型退避期间仍能收集原任务和补充已经准备好的任务；无实质变化不重复调用模型。 |
| 局部问题 | 科学偏差或任务失败不要求整包阶段重新验门禁；未知原身份或未知提交保留该项占位。 |
| 暂停 | 批次中途 pause/disarm 后不再提交后续任务；原远端任务保留。 |
| 输入与结果 | 原输入、run ID、连接、账本、归档 SHA、共享锁和原收集回执保留。 |
| 禁用行为 | disabled serve 不启动模型或 runner；status/check/plan 只读本地状态。 |
| 升级 | 旧策略精确备份后迁到 disabled v2；保留实际 workspace/state/runner/Magpie 来源，拒覆盖已改服务器源码。 |

## 测试方法

最终 Linux 完整验证：**100 项全部通过，无跳过**，1.417 秒；
包含实际跨进程文件锁与权限元数据检查。
最终 Windows 部署专项：**22 项全部通过**，1.441 秒。
此前 Windows 完整验证为 96 项（95 项通过、1 项 POSIX 检查跳过），
Linux 核心验证为 78 项全部通过；后续新增部署检查已包含在最终 100 项中。

```powershell
python -B -m unittest discover -s automation/server-codex -p 'test_*.py' -v
```

Linux 测试使用本机隔离 Docker 容器：

- 镜像 `tcad-autonomy-offline-test:20261116`，仅用于本轮离线验证。
- `--network none --read-only --memory 512m --cpus 1`。
- 源码只读挂载；测试临时状态写入容器 `/tmp`。
- 组合测试使用真实 controller 与 Runtime；模型进程与原 runner 的外部调用由 fixture 替代。
- 部署单元测试使用临时文件和 mock 系统命令，不启动 systemd 服务。
- 旧默认任务说明精确匹配后才备份更新；自定义任务内容保留，
  不用关键词猜测其含义或覆盖它。

因此，“9 个运行”是调度契约验证，不是实际 TCAD/Geant4 的九并发性能验收。
本轮没有调用真实模型 API、启动求解器、改 VM 或提交新的科学任务。

## 升级前的服务器检查

通过 `管理入口` 只读检查：

- `tcad-autonomy.service` 为 `inactive`、`disabled`。
- 旧版本为 `<AUTONOMY_INSTALL_DIR>/releases/20261116T055340Z`，策略为 disabled v1。
- 已归属源码快照与原 manifest 一致，没有检测到源码漂移。
- `<SERVER_CONFIG_DIR>/task.md` 与旧 release 的默认模板字节完全一致。
- 该部署工作区没有原作业账本；这一结果不表示其它工作区或虚拟机没有正在执行的任务。

## 服务器禁用升级结果

2026-11-16 10:44:26 UTC 完成回读：

| 对象 | 实际状态 |
|---|---|
| 当前 release | `<AUTONOMY_INSTALL_DIR>/releases/20261116T104237Z` |
| 策略 | `tcad-server-codex-v2`，`enabled=false`，`max_parallel_jobs=9` |
| 服务 | `inactive`、`disabled` |
| 计划与提案 | `execution_authorized: false`；无正式 work-items 队列；示例为空 |
| 执行交接 | `readiness=null`；因此 status 正确报告 `ready_to_start=false` |
| 原配置来源 | workspace/state/runner/Magpie 配置来源均保留 |
| 源码 | 1,090 个 manifest 文件全部匹配；原 TCAD/Geant4 runner 与本轮开发前 SHA 一致 |
| 旧策略备份 | `<SERVER_CONFIG_DIR>/policy.json.before-v2-f533b78a` |
| 旧默认任务备份 | `<SERVER_CONFIG_DIR>/task.md.v1-default-20261116T103304Z.bak`；新文件保留原 owner/group/0640 权限 |
| 实际 systemd 校验 | 退出码 0；仅有其它既存 `tcad-mihomo.service` 的 MemoryLimit 弃用提示，未修改该服务 |

首次安装在实际 systemd 校验处中止：`WorkingDirectory` 和
`ConditionPathExists` 的单路径值被错误套用了命令参数引号。
已修正安装器及回归断言；修正后的完整离线测试、安装前实际 unit 校验、
安装后的实际 unit 校验均通过。首次失败日志和中间版本保留，没有启动服务补测。

修复包复用已上传源码归档，只传递安装器及部署测试的四个副本变更；
重建前后逐文件校验目标 manifest，未重新打包另一线程的动态成果。
最终包 SHA256：
`83c606166519628c88a69289abd44a6fb3d5283d09310c9eddbdb1f7beaee6f2`。

安装器为首次 owned snapshot 创建来源提交
`6fb64d1a3ff4dad24768c40e8c3a6092cb78a529`；
后续修复保留该 HEAD 与 index，安装器、部署测试和 snapshot marker 的修改由新 manifest 记录，
因此不宣称工作树干净。既有 `local_runtime/` 中的历史 runner 备份保留且不入源码提交。

## 证据与未执行项

本地完整日志、源码摘要和部署记录位于
`E:\TCAD-Workspace\output\server-autonomy-v2-20261116-031001`。
最终测试记录为 `linux-final-verified-tests.log`、
`windows-postfix-deployment-tests.log`。
部署以 `fixed-install-result.json`、`remote-final-verification.json` 为准；
`unit-first-verification.log` 保留首次实际安装错误。
初次测试与中间回归失败记录也保留，未覆盖成通过结果。
源码包内的本文冻结于安装前；本地本文补记了安装后的真实状态。

未执行：真实 Codex/Magpie 联通烟测、服务启动后的长期运行、
真实九并发求解与性能测试、真实失败的自动修复成功率评估、研究数据及预测模型验收。
下一次用户授权启动时才进行实际原作业交接与执行身份绑定；本次不填写授权为真的 readiness。

## 2026-11-16 后续模型联通验证

前文未执行项描述开发部署阶段。之后已在服务器以隔离 `CODEX_HOME`、
空工作目录和只读/ephemeral方式，调用现有Codex CLI及Magpie路由。
请求配置为 `auto/gpt-6.1-sol`、`reasoning_effort=high`；
4.736秒返回，exit code 0，无超时，随机nonce与137+286=423均正确。
记录中无工具调用，服务测试后仍为inactive，controller enabled=false，
simulation_submitted=false。

本地结果：[模型调用result.json](../../../output/server-model-check-20261116/result.json)；
远端原结果：`<SERVER_STATE_DIR>/model-checks/20261116T105408Z-ccbd10/result.json`。
该记录证明配置请求和成功响应，不替代供应商内部模型身份认证、服务长期运行、
失败自主修复成功率或新研究数据的验证。本次未启动自主服务或仿真。
