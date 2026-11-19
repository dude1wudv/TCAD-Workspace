# r5 综合审计与 r4 复用桥

实现契约见 [implementation-contract.md](../interface-completion-r1/implementation-contract.md)。本模块只读已有求解与后处理证据，不连接 SSH、不运行求解器、不修改旧记录。

## API

- `audit_interface.load(run, project=None, field_audit=None)` 返回 `summary/parameters/source/proof/curves`；有源且场证据完整时返回 `native_curves`。r4 原档自动走严格复用桥。
- `write(output, bundle)` 在新的 r5 runtime 子目录写 `audit.json`（或 `comparison.json`）及完整电路、器件、原始曲线和原生 ROI 曲线；拒绝覆盖已有目录。
- `matched_control(signal, control)` 要求双方单项审计通过、control 为 A0、存储状态和规范化物理合同相同、实际 `cell_msh.tdr` 哈希相同。返回匹配证据；不满足时抛 `ValueError`。
- `compare(a, b, ca, cb, mode='equivalent', output=None)` 接收四个已审计 bundle，分别扣除各自匹配 A0。`equivalent` 限 A1/A4 和 A5/A7；`segment` 按 main A1→A8S2/A8S4；`refinement` 按同案例 main→time/fine。
- `reuse_bridge.load(run, reference_project=None, field_audit=None)` 只接受 source contract 的两条 `reuse_roles`。`reference_project` 若传入，必须是登记的**原 r4 project**；新 main 物理条件通过冻结 r5 renderer 独立生成并核对。

## 证据链

1. 复用冻结旧解析器检查输入／结果归档、真实退出码、原始串行执行、所有原始曲线、完整 0–4 ns 时域、端口电流、电路 KCL 和电荷守恒。
2. r5 的全部物理输入按冻结 builder、source contract、完整 device deck、HeavyIon 参数、geometry 字节、matching contract 和离线源积分逐项检查。候选目录存在不等于求解通过。
3. 总生成量采用原生无窗口积分，按 BE 接受区间右矩形积分；时间矩使用区间中点。A3 的目标是预计算**域内约 0.5 fC**，不是声明总量 1 fC；A6 的预期时刻按各轨迹**域内电荷加权**，不是第一条轨迹时刻。
4. 有源角色必须绑定 full-mode `source-field-audit-r2` 报告及其 auditor／contract 哈希、原 run／manifest／archive／mesh。继续检查原生提取 receipt、真实退出码、operation／archive、原始 measurement CSV 和每帧 TDR 哈希、native Writing 与精确 PLT 接受区间。新场报告的 frames.csv 也核对哈希。
5. ROI 比较曲线从绑定的原始 `field-measurements.csv` 读取，不使用已知失效的 Window CurrentPlot，不由源坐标或理论分数补测量。窗口起点真实测量帧保留用于曲线比较，但不重复计入生成量积分。各完整有效时间网格之间可按原比较器插值，缺失接受帧仍直接失败。

`load` 通过只表示单次源／曲线／守恒证据通过。有源角色仍需匹配 A0 与适用等价／分段／数值比较；主调度者据此生成最终 role gate。所有报告保留 `overall_source_interface_passed=false`，不自行宣布整套二维验收或器件校准完成。

## 阈值和比较

不新增、放宽或拟合阈值，沿用冻结 r2/r4 数值：总源量／总波形 5%，ROI 分数绝对误差 0.05，空间质心 0.01 µm，时间质心 0.5 ps。等价源生成量差不超过 1e-4 fC、原生 ROI 波形相对误差不超过 1e-3；电压绝对差不超过 1e-5 V，电流按既有绝对 1e-12 A 加相对 1e-3 判定。

分段和 time/fine 比较：生成电荷差以 `a` 的 main 原生生成量为分母，不超过 2%；SN／BL 全时域扰动差不超过 `max(1 mV, 5% × 两条扰动曲线的共同峰值)`。每条扰动各自减去同 bit／同数值条件 A0。time 只允许 pulse step 与显示标签改变且实际网格相同；fine 只允许网格尺度、geometry 哈希与显示标签改变且实际网格不同。

A1/A4 使用原 9 个 ROI；A5/A7 还比较已批准的 SourceLeft／SourceRight。额外 ROI 不给其他案例增加新门槛。

## 旧 r4 复用限制

桥只接受合同中登记的原 A0/A1 bit1 mesh run、原 audit、原 A1 full field audit 和原数值 comparison 哈希。重新只读审计必须结构化复现原 audit。旧 comparison 的 coarse 空间失败及未完成全局收敛结论不被改写。

旧参数仍保存 `variant='mesh'`，新摘要显式记录 `canonical_variant='main'`。原 matching contract 仅映射该标签，几何内容、实际网格标识、源、HeavyIon 参数、单位、电路、初态、偏压与时序不变。r5 新增的 `kernel.time_sigma_equals_s_hi=true` 仅作为明确登记的文档补充，剔除此唯一字段后两版核定义必须完全一致；两版完整物理 deck 也必须一致。

首轮 A0 桥检查因这个新增文档字段失败，记录保留于 `audit-dev/reuse-a0-r1`；随后明确处理该字段后，`reuse-a0-r2` 和 `reuse-a1-r1` 通过。它们属于旧归档复用核验，不增加 TCAD 次数。

## CLI

```powershell
python experiments/dram-see-v4/source-interface-r5/audit_interface.py audit <run-dir> --project <project-dir> --field-audit <full-field-audit.json> --output <new-r5-runtime-dir>
python experiments/dram-see-v4/source-interface-r5/audit_interface.py compare --registry <evidence-registry.json> --a signalA --b signalB --ca controlA --cb controlB --mode equivalent --output <new-r5-runtime-dir>
```

Registry 格式为 `{"runs": {"signalA": {"run": "...", "project": "...", "field_audit": "...", "field_audit_sha256": "...", "role": ["A4",1,"main"]}}}`；A0 可省略场报告。角色必须与实际输入一致，r4 登记角色使用规范化 main 标签。运行入口需要依赖冻结完成；此处命令不构成自动调度授权。

## 验证范围

`test_audit_interface.py` 用人工曲线验证 A3 截断、A6 加权时间、负源、A0 缺测处理、错误控制、参数冲突、未登记复用、原生 ROI 差异、segment/time/fine 门槛、场报告身份／模式／代码／receipt 篡改和旧证据精确匹配。人工曲线只属于单元测试，永远不当作 TCAD 结果。

另外以冻结的新 A4 离线输入检查 archive 合同与篡改拒绝，并对登记旧 r4 A0/A1 原档执行真实只读桥接。新 r5 全流程仍需主调度者用真实完成的求解及全帧原生场报告验证。本模块没有启动求解器或后处理器。
