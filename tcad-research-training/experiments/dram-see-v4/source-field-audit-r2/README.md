# 通用原生源场审计 r2

对应 `interface-completion-r1/implementation-contract.md`，仅处理登记的二维人工源。旧source-field-audit-r1、旧物理实现及原档保持不变；旧r4已通过证据由外部复用桥核验，无需重做后处理。本模块不调用SSH、TCAD或调度器。

## 原生提取

`extract_fields.tcl`继承已原生验证的bounded-r2脚本：每帧先删plot再删dataset，返回单对象名必须与实际创建对象严格相同；所有失败记录并退出2。新增两个窗口SourceLeft=[0.295,0,0.355,1.2]、SourceRight=[0.495,0,0.555,1.2]，前九ROI、材料、积分公式和坐标矩保持原样。

输入 `tdr-files.txt` 每行一个已归档的TDR basename；默认清单仅供旧r2 A1五帧兼容验证。根适配器复制文件并验证前后SHA。原始G、XG、YG、ONE在11ROI和无窗口硅域积分，每帧52数值行及2清理行；保持CSV列、`FIELD_AUDIT_COMPLETED mandatory_errors=0` stdout和receipt格式，status schema为`source-field-audit-r2-extraction`。

```text
svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl
```

## 审计与放行边界

```text
python -B experiments/dram-see-v4/source-field-audit-r2/audit_fields.py snapshots <旧r2-A1-run> --extraction <新提取operation根> --output local_runtime/dram-see-v4/source-field-audit-r2/audit-dev/<新标签>
python -B experiments/dram-see-v4/source-field-audit-r2/audit_fields.py full <r5有源run> --extraction <全帧operation根> --output local_runtime/dram-see-v4/source-field-audit-r2/audit-dev/<新标签>
python -B experiments/dram-see-v4/source-field-audit-r2/test_audit_fields.py
```

API为`audit(run,extraction,mode='full',output=None)`。CLI必须显式选择模式。operation根或其collected均可输入；receipt读取位置及schema保持根适配器约定。`snapshots`支持旧r2 A1稀疏帧，只验证原生提取、原始归档及BE时间关联，不令`field_measurements_passed`为真。`full`支持r5全部登记有源case/bit/profile；A0缺场不伪造零或质心。

每一帧必须对应实际成功BE步和精确PLT区间，起点状态不重复积分；少一帧、重复帧、未知退出码、非有限量、错hash或缺坐标矩都失败。电荷ΣG_iΔt_i、时间矩使用区间中点；窗外量只读取原生legacy曲线，绝不从理论尾部补零。所有测量保留1µm有效厚度及显式单位转换。

时间oracle为原公式σ=s_hi，仅用于评价，不生成缺失场。A3按预计算域内约0.5fC验收，输入总1fC被裁掉的部分不补回。旧9ROI门槛及5%电荷/波形、0.05 ROI比例、0.01µm质心、0.5ps时刻门槛不变。各有效ROI均用真实XG/G、YG/G检查质心；有效指解析域内电荷比例≥原active_generation_fraction，活跃样本使用该ROI峰值乘同一比例。

新增SourceLeft/Right仅在A5/A6/A7参与放行；其它case仍记录它们但不新增门槛。三个分离源case检查局部BE平均波形；A6检查两个窗口的局部时间质心及右减左约10ps延迟，沿用0.5ps时间容差。即使总源电荷正确，错误重合、左右时间颠倒或局部位置错误仍应失败。

## 输出绑定

`audit.json` schema为`source-field-audit-r2`，保存passed、field_measurements_passed、run/manifest/archive/code/contract SHA、全部原门槛、checks/errors和失败量。`overall_source_interface_passed`始终false，匹配A0、分段/等价/细化的综合验收由root模块完成。

`frames.csv` schema标签为`source-field-audit-r2-native-11roi-frames`，保留真实起止时间及日志行，逐帧完整输出`G_<ROI>_raw`、`XG_<ROI>_raw`、`YG_<ROI>_raw`、`ONE_<ROI>_raw`和无窗口硅域矩。报告的`frames_csv_sha256`、`frames_csv_path`绑定该文件；`extraction_directory`、`field_measurements_sha256`及完整receipt绑定原生CSV，不能更换波形却沿用通过JSON。G积分单位µm²·cm⁻³·s⁻¹，矩单位多一维µm，ONE为µm²。新文件不把仅五帧的技术检查当完整源通过。

离线测试使用明确合成夹具，覆盖所有源角色、A3禁止补量、A5误重合、A6延迟/反序、局部质心偏移、缺帧/失败BE、缺矩/非有限量、新窗口适用范围及0.25ps采样；不代表新TCAD物理结果。实际原生与全帧结果由root执行后另附。

已完成原生兼容证据：操作`r5-extractor-five-r1`由root执行，SVisual/SSH/remote/collection真实退出均0。新snapshot审计位于`local_runtime/dram-see-v4/source-field-audit-r2/audit-dev/native-five-r1/`；`native-five-comparison.json`逐项核对旧r6的220条数值行完全一致，新增两窗口40行单独保留。该五帧技术验证不令旧基准空间失败或完整源状态通过。
