# α v2 受控输入

`prepare_case.py` 现可从固定注册的 `v2-alpha-surface` 原包准备一个 A0 或信号输入。生成仍要求真实完成且完整收集的 D3 原档，不接受只有输入的目录。原 `request-r1`、固定 v1 源、首个 S2 A0 和已经冻结的 D3 输入保留。

真实 D3 完成后，用它归档中的 `model.proposed.json`、`geometry-contract.json` 生成新的 v2 源包；不能把数学示例自动当成该 D3 的源包。下面是 v2 A0 请求的完整形状：

```json
{
  "schema": "dram-see-v4-controlled-device-request-r2",
  "kind": "transient",
  "particle": "alpha",
  "source_version": "v2-alpha-surface",
  "source_packet_file": "ABSOLUTE_PATH_TO_ORIGINAL_V2_SOURCE_FEATURES_JSON",
  "gate_top_depth_nm": 80,
  "sn_junction_depth_nm": 87,
  "dimension": 3,
  "variant": "main",
  "stored_bit": 0,
  "source_case": "A0",
  "d3_source_run": "ABSOLUTE_PATH_TO_ORIGINAL_COLLECTED_D3_RUN"
}
```

先生成该 bit/variant 的 A0；信号请求把 `source_case` 改为 `Aalpha`，再加入 `matched_a0_project` 和 `registered_data_input`，分别指向该 A0 冻结输入与 data 登记原文件。`source_features_file` 可省略，由 `source_packet_file` 导出；显式给出时必须是同一原路径。bit1 使用相同源包原字节及 bit1 登记。A0 不接收活动源登记，源包只提供不活动的原输入和精确时序上下文。

```powershell
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request REQUEST.json --preview
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request REQUEST.json --run-id NEW_RUN_ID
```

两条命令都不提交原生作业。`--preview` 只验证结构化请求；实际生成还验证原 D3 退出与归档、源重算、登记、物理和 A0 对应。找不到真实成功 D3、源包或匹配 A0 时直接拒绝。输入资格登记可以先于原生结果，不能把数据训练资格当成首次源运行的前置条件。

gate 允许 70/80/90 nm，SN 允许 82/87/92 nm。能量 3/5/7 MeV 和角度 0/30° 只读取包内 `source-request.json`；请求不接受能量/角度覆盖，也不缩放 v1 的 5 MeV 表。v2 目前只有正幅 1 的 `Aalpha` 和源关闭的 `A0`，明确拒绝 H、Z、split。原 `source-request`、ASTAR、profile、HeavyIon、source.par 和 source-contract 都保留原字节。

`main` 使用相应真实 D3 的主网格；`time` 使用同网格，时间步长减半；`mesh` 要求独立真实 h/2 D3 及以该 D3 原 model/geometry 重新绑定的源包。主网格包不能借用到 h/2。每个变体有同 bit、同 mesh、同物理、同时序的 A0。去除声明的源片段和参数附加后，信号与 A0 的完整 `device.cmd` 必须相同。

原 `source-contract.json` 不增加 device 字段。单独的 `device-source-binding.json` 记录实际 D3 的 manifest/archive/mesh/geometry-validation SHA 和物理四文件 SHA；`run-parameters.par` 精确等于原 `physics.par` 字节、一个 LF 与原 `source.par` 字节。`source-packet.json` 保留原包；信号的 `source-features.json` 必须与它逐字节相同。新绑定通过固定 dispatcher 重算并冻结 verifier、dispatcher、registry、dependency manifest 的独立身份，不运行包提供的代码。

v2 信号登记继续调用 `prospective.bind` 和 data 的 `verify_registered_input`。资格登记使用 data 的 request-v3 兼容入口，输出仍为 registered-data-input-v2；`source_case=Aalpha` 与实际 generic spec 的 `role=SIGNAL` 分开记录。原 split、原留出提示和数据合同原字节不改。S3 及其它原最终条件，包括插值组，继续由 data 保护，改变 SN 或 seed 不能重新分配为训练样本。

`source-time-contract.json` 直接复制原包 ±8σ 端点。A0 和信号都按相同浮点原值生成窗口；主步长 0.04 ps，细化 0.02 ps。这个 v2 分支不更改 v1 的原窗口。源模型要求在路径 s=0、s=L 处使用垂直于斜射方向的有限端面；当前生成的 HeavyIon 片段、全源窗 TDR 请求和场观察并不证明求解器实现了该语义。

当前 data 的 `source_bridge.py::alpha_admission_version` 对 v2 明确拒绝科学准入，原因是独立有限端面参考、实际 accepted-BE 全帧比较和端面语义尚未接入。诊断原档可保留，输入数学和登记可以通过；不能因此称源电荷、两 bit 功能、收敛细化或 PMI/R12 已通过。后续必须由真实字段、时钟、双载流子、KCL 和匹配 A0 证据完成专属审核。

本次新增 6 项接口检查和 1 项真实两 bit 登记集成均通过；另复核 1 项直接受影响的 v1 prospective 检查。v1 求解输入与冻结 D3r3 生成器对比保持原字节，当前 bridge 也接受 D3r3 冻结输入，未修改它。证据见 `local_runtime/dram-see-v4/continuous/device/alpha-v2-device-delivery-r1.json`。未运行任何新 TCAD；尚无 v2 真实 D3→A0→源响应结果，h/2 正向运行也待实际网格。
