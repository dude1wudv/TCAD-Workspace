# 粒子输运与联合源实施设计

2026-10-12。这里给出下一步应实现和核查的内容，不是已经运行通过的结果。

## 工具依据与先决条件

现有 [环境记录](../../dram-see-v1/environment.md) 和 [编译输出](../../../local_runtime/dram-see-v1/compile-geant4.stdout.txt) 证明历史使用Sentaurus W-2024.09、Geant4 10.7.3；当前未连接VM，未探测许可或编译。本地 [geant4-env.sh](../../../local_runtime/dram-see-v1/geant4-env.sh) 仅明确配置G4EMLOW7.13、G4ENSDFSTATE2.3。头文件包含某物理列表不能证明相应数据已安装。

| 候选 | 本轮依据 | 在v4中的位置 |
|---|---|---|
| QGSP_BIC + EM Opt4 | [10.7.3列表源码](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/physics_lists/lists/src/QGSP_BIC.cc)及[强子构造器](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/physics_lists/constructors/hadron_inelastic/src/G4HadronPhysicsQGSP_BIC.cc) | 首轮H臂候选；低能proton采用Binary，不等于目标DRAM中已验证准确 |
| FTFP_BERT + 相同EM设置 | [10.7.3构造器](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/physics_lists/constructors/hadron_inelastic/src/G4HadronPhysicsFTFP_BERT.cc) | 完成主链后在代表能量做模型敏感性检查，不立即扩全矩阵 |
| QGSP_BIC_HP / AllHP | [10.7.3 AllHP源码](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/physics_lists/constructors/hadron_inelastic/src/G4HadronPhysicsQGSP_BIC_AllHP.cc) | HP主要指低能中子；AllHP对质子包含<200 MeV的ParticleHP。数据和同位素覆盖未核实，不能启用后忽略缺包 |

需只读核查PhotonEvaporation5.7、G4PARTICLEXS3.1.1等实际所需数据；HP/AllHP另查G4NDL及ParticleHP相关数据，放射性衰变若启用另查对应依赖。版本清单参考 [Geant4 10.7.3发布页](https://geant4.web.cern.ch/download/10.7.3.html)，以实际构造器与启用过程确定依赖。未找到配置证据并不等于已证明远端缺包；若确认缺包，记录缺项后再处理安装授权。

QGSP_BIC的默认电磁构造器和0.7 mm默认cut与旧Opt4/0.01 µm设置不同。H臂必须显式替换为同一EM模型并显式设置cut，输出实际过程清单确认没有重复注册；最终API调用在实现时依据10.7.3确认，此设计不发布未经编译核验的替换代码。

## 四种分辨率分别检查

production cut影响是否显式产生次级，由距离按材料/粒子转换为能量阈值；它不是所有低能粒子的终止阈值，也不是最大步长。最大step影响输运采样，源分段尺度影响映射，TCAD网格/时间步影响电学离散。一个变小不能代替其他项的检查。[Geant4阈值说明](https://geant4.web.cern.ch/documentation/dev/bfad_html/ForApplicationDevelopers/TrackingAndPhysics/thresholdVScut.html)

旧cut=0.01 µm、step=0.02 µm只可用作接口比较起点，不能作为95nm器件收敛证据。10.7.3的StepLimiter默认针对带电粒子；如要求中性粒子受最大step限制，需要另外明确并核验。[10.7.3源码](https://raw.githubusercontent.com/Geant4/geant4/v10.7.3/source/physics_lists/constructors/limiters/src/G4StepLimiterPhysics.cc)

首轮保持各设置固定；代表案例再单独细化cut、step、源分段、网格和时间步，记录显式次级数、电离分布、生成量、连续响应和耗时。改设置后不要求同seed逐步轨迹相同。

## 先验证内置多源

依据本地指南p813–816（见 [heavyion-reference.txt](../../../local_runtime/dram-see-v1/heavyion-reference.txt)），首版候选是一个事件生成多个命名HeavyIon；所有源在同一瞬态问题中求解。命名源有对应参数文件要求；StartPoint为单向径迹，Location的双向含义不可混用。PicoCoulomb模式的LET为pC/µm，长度/宽度为µm，时间仍用s。

第一步只做A0、A1、A4，证明零源、单源、两个重合半量源的积分和生成场一致；随后才扩展位置、裁剪和错时。全事件多源可先用逐步有限直线段表达；后续把共线段压缩为LET数组时，数组值是插值节点，不是每段能量。先核算分段能量，再构建函数，不能把沉积数直接塞到LET数组。

边界源要区分两类验收：若合同目标是全Q入硅，而核函数被截去一半，应检出失败；若预先定义了域内/域外账本，则检查实际积分是否等于预计算的Qin。不得根据TCAD输出回调目标Q让自己通过。这里的场线性相加不代表器件响应线性相加。

## 可先冻结的接口测试数值

以下取自历史0.25 µm模型的几何，仅作接口测试，不表示90nm器件参数。拟使用v4独立副本、硅二维域0.85×1.2 µm、有效厚度1 µm、Q0=1 fC、长度0.6 µm、宽度参数0.03 µm、Time=1 ns；源时间核及其参数仍须核验。旧模型/原件不改。

| 工况 | 几何/时间设计 |
|---|---|
| A1 | 起点(0.425,0.3) µm，方向(0,1)，终点(0.425,0.9) µm |
| A2 | 中心不变；方向(−sin30°,cos30°)，长度仍0.6 µm；实际端点见design-register.json |
| A3 | 径迹轴移到x=0；独立预计算横向核裁剪，作为边界负向检查 |
| A4 | 同A1的两个命名源，各0.5 fC，同时1 ns |
| A5 | 两条轴x=0.325/0.525 µm，各0.5 fC，同时1 ns |
| A6 | 同A5；第二源时间1.01 ns，延迟是软件检查值，不是实际次级到达时间假设 |
| A11 | 低—高—低三角形LET(s)，两端0、中点峰值2Q0/L，总积分Q0 |

真实输运事件使用轨迹/步的实际时间，不能套用A6的人为延迟。宽度与时间核是暂定接口设置，新器件的物理值另有依据；三维A9需三维测试体，不能在二维deck中假装完成。

## 核事件的新能量账本

旧 [event_audit.py](../../dram-see-v3/event_audit.py) 固定5 MeV并限制电离量+NIEL不超过初级动能。含核反应时，反应Q值/核状态变化可能参与能量平衡；不能把这个上界机械迁移到v4。新验收分层：

1. 每步总沉积、NIEL与电离分量非负且定义一致；分步之和与事件汇总闭合。
2. 每份电离沉积只能进入一个源账目，域外/其他材料单独记，不重复扣NIEL或重复计次级动能。
3. 完整全局能量平衡需记录入射、逃逸、沉积和适用的静质量/核状态项后再制定；记录不足时不能声称全局能量闭合。

核后代按creator process和祖先链标识，原初质子核相互作用前/后的沉积另分段；track_id=1不意味着一直未受核过程影响。H−E的分布差包括核过程改变初级路径的影响，不能把它严格等同“核次级贡献电荷”。

微米薄硅探针未出现核事件时，先看过程注册与数据，不否认机制。必要时另设明确厚靶witness检查记录链，其结果不得混入DRAM事件率或训练数据。任何扩大搜索都单独登记，不靠反复改seed挑一个漂亮案例。
