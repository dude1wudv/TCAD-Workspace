# 多参数质子候选的接续入口

先为对应器件准备新的编译输入；`--model-path` 和 `--geometry-path` 应来自同一份真实受控D3输入，后续进入器件响应仍须有其实际成功D3证据。下列占位路径需要替换，命令没有在本阶段执行原生工具。

```powershell
python -B experiments/dram-see-v4/continuous/proton/transport_prepare_v2.py build --model-path D3_INPUT/model.proposed.json --geometry-path D3_INPUT/geometry-contract.json --output local_runtime/dram-see-v4/continuous/proton/NEW_BUILD_INPUTS
```

主代理沿原 operation/owner/共享锁实际编译并收集该包后，开发期可准备原矩阵train条件。例如T01必须使用70 nm gate的对应编译包，seed必须属于该原条件：

```powershell
python -B experiments/dram-see-v4/continuous/proton/transport_prepare_v2.py run --build ORIGINAL_COMPLETED_BUILD --condition-id proton-T01 --seed 61017011 --events 1 --label NEW_NATIVE_LABEL --output local_runtime/dram-see-v4/continuous/proton/NEW_RUN_INPUTS
```

这些入口只生成不可覆盖的新输入目录，不提交操作、建立runner或改变旧队列。原调用协议和编译脚本保持原字节；原生事件仍由主代理用既有 `transport-probe/operation.py` 调度。断连时只查询和收集原label。

完成实际输运并完整收集后，对每个原event ID保留完整事件绑定并生成源包：

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_bundle_proton_v2.py --operation ORIGINAL_COMPLETED_RUN --event-id 0 --build ORIGINAL_COMPLETED_BUILD --output local_runtime/dram-see-v4/continuous/proton/NEW_EVENT_BUNDLE
python -B experiments/dram-see-v4/continuous/proton/source_features_proton_v2.py build --source-dir local_runtime/dram-see-v4/continuous/proton/NEW_EVENT_BUNDLE --output local_runtime/dram-see-v4/continuous/proton/NEW_EVENT_BUNDLE/source-features.json
python -B experiments/dram-see-v4/continuous/proton/source_features_proton_v2.py verify --packet-path local_runtime/dram-see-v4/continuous/proton/NEW_EVENT_BUNDLE/source-features.json
```

`source_bundle_proton_v2.audit_transport_event(operation,event_id,build)` 逐次核对原operation归档与真实退出、编译输入/二进制、完整事件分母、精确probe列表、材料/overlap、源束流、线程协议和原祖先链。`payload` 复用原 `couple.py` 的完整源核。新features验证器完整重做该绑定和源包，再用原未修改的有限Si矩积分；不存在直接从CSV伪造成功native packet的入口。

`v2-proton-bcat` 当前没有登记到固定分发器，也没有接入device/data。候选schema分别为：

| 对象 | schema |
| --- | --- |
| 输运几何 | `continuous-bcat-proton-geometry-v2` |
| 输运请求 | `continuous-proton-transport-request-v2` |
| 原生事件绑定 | `continuous-proton-native-event-binding-v2` |
| 事件源包 | `continuous-proton-source-bundle-v2` |
| 13量摘要 | `continuous-particle-source-features-v2`，`version_id=v2-proton-bcat` |
| 13量合同 | `continuous-particle-source-feature-contract-proton-v2` |

原核的 `sources.dat`、HeavyIon片段、`fragments.json` 和 `continuous-proton-heavyion-candidate-v1` 源合同仍由原 `couple.py` 原样生成。外层v2事件绑定新增实际gate/SN和所供D3几何身份；不把相同核格式误称为同一器件输入。包内同时保存 `geometry-contract.json`（输运包装）和 `device-geometry-contract.json`（原D3字节），以及原 `model-input.json`、`request.json`。后续device接线须分别对应实际D3文件，不覆盖或偷换这些同名来源。

调查发现，限制不在C++核心：`prepare.py:66` 已从模型读取参数，`bcat_geometry.inc:33` 使用 `frozen::gate_top`；C++运行CLI已有能量、角度、目标与方位。实际S2限制在 `source_bundle.py:40`、`:55`、`:62`、`:296` 和 `source_features.py:74`，再加已经编译的S2 header/binary只绑定80/87。新几何输入从原模型重新核对物理几何、掺杂、接触和独立Si体积，使用供给的D3几何原字节；每一条件生成自己的header及编译合同。gate改变氧化物/空隙边界；SN不改变原G4材料物理，同随机流的不同SN不能增加独立样本数。

开发入口只准备原T01–T06。原I01/I02和全部外推条件保持最终留出；改变SN、seed或名字不能放行。只读条件查询和未来事件审计可保留它们的原身份，但本阶段不生成最终事件或响应。正式最终运行输入的阶段接线仍须与data端已冻结设计/模型统一完成。新增SN轴没有被本候选自动登记为训练数据。

所有正Si电离沉积、零弦长、晚源都保留；完整无正Si电离事件的13量为零，解释矩为null。缺失/损坏事件和积分失败均拒绝。晚源窗超过19.9 ns时，后续device必须保留事件并明确不可表示，不能裁尾。原G4标准10 μs neutronTrackingCut保持不变，不能把“保留记录中的全部晚源”说成无限时间的输运物理。

13量仍相对输入目标(-0.052,0,0) μm和15 ns，不归一，不读TCAD时钟、场或响应。v2以Decimal进行原15 ns到秒的单位转换。旧v1 `float('15')*1e-9` 的浮点结果为 `1.5000000000000002e-08`，与字面 `15e-9` 相差1 ulp；旧包不能因此改写。若后续兼容两版，应明确记录这项原单位换算差异，不能用一般时间容差隐藏物理变化。该问题已交主代理/data owner处理，未改现有注册或data文件。

本次新增7项检查通过：9组纯输入传播、几何/掺杂错配拒绝、原12行及留出保护、复用实际旧编译C++并绑定当前D3输入、结构零/晚到点源、旧S2编译或缺失事件不能冒充v2、20份冻结文件保持原字节。9组几何及晚源是明确标记的数学测试输入；唯一准备的编译包位于 `proton-v2-candidate-r1/UNIT_INPUT_ONLY_NOT_NATIVE-*/build-g80-sn87-INPUTS_ONLY`，没有二进制或事件输出，不能作为原生结果或运行队列。

尚未验证：新header实际编译、新条件G4探针/输运/全部事件审计的成功路径、真实源包及13量完整重算、HeavyIon实际字段/接受BE/双载流子/匹配A0、网格/步长/cut细化、数据设计和模型兼容登记。当前所有相关原生资格、PMI/R12修复标志仍为false。完整证据在 `local_runtime/dram-see-v4/continuous/proton/proton-v2-candidate-r1`。
