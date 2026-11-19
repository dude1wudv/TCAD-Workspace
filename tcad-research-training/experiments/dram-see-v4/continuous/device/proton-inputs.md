# 真实质子事件的器件输入接口

先由主调度取得成功收集的真实 D3，以及 `continuous/proton/source_bundle.py` 从完整 Geant4 原事件形成的源包。`prepare_case.py` 只冻结一次输入，不启动求解器，不创建 runner 或 operation。缺原档、原事件失败、来源/几何/物理错配、固定版本依赖发生变化时均拒绝。

按同一事件、同一 bit 和数值分支先准备 A0，再准备 `SIGNAL` 或真实完整空事件的 `STRUCTURAL_ZERO`。A0 冻结原事件是为了使用完全相同的观察时窗；其 deck 没有活动源，也不要求源摘要或训练登记。信号要求事先生成的 `source-features.json` 与 `data-input.json`。资格/诊断登记不要求已有原生结果或有效训练行；正式数据集仅接受 `main` 数值分支。

一次受控请求示例（路径应替换为已有真实文件，示例本身不能作为原生证据）：

```json
{
  "schema": "dram-see-v4-controlled-device-request-r1",
  "kind": "transient",
  "dimension": 3,
  "gate_top_depth_nm": 80,
  "particle": "proton",
  "variant": "main",
  "stored_bit": 0,
  "source_case": "SIGNAL",
  "d3_source_run": "E:/TCAD-Workspace/tcad-research-training/local_runtime/runs/<collected-D3-run>",
  "proton_source_bundle": "E:/TCAD-Workspace/tcad-research-training/local_runtime/dram-see-v4/continuous/proton/<original-event-source-bundle>",
  "matched_a0_project": "E:/TCAD-Workspace/tcad-research-training/local_runtime/dram-see-v4/continuous/device/projects/<same-event-bit-variant-A0>",
  "source_features_file": "E:/TCAD-Workspace/tcad-research-training/local_runtime/dram-see-v4/continuous/proton/<original-source-features>/source-features.json",
  "registered_data_input": "E:/TCAD-Workspace/tcad-research-training/local_runtime/dram-see-v4/continuous/data/<registered-response>/data-input.json"
}
```

准备 A0 时把 `source_case` 改为 `A0`，去掉最后三个信号字段，保留实际源包和 D3 路径。空事件信号用 `STRUCTURAL_ZERO`；`variant` 可为 `main`、`mesh`、`time`，对应 A0 必须同分支。`mesh` 必须使用实际 h/2 D3，`time` 使用主 D3 并将所有瞬态最大步长减半。两 bit 使用同一原事件摘要的原字节，各自绑定登记输入和 A0。

```powershell
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request <request.json> --preview
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request <request.json> --run-id <new-UTC-run-id>
```

预览只检查结构化白名单。正式准备重新调用固定 `v1-s2` 原实现的 `audit_transport_event` 和 `package_payload`，检查完整事件分母、原二进制/输入/祖先链、真实退出和所有源字节。源包和固定实现检查前后的原哈希一致才允许冻结。正式准备还读取成功 D3 的完整原档；从已冻结 A0 输入取得的只是匹配身份，A0 功能资格必须另以真实结果审计。

输入保持以下对应关系：

| 文件 | 含义 |
| --- | --- |
| `geometry-contract.json`、`model.proposed.json` | 实际 D3 的原几何与器件模型 |
| `transport-geometry-contract.json`、`transport-model-input.json`、`transport-request.json` | Geant4 的原同名输入，分别保留原 SHA |
| `source-contract.json`、`sources.dat`、`fragments.json`、四个 `heavyion.*`/`source.par` 文件 | 原 `couple.package_payload` 七个源文件；另保留原 `source-bundle.json`、事件绑定和 pre-clock 参考 |
| `device-source-binding.json` | D3、完整原事件、匹配 A0 和 prospective 摘要的器件侧绑定；不改原源合同 |
| `run-parameters.par` | 正源实际选用文件，严格等于原 `physics.par` 字节 + LF + 原 `source.par` 字节 |
| `source-spec.json` | 真实 bit、`CONTROL`/`SIGNAL`/`STRUCTURAL_ZERO`、`numerical_variant` 及原物理/源/登记摘要哈希 |
| `source-time-contract.json` | 原完整事件的观察范围；晚源未裁剪 |

源摘要使用固定 `source_feature_versions.py` 分发器。新 binding 为 `dram-see-v4-prospective-source-binding-r2`，分别冻结分发器、原 v1 验证器、注册表、依赖清单的原字节与 SHA；不把分发器 SHA 当成 v1 SHA。旧 r1 输入和旧验收记录不改。生成摘要和输入绑定只读源及输入几何，未读取 TCAD 的生成率、BE 时间、收集电荷或电压响应。

原质子核仍为 0.03 µm 各向同性 Gaussian 线卷积、2 ps 时间宽度、3.6 eV/电子空穴对。正源保留 `[min(t0)-8σ, max(t1)+8σ]` 完整范围，窗口内主最大步长为 0.4 ps；若完整范围不在现有 8.1–19.9 ns 保持/收集区间内部，明确拒绝并保留事件，不裁晚次级或改源时刻。真实空事件使用原 epoch 至 19.9 ns 的登记比较窗；源字段缺失保持结构性缺失，不填成实测零。

新检查覆盖受控别名、物理错配拒绝、两 bit 和三数值分支的 A0 逐字节对应、参数聚合、零源、晚源拒绝、固定版本快照，以及一次真实既有 α 纯输入摘要的分发绑定。测试目录均明确标记非原生，未构造生产项目或原生结果归档。尚未取得本接口的真实质子 TCAD 运行、原生 HeavyIon 时钟/生成率、源电荷/质心、载流子守恒或功能结果；PMI/R12 仍未据此证明修复。首个真实完整事件和 D3/A0 到位后，主调度通过原 runner 执行并审计这些部分。
