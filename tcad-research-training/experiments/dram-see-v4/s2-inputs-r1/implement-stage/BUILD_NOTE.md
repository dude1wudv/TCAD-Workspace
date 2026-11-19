# S2 离线实现记录

| Rung | 内容 | 离线验收 | 状态 |
|---|---|---|---|
| F0 | 原模型提案→独立审查包骨架 | prepare.py skeleton，退出0，F0-skeleton | 完成，仅离线 |
| F1 | S2 CAD/掺杂/接触/网格及物理/DC/写读deck | 48项约束、两维各16000点独立Scheme材料检查、58点/维掺杂式；私有卡SHA冻结 | 完成，仅离线 |
| F2 | α变LET/Si域积分/全帧提取与判定适配 | 35项算术/拒绝检查，退出0；独立Si体积和1584 mask点一致 | 完成，仅离线 |
| F3 | 首4角色打包、身份/门/成本绑定 | packages-r2，100文件，prepare/verify退出0 | 完成，未执行发布 |
| F4 | 独立审查、假设扫查、交接 | 原validation_worker，14项测试通过；same-family/provisional扫查；主验收见当前report | 完成，仅离线 |

## Run record

不调用SDE/snmesh/SDevice/SVisual/Geant4。用户禁止提交Git，技能的自动commit步骤不适用。

本轮记录根为`local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/`。F0先验证输入快照链，再并行推进边界清晰的CAD与α模块，主线实现物理/deck/packager；唯一调度者没有派发原生任务。F1/F2交权后冻结代码，验证代理只写测试/日志。

独立验证的命令与完整结果见`validation/review.json`、`validation/review.md`；最小命令为现有Python执行`-B -m unittest discover -s experiments/dram-see-v4/s2-inputs-r1/tests -p test_s2_inputs.py -v`。合成曲线只用于单位/失败路径，不是TCAD数据。

保留的问题与修正：CAD尾部公式改为合同字面的`1-w`后通过原容差；α的浮点表示等价比较改为1e−15 µm表示容差，科学门未变；r1两个A0漏归档3份非激活源审计资料，r2补齐并定向复验。A018由独立扫查发现求解控制漏记后补登记，不声称事前登记。原失败/旧包未删除。

包manifest SHA：`165473aacaada00f613885ced15b0d645205740cdf5c0c0fcffb50d82c18a8f3`。该SHA代表离线输入完整性，不代表native语法、器件功能或源资格。

## Deferred

执行预算/发布、实际网格、原生电学及源资格、质子新源接口、训练。

## Blockers

本轮没有原生执行授权；这不阻断离线输入准备。原PMI/R12状态不改变。
