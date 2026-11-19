# 原 runner 几何接线离线集成审查包

Target: 将已完成的几何生产者接入原 scripts/tcad.py 的归档冻结前步骤；本轮仅生成未应用、关闭执行的审查候选。ASK=never, effort=balanced, assurance=draft。

Inputs: 原 runner、capture/r3、S2 packages-r2、geometry candidate-r1、原 budget/active-entry/attempts。旧验收复用。

Outputs: 新 runtime 下的原 runner 合成补丁、仅新增几何补丁、候选源码、四角色 project.review.json、context/退出映射 helper、未授权成本分配提案、检查与主验收。没有 project.json、有效原生授权、预约或实际数据。

Success: 本机 prepare.py 生成闭合候选；新增隔离接线/拒绝测试通过。只测新增行为，不重跑旧29项/15项，不执行原生或SSH。

Base commit: eb49585b6d1c7c833fa5c17bc83393612232c379。原有工作区脏状态保留；capture、geometry与runner的实际文件hash也作为输入。

Scope cuts: 不应用补丁、不发布执行、不新增runner/operation或探针run、不重算科学容差/计划、不训练、不提交Git。原生语法/实际归档正常链未验收，PMI/R12不变。
