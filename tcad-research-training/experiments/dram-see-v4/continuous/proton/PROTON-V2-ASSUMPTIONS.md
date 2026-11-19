# 多参数质子 v2：实现前定义

本记录先于新候选实现建立。仅新增独立 Python 输入/审计/数学入口，不修改固定 v1、α v2、分发注册、原 operation、输运 C++ 或 device/data；不执行 SSH、编译、输运、TCAD 或拟合。

1. 依据为原 `finite-matrix.proposed.csv`、原 `prepare.py`/`source_bundle.py`/`couple.py`、`bcat_geometry.inc`、`transport_material_r2.cc` 和已收集的 `cgoal-bcat-build-20261017t043911z`。原 C++ 实现通过 `geometry.hh` 的常数构造布尔体，束流 CLI 已有能量和角度参数，因此此次不改 C++。每次候选编译输入必须绑定所提供 model 和三维几何的完整原字节，再生成该条件自己的 header；不复用 S2 二进制冒充其它条件。

2. 参数范围为 gate-top 70/80/90 nm、SN结深82/87/92 nm。其余代表 BCAT 材料域和已声明掺杂定义保持原值。gate-top 改变槽内 SiO2/GateVoid 分界；Si材料域本身不变。SN改变电学掺杂及输入身份，但原 G4 CSG 仍使用相同 Si/SiO2 材料，无掺杂依赖输运物理，不能把不同SN的源差异解释为掺杂能损效应。即使材料域相同也逐份绑定原模型和几何，不把条件标签改写到既有事件上。

3. 质子条件及种子必须逐项来自原12行矩阵。开发输运输入只准备原train行T01–T06；I01/I02、depth/energy/joint外推均保持最终留出，不能因改变SN或seed转成开发条件。SN新增轴尚需data端明确设计登记；本候选不替它分配训练/最终身份。只读事件审计保留原矩阵split，允许未来对已发生的最终事件取证，不读取或创造其响应。

4. 沿原方向定义，表面目标(-0.052,0,0) μm，phi=180°，theta=0/30°；原生源从z=-1 μm真空位置发射，能量50/100/150 MeV使用原CLI。能量/方向/位置/seed/事件数必须与真实metadata相符。时间为原输入epoch15 ns加各原生step的全局飞行时间，不把质子时间换成α的公共无飞行时间核。

5. 沿用原H臂（QGSP_BIC+EM Option4）、串行G4RunManager、既有数据环境和原operation。原软件保留标准10 μs neutronTrackingCut；不得增加用户kill、截时或筛选。全部event/track/step/birth-link及零沉积事件保留分母。核反应次级中子不是新增中子初级研究。

6. 正Si源完全复用原 `edep-NIEL`→3.6 eV/pair换算与原 `couple.py` 的各向同性3D Gaussian线段卷积：w=0.03 μm、sigma=2 ps，节点间隔w/12、时间子段sigma/8、轴向尾界8w，无补偿归一。保留零弦长、晚次级和所有正Si沉积；其它材料/零电离仍在原事件能量账内。完整无正Si电离事件产生结构零源，不把缺失文件或失败当0。源窗超过电路范围时由后续device明确拒绝并保留事件，不能截尾或删除。

7. 13源量直接复用已固定的 `source_feature_math.py.proton_moments` 和 `source_reference.py.SiliconMask`，传入该事件绑定的三维几何，移除的只是新入口中的S2条件限制。数量、单位、输入r0/epoch、有限Si全时间未归一矩、原积分容差和refinement判据均不变。不读取实际BE、TCAD场、Qcol、DeltaV、bit响应或训练统计。新源合同/packet独立版本化，不登记到当前分发器。

8. 两bit使用同一个原事件源。重复seed的不同SN实现具有共同随机流，不能当成新增独立统计样本；候选保留seed/event及原operation身份，标明这种相关性。data建议未注册，后续划分须整组保护，不能借SN拓展跨越原留出。

9. 输入、语法和构造样例检查只能说明新接线可复算。没有多参数真实G4事件之前，不可能证明新源包的原生通路已通过；没有实际源场/BE/双载流子/匹配A0与细化证据，也不能宣布耦合资格、商业器件可靠性或PMI/R12修复。原生步骤仍由主代理在同一个原operation/owner/共享锁下实施。
