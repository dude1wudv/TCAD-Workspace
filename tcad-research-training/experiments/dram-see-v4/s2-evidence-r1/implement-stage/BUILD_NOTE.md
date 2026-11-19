# F5–F7实施记录

| 阶段 | 产物 | 状态 |
|---|---|---|
| F0 | 读取实际归档→只读事实/缺口报告骨架 | 已完成，exit 0，F0-spine_smoke.json；旧归档只作格式证据 |
| F5 | 收集/审计接口与未应用采集补丁 | 离线交付完成，capture/r3；E010精确身份/独立准入接线经最终复验，补丁未应用 |
| F6 | 完整归档与拒绝路径的隔离单测、独立复验 | 最终29/29通过，exit 0；原生资格仍false，失败日志保留 |
| F7 | 首4角色未授权发布候选与具体剩余前置 | release-candidate-r2已独立复核，10文件；全部执行/授权开关关闭 |

本轮原生、SSH、训练、编译、提取调用均保持0。旧runner、S2源码、原档和预算不可修改。主Agent拥有核心collector/audit/候选和整合；子代理写入范围在任务契约内固定。

## 实际运行记录

- F0：本地Python只读原operation.json，exit 0，`F0-spine_smoke.json`。骨架不进入资格路径，保留为起步证据。
- F5：`evidence.py <原r10字段operation目录> --kind extraction`，exit 0，`existing-extractor-format.json`。原退出/版本/线程可读，native PID与锁观察缺失；不从完成状态补0。
- capture：generator构建r3、AST/不覆盖/源SHA拒绝检查exit 0，补丁未应用。原生运行语义未验证。
- F6：独立复核捕获`geometry checks=null`未返回结构化拒绝；修复显式JSON对象/映射检查。失败日志保留。随后22项核心检查exit 0；E010变更后最终29项检查通过，exit 0，耗时22.504s。
- F7：`release_candidate.py --package <frozen packages-r2> --capture <capture/r3> --output <release-candidate-r2>`，exit 0；清单SHA `c4298135787a0d5908713121ca19423e829f3a3b4cce5e46db14b0c860771539`。r1因接口SHA变化已过时，原样保留，不能用于发布。

最终套件命令：`local_runtime/vdmos-analysis-venv/Scripts/python.exe -B -m unittest discover -s experiments/dram-see-v4/s2-evidence-r1/tests -p test_evidence.py -v`。证据在本轮runtime的`validation/final-independent-suite-r3.txt`及`review.json`。中间测试布局、辅助读取和断言错误仅由worker修测试修复；真实JSON结构缺陷由主Agent修业务，原失败日志全部保留。

Git Bash仅对抽取的capture helper执行`-n`，exit 0、输出为空；未执行候选Bash。原generator AST/静态结果未因无相关变更而重复运行。假设扫查见`SILENT_ASSUMPTION_SWEEP.json`，same-family/provisional；离线确定性检查通过不等于科学验收。

最终报告与主验收：`local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/report.md`和`root-acceptance.json`。原40份账本/入口/S2源码、28份attempt清单、冻结100文件包保持；该核对不冒充新远端现场。

## 仍不属于本轮离线验收的项目

真实native launcher/PID采样、Bash实际运行、原生exit/归档异常链、几何测量生产者、实际mesh/资源、DC/写保持读/电路KCL/细化与α资格。任何原生执行仍需新合同、明确授权、独立预算预约与发布；不重置旧预算、不自动执行。
