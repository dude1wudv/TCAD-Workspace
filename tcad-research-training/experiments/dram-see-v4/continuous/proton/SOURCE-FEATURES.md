# 预 TCAD 的源条件摘要

现成 α 摘要位于 `local_runtime/dram-see-v4/continuous/proton/source-features-s2-alpha-main-r1/source-features.json`。输入是器件分支准备的5个声明源文件，原目录为 `local_runtime/dram-see-v4/continuous/device/source-feature-inputs-alpha-main-20261017T062254Z/`。这些文件来自 S2 D3 冻结输入的模型/几何、原 ASTAR 表和实际源片段；不包含 TCAD 场或电路响应。本接口没有调度任何原生程序。

预期模型是“给定源摘要及器件条件的响应代理”。摘要不是仅从能量/角度得到某次随机质子事件的预测，也不代表总体 SEE 风险。两个存储 bit 共用同一个摘要文件；存储 bit、器件条件和响应标签在数据分支另行绑定。

## 调用与绑定

构建命令已经对上述 α 输入执行成功。输出使用 exclusive create，不能覆盖；需要独立的新版本时使用新输出路径。

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_features.py alpha --source-dir local_runtime/dram-see-v4/continuous/device/source-feature-inputs-alpha-main-20261017T062254Z --output local_runtime/dram-see-v4/continuous/proton/source-features-s2-alpha-main-r1/source-features.json
python -B experiments/dram-see-v4/continuous/proton/source_features.py verify --packet local_runtime/dram-see-v4/continuous/proton/source-features-s2-alpha-main-r1/source-features.json
```

质子入口只能读取已通过 `source_bundle` 绑定的真实完整事件源包；在真实输运事件和原源包生成之前，不能执行下面的转换，也不填造替代样本。

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_features.py proton --source-dir ACTUAL_COMPLETE_EVENT_SOURCE_BUNDLE --output local_runtime/dram-see-v4/continuous/proton/NEW_EVENT/source-features.json
```

可供其他模块调用的接口：

```python
packet = source_features.build_alpha(source_dir, output_file)
packet = source_features.build_proton(source_bundle_dir, output_file)
packet = source_features.verify(packet_file, input_files=provided_source_bytes)
raw_contract = source_features.contract_bytes(packet)
```

`verify` 返回完整重算 packet，并要求它与已保存内容完全相等。`input_files` 是可选 `dict[str, bytes]`：提供的已绑定源文件子集逐项核对哈希，缺省依赖仍从原输入路径完整重算。调用方负责要求实际归档必须存在的源文件集合。α 的5项为 model.proposed.json、geometry-contract.json、alpha-profile.csv、按 case 前缀命名的 heavyion.physics.inc 和 source.par。质子的 G4 geometry-contract.json 是输运 wrapper，不能把 TCAD 同名 descriptor 作为同一字节输入传入；两者的实际几何相符性由已有源/器件审计另行核对。

输出 schema 为 `continuous-particle-source-features-v1`。数值在 `source_features`；全部纯输入文件引用在 `inputs`，每项严格为 `{path, sha256}`；独立实现引用在 `implementations`。`source_package` 绑定原源输入目录和规范的源输入子集 manifest/hash，避免把含 bit 的器件全包当作两 bit 共享源身份。`feature_contract` 嵌入完整合同，`feature_contract_sha256` 是合同原字节的 SHA256，`feature_contract_ref` 指向原合同文件。器件分支复制原 packet bytes 和 `contract_bytes(packet)`，不会生成循环的全包哈希。

`source_conditions` 从输入重算 gate_top_depth_nm、sn_junction_depth_nm、energy_MeV、angle_deg；质子另有 seed、transport_event_id。`r0_um` 与 `epoch_s` 独立列出。源状态只有 `PRESCRIBED_POSITIVE_SOURCE` 和 `PRESCRIBED_STRUCTURAL_ZERO`；后者是明确零输入，不是“测得零”。零源的原生资格仍需数据分支验证原空事件/零源输入、电学响应、双载流子和匹配控制。

实现使用精确路径及私有模块名。α 分支不导入质子调度模块；质子旧绝对依赖临时绑定到其精确文件，完成后恢复服务器 `sys.modules`，不会把 device.prepare 换成 proton.prepare。实现或依赖变更会使旧 packet 重算校验失败，需要显式的新版本。

## 13 个输入量

