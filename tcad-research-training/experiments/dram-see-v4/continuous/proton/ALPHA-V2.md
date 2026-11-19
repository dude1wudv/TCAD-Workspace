# α v2 的使用与接线边界

`source_features_v2.py` 是独立入口，目前未登记到 `source_feature_versions.py`，也未接入 device/data。它只建立可重算的源输入和13量摘要，不执行TCAD、不读取原生时钟或响应。所有v1原路径、字节和分发注册保持不变。

从本项目根目录准备一个新源包：

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_features_v2.py alpha --model <纯输入model.proposed.json> --geometry <对应三维geometry-contract.json> --energy 3 --angle 30 --output local_runtime/dram-see-v4/continuous/proton/<新目录>
python -B experiments/dram-see-v4/continuous/proton/source_features_v2.py verify --packet local_runtime/dram-see-v4/continuous/proton/<新目录>/source-features.json
```

输出目录必须不存在，重复调用不会覆盖。支持 gate=70/80/90 nm、SN=82/87/92 nm，能量3/5/7 MeV、角度0/30°；需要实际输入model与几何的gate和SN一致。`source-request.json` 是该次能量/角度的权威输入，模型中旧α基线元数据不会被改写。模型所声明的r0、sigma、w、时间和数值窗口必须仍符合原定义。

Python API（用精确文件加载，不依赖调用者的 `sys.path`）为：

```python
build_alpha(model_path, geometry_path, energy_MeV, angle_deg, output_dir)
verify(packet_path, input_files=None)
contract_bytes(packet=None)
```

`verify` 返回完整重算packet，要求它与原packet完全相等。`input_files` 可为 `dict[str, bytes]` 子集；已提供且属于绑定源文件的字节必须完全匹配，未提供的绑定文件从原包读取并重算。调用者仍须要求其归档中必要文件都提供。实现只加载自身固定模块和哈希固定的旧独立Si参考，不执行packet给出的任意代码路径。

packet schema 为 `continuous-particle-source-features-v2`，`version_id=v2-alpha-surface`。`source_features` 恰含原13字段；`source_conditions` 含gate、SN、energy、angle；`inputs` 是 `{name: {path, sha256}}`；`feature_contract`、`feature_contract_sha256`、`feature_contract_ref` 绑定本版本合同。原合同为 `source-feature-contract-v2.json`，包内副本名为 `source-feature-contract.json`，可由 `contract_bytes(packet)` 取得原字节。同一源两bit使用相同packet字节，摘要不含bit。

绑定输入文件为 `model.proposed.json`、`geometry-contract.json`、`source-request.json`、`alpha-astar-silicon.csv`、`source-origins.json`、`alpha-profile.csv`、`heavyion.physics.inc`、`source.par`、`source-contract.json`。最后四项每次从原ASTAR与纯输入重新生成并逐字节比较。`source-origins.json` 留存复制来源路径/hash；计算使用包内已绑定快照。旧ASTAR原表hash另有固定校验，不接受重新缩放的5MeV表。

数学定义与事先声明见 `ALPHA-V2-ASSUMPTIONS.md`。0°路径1 μm，30°路径1.1547005383792515 μm；能量定义在所建模Si表面。中心线必须有全程Si证明，否则拒绝。横向云与氧化物相交只计为源材料域裁剪，不能解释为实际沿氧化物传播/损能。保留未截线电荷、外盒电荷、实际Si电荷及两类损失；没有尾量重归一。

源合同保留原±8sigma窗口、BE源窗最大步长0.04 ps及细化0.02 ps。当前只是要求，`actual_clock=null`。后续原生验证还须证明HeavyIon实际沿斜射方向的有限端面语义，取得真实全源场、接受步区间、PLT/TDR对应和同网格/物理两bit匹配A0。当前没有任何v2原生资格；PMI/R12也没有因此修复。

已保存三份最终输入示例于 `local_runtime/dram-see-v4/continuous/proton/alpha-v2-examples-r2`：80/87 nm、5 MeV、0°；70/82 nm、3 MeV、30°；90/92 nm、7 MeV、30°。第三份只为最终留出条件的数学输入准备；全部 `data_design_registered=false`，没有TCAD响应或调参。SN维度须在后续数据设计中显式登记。旧原矩阵的最终条件也保留提示，准备源包不授予其训练用途。

新增6项定向检查通过，覆盖原独立RK4能量表、9组几何和射线坐标、无轴向展宽的原始矩、独立轨迹坐标外盒积分、旧S2原点/单位/13量及完整输入重算。首轮示例发现正入射微小外盒尾量被数值求积误差淹没，原始有符号差值及源码保存在 `alpha-v2-r1-before-normal-box-correction`；现用可解析的正入射外盒多项式积分，原自适应值另记诊断。只对受影响S2兼容和新增微尾量检查复核，均通过；没有改门限或截零。旧v1八项数学检查未重跑。

后续要登记v2时，必须显式固定本版本实现与依赖hash，并单独审阅模型合同兼容表；不能删去现有单合同限制，或把v2改动冒充v1。当前源数学文件完成后按不可原位修改处理，后续改核应建立新版本。
