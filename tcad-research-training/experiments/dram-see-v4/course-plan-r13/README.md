# 项目设计实施规划 r13.2

主任务仍是《AI辅助下的存储器单粒子效应评估》。先进 LPDDR5/6 相关 DRAM 选型是导师新增方向，论文潜力和面试展示是扩展价值，不替代课程功能与验收。

本次根据“梳理 DRAM SEE 协作沟通”中的人类澄清修正B4：**明确物理公式必须参与训练**，保留匹配的无约束对照与留出检验；不以降低拟合准确性为目标，也不预设必须做PINN。先用α数据验证一个低复杂度电荷平衡约束候选，避免在有限数据和预算下同时铺开两类粒子训练。详见[最新对齐与训练方案](evidence/physics-training-alignment.md)。

当前选定 Lee 等 2020 的常规非对称结 BCAT（Fig.2(c)），以公开垂直结构与掺杂依据配合逐项登记的工程假设建立代表单元。S1/S2/S3 是70/80/90 nm埋栅顶深，不是商业节点或有效沟道长。α首批为Si表面5 MeV；质子使用Geant4；不加中子初级分支、轨道谱或事件率。

- [实施规划与要求映射](refine-logs/EXPERIMENT_PLAN.md)
- [阶段与准入状态](refine-logs/EXPERIMENT_TRACKER.md)
- [人类对齐来源](evidence/mentor-alignment-20261016.json) · [物理训练与协作安排](evidence/physics-training-alignment.md)
- [选型来源及证据边界](sources.md)
- [器件原文与53项参数证据](evidence/device-evidence.md)
- [α原生源、ASTAR与18角色配对](evidence/alpha-source-design.md)
- [模型与假设合同提案](model-contract.proposed.json)
- [首批21个正式角色](b1-b2-run-plan.csv) · [预算提案](budget.proposed.json)
- [后续有限矩阵提案](finite-matrix.proposed.csv)

本版是实施规格与离线准备，**不是执行发布**。已取得出版者PDF/XML、NIST数值并完成[S2 CAD、物理卡、DC/实际写读deck及α审计适配](../s2-inputs-r1/README.md)，首4个无粒子角色已生成审查包。未构建原生网格、未完成新模型原生资格；完整B1+B2仍为21个正式SDevice角色+最多2个纠错提案，该预算提案获批额度为0。域敏感性、质子接口、数据与训练另列预算，不立即铺开矩阵。

F5–F7的[证据接口、隔离归档检查与四角色未授权候选](../s2-evidence-r1/README.md)已离线完成，独立29/29检查通过。B4训练首轮提案按3个中位数目标、4个无约束目标、4个物理候选目标保守记11个fit单位，仍受12 fit/10 CPU分钟总上限，该预算尚未批准；完整质子对照不能假称已在剩余额度内。预算文件、模型合同、矩阵和冻结输入均未修改。

旧核闭环、二维失败、全部预算与原档保留。原 `nuclear-closure-r1/active-entry.json` 仍为 READ_ONLY_HOLD。R12候选尚未编译/发布/运行；原PMI未修复。新几何不能沿用旧事件作统计样本，新模型、源接口、批次、训练分别满足合同/预算/授权/发布后才可提交。

中断收尾已完成：[收尾报告](../../../local_runtime/dram-see-v4/course-plan-r13/alignment-20261016T132417Z/report.md)保留原9文档检查与29项离线验收，清除的是已无实际编辑者的占用标记，未改冻结包或重跑套件。

首4角色离线发布合同审查包已完成：原owner/runner、integration candidate-r2、四个预定run ID、已知输入、独立S2预算和比较/资源策略已绑定。新增7项合同检查通过，同家族审查provisional；原29/15/Tcl/9项复用。用户本轮已允许调整细节、应用补丁及原生求解/编译/提取/训练，授权原文已入包；具体预算/策略/owner发布缺件保持未批准，未应用补丁、未执行原生。[最新报告](../../../local_runtime/dram-see-v4/s2-release-contract-r1/20261017T033504Z/report.md)与[合同实现](../s2-evidence-r1/release-contract-r1/README.md)记录4个预定run ID、8个独立计划请求和缺项，批准/预约/消耗0，几何2+字段2=4次SVisual提案，4CPU小时/8GiB不增。下一项具体交付是首D2发布证据页：具体预算与比较策略批准、有依据的初始资源预测、原owner现场准入及应用后指纹，再冻结D2可执行输入。A0最终输入等待同一D3原档验收；两次字段提取使用原operation独立label，不是A0项目内的步骤。用户行动许可已收到，不重复索要；本次离线合同收尾后无新增指令或实质证据静默。

执行顺序仍为无粒子→α→质子→有限数据/物理训练→作品；本轮一般行动许可已记录；每项原生/训练仍需对应合同、具体预算、策略、owner发布及现场准入，首4不分配训练/编译额度。同学先同步材料与进度，等基础/时间/兴趣反馈后再分工。唯一调度、串行、单核单线程与旧门不变。

用户明确授权旧任务不存在后重建，当前唯一`dram-see-v4`已ACTIVE/30分钟，绑定接续chat `01a144ee-5a13-76f1-a56b-f26ef88da9f3`；无实质变化静默。旧缺失/迁移失败的收尾报告保留为历史，无第二任务。
