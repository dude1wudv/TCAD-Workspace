# 自主推进功能的实现边界

2026-11-16 按用户指令实现服务器Codex自主推进v2。实现时科研计划为revision 0.2，`execution_authorized: false`；当时授权是实现及必要验证，暂不启动仿真。

实现入口：[控制器与任务接口](../../automation/server-codex/README.md)。证据及部署状态：[验证记录](../../automation/server-codex/VALIDATION.md)。

服务器已安装 release `20261116T104237Z`，回读确认为 disabled v2、并发上限9、
服务 inactive/disabled。最终Linux离线100项及Windows部署专项22项通过，
实际systemd单元校验通过。首次安装的单路径引号问题已修复并保留失败证据。
本轮没有启动自主服务、调用其真实模型API或新增仿真；实际九并发与科研验收另行执行。

- 原runner支持的0–8共享槽用于9个独立单核任务；监督按产物依赖补槽。
- Codex将目标转成冻结输入任务提案，并完成数据整理、训练和分析；轻量监督调用原run/status/collect，避免模型空转等待。
- 失败收集后以新目录、新输入和理由创建修复分支；局部失败不阻塞其它研究路线。
- 提交前持久化意图，断线/进程重启恢复原ID和原收集，未知提交不重投。
- 模型仅因事件、实质进展或失败退避到期唤醒；不把论文参数缺口、理论偏差或阶段未关闭变成全局门禁。

这些是软件执行能力，不是已获得DRAM辐射数据、训练完成的预测器或结题证据。结题仍按导师四项工作验证；DDR5/LPDDR5路线与数据域边界不因软件上线改变。

## 2026-11-16 后续：真实模型调用通过

上述“未调用真实模型API”描述开发部署阶段。后续已用服务器原Codex CLI及Magpie路由，以 `auto/gpt-6.1-sol`、`high` 完成隔离只读请求：4.736秒、退出0，随机nonce和算术回答正确，无工具调用。证据见 [result.json](../../../output/server-model-check-20261116/result.json)。

测试后记录为服务inactive、controller disabled，`simulation_submitted=false`。这验证模型联通，不代表自主长期运行或科研仿真已验收。后续研究计划已修订为r0.4的[质子宽能区与多参数实验](FIRST-BATCH-DESIGN.md)，未创建执行队列；本次计划修订没有重测API或更改服务状态。
