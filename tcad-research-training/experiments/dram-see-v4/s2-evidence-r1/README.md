# S2 原始证据接口与未授权发布候选

本阶段接续[S2离线四角色输入包](../s2-inputs-r1/README.md)的F5–F7。没有原生、SSH、编译、提取或训练调用；没有修改原runner、原S2实现、冻结packages-r2或旧预算。

F5–F7已完成离线交付，最终独立套件29/29通过、exit 0。当前采集候选为`capture/r3`，首4角色发布候选为`release-candidate-r2`，均未应用或授权；r1候选因接口SHA更新已过时，保留为历史。原生几何/电路/α资格仍未验证。

本轮runtime由`local_runtime/dram-see-v4/s2-evidence-r1/current-preparation.txt`定位。最终状态与独立验证见该目录的`report.md`、`root-acceptance.json`和`validation/`；本目录提供实现，不是生产执行入口。

| 文件 | 作用 | 边界 |
|---|---|---|
| [evidence.py](evidence.py) | 只读归档收集observed/inferred/unavailable事实及来源SHA | 不启动进程/网络，不解包、不写native receipt |
| [audit.py](audit.py) | 检查真实观测、原授权/发布/几何绑定，再复用冻结S2全帧与数值门 | 整体native资格始终另需G1/配对/KCL/细化；未运行真实S2 |
| [capture_patch.py](capture_patch.py) | 对既有runner/operation生成未应用的采集补丁候选 | 不改源文件、不部署第二runner、不运行候选 |
| [release_candidate.py](release_candidate.py) | 生成首4角色明确关闭执行的候选和资源未知表 | 不生成project.json，不占用/转移预算，不填造实际mesh |
| [tests/fixtures.py](tests/fixtures.py) | 构造隔离synthetic归档供完整解析测试 | 公共native入口必须拒绝；不是求解/提取结果 |

接口取舍先登记于[假设账本](implement-stage/ASSUMPTIONS.md)。[兼容表](compatibility.md)列出直接证据和缺口；[采集候选说明](capture-notes.md)记录待原生验证的观察方法。

原runner没有独立持久化SDevice退出码/收集退出码，日志中的CPU mask属于父shell；旧提取器affinity.txt则是Threads/Cpus_allowed_list两行。收集器保留这些真实含义，不从COLLECTED/set-e/父shell mask补造实测0或单核收据。新原生入口要求真正native进程观察、版本/线程、逐工具/SSH/归档真实退出、原始锁观察、实际mesh与几何审计报告；任何缺失均拒绝。

已取得的旧归档仅用于格式调查，没有迁移其事件、样本或物理结论。新数学源、材料掩膜与全部数值门保持S2原合同；合成正常路径通过只表明软件解析路径可达，不表明原生工具或新器件可用。

执行前仍须：审批并单独应用采集补丁、冻结实际输入与接口SHA、明确授权及独立预算预约、重新核对owner/进程/共享锁/严格SSH和资源。F7候选保留approved=false/execution_enabled=false，首切片4 SDevice/2mesh/2提取/4CPU小时/新增8GiB上限只是原提案。实际节点/峰值内存/帧数/算时留null；原8/20/4/160GiB门不变。

本阶段有限离线任务已完成，半小时任务在本轮收尾通知一次待授权状态；此后无新变化静默，不自行提交、扩大矩阵或重发未知任务。当前用户仍明确暂不原生计算，不反复请求许可。未来是否执行还需完成报告列出的原生前置，不能直接改名启动。

后续新增：[几何测量生产者离线候选](geometry-producer-r1/README.md)已完成，15项新检查及双维Tcl mock通过；原F5–F7源码和29项验收保持，真实原生仍未发布。最新报告由`local_runtime/dram-see-v4/s2-geometry-r1/current-preparation.txt`定位。

当前最新：[原runner归档前几何接线离线审查包](runner-integration-r1/README.md)的candidate-r2已完成，新增9项检查有最终通过证据，旧29项/15项不重跑。首切片原“2提取”明确是A0字段提取，另有D2/D3几何提取2次，合计4次SVisual提案；批准/预约/消耗仍0，旧预算原档不改。报告入口为`local_runtime/dram-see-v4/s2-runner-integration-r1/current-preparation.txt`；采集与接线补丁未应用，首4执行未发布。


## 首四角色离线发布合同当前入口

首4角色离线发布合同审查包已完成：原owner/runner、integration candidate-r2、四个预定run ID、已知输入、独立S2预算和比较/资源策略已绑定。新增7项合同检查通过，同家族审查provisional；原29/15/Tcl/9项复用。用户本轮已允许调整细节、应用补丁及原生求解/编译/提取/训练，授权原文已入包；具体预算/策略/owner发布缺件保持未批准，未应用补丁、未执行原生。见[合同入口](release-contract-r1/README.md)与[最新报告](../../../local_runtime/dram-see-v4/s2-release-contract-r1/20261017T033504Z/report.md)。下一项具体交付是首D2发布证据页：具体预算与比较策略批准、有依据的初始资源预测、原owner现场准入及应用后指纹，再冻结D2可执行输入。A0最终输入等待同一D3原档验收；两次字段提取使用原operation独立label，不是A0项目内的步骤。用户行动许可已收到，不重复索要；本次离线合同收尾后无新增指令或实质证据静默。
