# 源摘要的固定版本分发

从 `source_feature_versions.py` 的固定登记入口读取源包：

```python
packet = dispatcher.verify(packet_path, input_files=actual_source_input_bytes)
info = dispatcher.version_info(packet)
contract = dispatcher.contract_bytes(packet)
```

`v1-s2` 仍为默认，支持原 S2 α/质子路径。`v2-alpha-surface` 只支持已固定的 α 正源，必须由 packet 显式声明；对应 schema 为 `continuous-particle-source-features-v2`。显式构造或检查可调用 `load_version('v2-alpha-surface', particle='alpha')`。v2 质子、未知版本、篡改实现路径/hash、合同或依赖均拒绝。分发器仅加载登记的原始文件，不执行 packet 提供的代码路径。

新绑定保存 `version_info` 的完整结果，并逐字节保存其中 `verifier`、`dispatcher`、`registry`、`dependency_manifest` 四项。packet 的实现键仍使用实际文件名：v1 为 `source_features.py`，v2 为 `source_features_v2.py`；不能为兼容字段而改写原 packet。

旧绑定使用其保存的字节核验：

```python
result = dispatcher.verify_version_snapshot(
    original_info,
    {name: original_snapshot_bytes[name] for name in
     ('verifier', 'dispatcher', 'registry', 'dependency_manifest')},
    packet,
)
```

此入口只核验绑定身份，不执行任何快照代码，也不代替 `verify` 的源输入重算。原登记项、原 verifier、依赖清单必须仍与固定版本一致；dispatcher/registry 则可以属于已登记的历史组合。因此不能将当前 dispatcher SHA 填进旧绑定。仅保存指向当前文件的路径也不够，必须保留原始字节。后续增加分发版本时，先保存现有 dispatcher/registry，再将其登记到历史表；固定源版本的实现或依赖若要改变，应创建新的源版本。

`source-feature-compatibility-v1-v2.json` 给出可供 data 审阅的兼容集合，`semantic_compatibility()` 核验固定 hash 后读取。它不自动放行数据或原生资格。两版 α 的13量使用相同字段、单位、有限 Si/全时间积分、相对输入 r0 和 epoch 的未归一化电荷矩；兼容条件固定 r0=(-0.052,0,0) μm、epoch=15 ns、w=0.05 μm、sigma=0.2 ps，能量指首次建模 Si 表面处的动能。跨版本数据限正源 Aalpha/amplitude1，并保留各自 packet/version/contract 身份及真实输入条件。v1 的 Z/H/split 仍是其自身资格路径；v2 当前没有这些构造器。质子只允许 v1。

v2 重生成 ASTAR 路径和斜射有限端面，数值实现与 v1 源文件并非逐字节相同。13量同义不能推出实际源生成、原生积分或器件响应已等价。还需真实 HeavyIon 有限端面、接受步、源场、电荷及两bit匹配A0资格。未产生原生运行、训练数据、预测分数或 PMI/R12 修复结论。

原 `ALPHA-V2.md`、`ALPHA-V2-ASSUMPTIONS.md`、v2源码头部和合同中“尚未登记”的文字保留其冻结时状态；本文件与固定 registry 记录后续分发接入，不原位改写这些已绑定的历史字节。device/data 接线验收由各自模块单独给出。

本次只运行新增的 `test_source_feature_versions_v2.py -v`：7项通过，包含一次 v1 原包重算、v2 斜射包重算、输入和实现篡改拒绝、跨粒子拒绝、历史快照与当前快照核验、原23份文件/packet字节保持。旧数学套件没有重跑。证据保存在 `local_runtime/dram-see-v4/continuous/proton/source-feature-registration-v2-r1`。
