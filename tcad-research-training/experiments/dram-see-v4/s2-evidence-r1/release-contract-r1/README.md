# 首四角色离线发布合同审查包

本目录把原 runner 接线 `candidate-r2`、原 owner、四个预定 run ID、已知输入、独立 S2 预算和策略绑定为可接续的审查合同。当前产物由 `local_runtime/dram-see-v4/s2-release-contract-r1/current-preparation.txt` 定位。

```powershell
& .\local_runtime\vdmos-analysis-venv\Scripts\python.exe -X utf8 -B .\experiments\dram-see-v4\s2-evidence-r1\release-contract-r1\prepare.py --output <全新review目录> --authorization <本轮用户原文记录.json> --stamp <UTC批次标识>
```

生成器只写新审查文件，没有调度、批准、应用补丁或运行接口；不生成可执行 `project.json`。`contract.json` 给出四角色的身份和引用，`budget.review.json` 给出独立预算与预约请求，`missing-evidence.json` 给出发布缺件。

用户本轮已授权调整细节、应用补丁、原生求解、编译、提取或训练。原文完整保存在授权记录中；不能再把旧候选中的 `false` 当作当前用户尚未许可。具体预算批准、策略签发、owner 发布和现场准入仍分别需要对应证据，不能由一般行动授权补造。首四没有编译或训练角色，也未分配其费用。

原 owner 绑定 `nuclear-closure-r1/supervisor.py::ownership` 与既有 continuation/owner.lock，TCAD/字段提取仍分别使用原 `scripts/tcad.py` 和 `transport-probe/operation.py`。当前会话仅是合同编制者，实际持锁者和发布记录留待现场取得；旧 r10 active-entry 与旧账本不恢复、不挪用。

四个预定 run ID 现在固定，尚未提交。D2/D3 绑定准确 review 配置与既有冻结 payload；两个 A0 同时绑定同一 D3 producer ID。A0 的真实 mesh、原 manifest/tar、验收及最终执行输入哈希等待 D3 原档产生，保持空值。review 输入哈希不是未来执行输入哈希。

预算为 mesh 2、SDevice 4、几何 SVisual 2、字段 SVisual 2，共 4 次 SVisual，仍在 4 CPU 小时/8 GiB 提案内。四个角色执行请求与四个提取请求共 8 个唯一计划 ID；它们不是实际预约，批准/预约/消耗均为 0。两个字段提取分别绑定原 operation label；它们不在 A0 的 SDevice project steps 内，其实际 TDR 输入等各自 A0 原档验收后冻结。

比较数值、单核单线程、严格 SSH、原 owner/共享锁和资源门保持。首 D2 需要有依据的初始资源预测与现场准入，不要求它未来自己的真实 mesh；D3 的实际 mesh 只阻塞依赖它的 A0。所有未批准策略保持关闭。

旧29项、几何15项、Tcl mock和接线9项检查直接复用；新增检查只针对本包的身份、引用、授权与未批准状态、预算/依赖和拒绝路径。同家族审查仅 provisional，不是原生或科学验收。原 PMI 实际 BE 未更新，R12 未编译/发布。

[规格](implement-stage/SPEC.md) · [事前决定](implement-stage/ASSUMPTIONS.md) · [实施记录](implement-stage/BUILD_NOTE.md)