所有矩都是在实际有限 Si 域、全时间上的原始电荷加权积分，不除以 Q。

| 字段 | 定义 | 单位 |
|---|---|---|
| source_present | 明确正源=1，明确零源=0 | 1 |
| Q_Si_fC | ∫dQ | fC |
| M_x / M_y / M_z_fC_um | ∫(r_i-r0_i)dQ | fC µm |
| M_xx / M_xy / M_xz / M_yy / M_yz / M_zz_fC_um2 | ∫(r_i-r0_i)(r_j-r0_j)dQ | fC µm² |
| M_t_fC_ps | ∫((t-epoch)/ps)dQ | fC ps |
| M_tt_fC_ps2 | ∫((t-epoch)/ps)²dQ | fC ps² |

精确字段顺序见 `source-feature-contract.json`。质子 r0 取原 request.json 的输入 target_um，epoch 取输入 source-contract.epoch_s；α 从输入模型的 position_nm 和 time_center_ns 换算。不会用实际 BE、TCAD G、生成/收集电荷、ΔV 或场统计推导特征。

解释字段中的质心/协方差由这些原始矩导出，不进入这13个特征。明确零源时全部特征为0，解释质心、协方差、时间方差为 null。缺文件、非有限量、积分失败或正源无法解析出有限 Si 电荷直接报错，不填0。没有尾部重归一、晚次级截断或按结果删事件。

## 两种核与积分

质子沿原 sources.dat 的每条完整源段积分：均匀段参数 u 上的3D各向同性 Gaussian 卷积，w=0.03 µm；时间 Gaussian 的 sigma=2 ps，中心随原段时间线性变化。全时间的一、二阶时间矩分别使用中心相对 epoch 的 τ 和 τ²+sigma²，再与该 u 处的有限 Si 空间质量积分。零长度源和任意晚次级照常贡献。

α 使用原101节点、5 MeV ASTAR 电子 LET LUT，在 z=0..1 µm 逐段线性插值，横向 Gaussian w=0.05 µm，所有纵向节点共用 sigma=0.2 ps 的输入时刻。纵向不做 Gaussian 卷积，所以 z 二阶矩中没有人为增加 w²/2。Aalpha、H、split、Z 的源片段必须与已有 α 生成器逐字节匹配；H 为半幅，split 保留同一连续 LUT，Z 是明确零幅。

独立 Si 掩膜复用已有 `source_reference.SiliconMask` 的解析材料边界；不改变其原 Q/一阶矩或 native audit 行为。新代码独立增加截断 Gaussian 的二阶原函数与截面二阶矩。矩形区沿 z 解析积分，圆底用 z=c+r sinθ 去除平方根端点；再做源段 u 或 α LUT 分段积分。固定为当前 S2：80 nm gate top、87 nm SN 结深、20 nm active width、150 nm 金属最深；栅空隙仍按原显式理想电极材料假设。

基础数值容差复用原参考的归一化绝对 `1e-11`、相对 `1e-8`，另以四分之一容差重算全部矩。每个已声明单位下的差值上限是 `100*abs_tol*max(1,全空间分配fC)+10*rel_tol*abs(加密矩)`；这是积分重复性要求，不是原生源验收判据，也不是严格误差界。没有改动原生源验收容差。

## 本次实际证据与剩余边界

6项新增检查通过后，仅追加运行2项新边界检查，没有重跑旧质子/源资格套件。覆盖 Gaussian 二阶解析值、点/斜段/时间交叉矩、边界与晚源、原 proton Q/一阶兼容、原 α Q/一阶兼容及独立密集 z² 积分、零/缺失/clock 拒绝、输入及 packet 篡改、两 bit 共享、禁止覆盖、私有模块恢复、Z/split 原输入一致性。构造的质子行只用于单元测试，不能进入训练数据。

首份声明 S2 α packet 的 Q_Si 为 **5.565525196954477 fC**；四分之一容差重算的 Q 差为 **2.4203750115248113e-11 fC**。这是原源和输入几何推得的值，尚无新原生源场或响应验收。

当前未执行真实质子事件的 `proton_packet` 文件级路径；它仍依赖首个实际完整 Geant4 事件。没有拟合、SSH、编译、求解或源资格操作。所有 packet 保持 `native_source_qualified=false`、`pmi_r12_fixed=false`；本接口不替代有限 Si 原生场、实际 BE、载流子及电路验收。
