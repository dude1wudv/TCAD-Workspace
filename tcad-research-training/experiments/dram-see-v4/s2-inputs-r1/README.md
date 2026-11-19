# S2 离线输入审查包 r1

本目录落实r13.1的S2代表BCAT：CAD/掺杂/接触/网格、物理卡、DC、两bit实际写读和α源审计适配。**只准备与审查，原生调用0，执行授权0。** 这不是商业LPDDR5/6复现，也不是文献器件校准。

当前包位置由`local_runtime/dram-see-v4/s2-inputs-r1/current-preparation.txt`定位；该目录中的`review-package.txt`指向最终审查版本，`report.md`记录主验收。`preparation-state.json`是本轮编辑占用状态，不是替代旧active-entry的调度入口。

- [CAD与名义材料/接触审查](geometry-notes.md)
- [物理卡、DC和实际写读说明](physics-and-decks.md)
- [α独立积分与原生全帧适配](alpha-notes.md)
- [规格与假设账本](implement-stage/SPEC.md) · [假设](implement-stage/ASSUMPTIONS.md) · [实施记录](implement-stage/BUILD_NOTE.md)
- [r13当前计划与原门槛](../course-plan-r13/refine-logs/EXPERIMENT_PLAN.md) · [原预算提案](../course-plan-r13/budget.proposed.json)

| 角色 | 已准备输入 | 未来依赖 |
|---|---|---|
| B1-D2 | 2D中心截面CAD、物理卡、两个VDS的DC扫描 | 新预算/发布；原生结构、mesh与DC工程检查 |
| B1-D3 | 有STI/有限宽度的3D CAD、物理卡、DC扫描 | D2通过适用的工程门，资源准入；原生3D检查 |
| B1-A0-main-b0 | bit0实际写/保持/读出deck与字段审计合同 | D3同一实际mesh/hash；原生功能与KCL |
| B1-A0-main-b1 | bit1实际写/保持/读出deck与字段审计合同 | 同一D3 mesh；bit0失败先停止依赖角色并查因 |

每包含`input-manifest.json`、`role-contract.json`、`project.review.json`和关闭的`resource-policy.json`，不含`project.json`或虚构TDR。A0的`mesh-import.required.json`明确生产者，实际mesh SHA保持空值。私有安装参数卡只在被忽略的runtime包内。`alpha-audit/`是独立源审查资料，没有增加第5个计算角色。

离线复现使用既有Python；输出必须是新runtime目录，保留所有早期版本和失败记录：

```powershell
& .\local_runtime\vdmos-analysis-venv\Scripts\python.exe -B .\experiments\dram-see-v4\s2-inputs-r1\prepare.py prepare --output <新的S2-runtime目录> --private-physics <本轮private-physics目录>
& .\local_runtime\vdmos-analysis-venv\Scripts\python.exe -B .\experiments\dram-see-v4\s2-inputs-r1\prepare.py verify --output <审查包目录>
```

这两条命令没有网络或求解入口。原生执行仍只能使用既有runner与唯一调度者，严格SSH、共享锁、串行单线程单核。

首切片仍只提案4个SDevice、2次mesh构建、2次原生字段提取、4 CPU小时和新增原档8 GiB上限；没有获批，也没有占用或重置旧预算。实际节点、峰值内存、TDR帧数/大小、墙时/CPU时仍待测。资源记录模板在当前runtime中，未测值保持null。原8/20/4/160 GiB门不变。

下一步先处理本包具体审查问题，再以确切角色、输入SHA、资源预测和对应预算形成独立执行发布。用户本轮要求暂不原生计算，因此不发起执行或重复索要执行许可。main的两份A0不能替代后续h/2、dt/2资格，也不能直接铺开α、质子或数据矩阵。

旧PMI实际BE未更新、R12未编译/发布的阻断原样保留；它们不阻断本离线α支线。新几何不沿用旧事件作统计样本。现有`dram-see-v4`半小时任务恢复ACTIVE，仍每30分钟、原目标chat，无第二任务；仅继续授权的离线工作，IN_PROGRESS时不并发写本输入目录。
