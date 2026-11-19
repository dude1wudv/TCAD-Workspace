# 连续项目质子候选：仅主代理调度原生执行

以下首轮准备与检查记录作为历史保留。当前 S2 运行与事件源入口见 [SOURCE-BUNDLE.md](SOURCE-BUNDLE.md)，独立有限 Si/时钟审计见 [SOURCE-REFERENCE.md](SOURCE-REFERENCE.md)。Geant4 和 R12 均已由主调度实际编译并收集；R12 编译验收在 `local_runtime/dram-see-v4/continuous/proton/r12-native-build-review-r1/report.md`。这些编译不代表原生源资格；本页下方的“尚未执行/未交付”描述首轮交付时点。

预 TCAD 的13维源摘要与两 bit 共享接口见 [SOURCE-FEATURES.md](SOURCE-FEATURES.md)。该接口分别使用真实 α LUT 核与质子段卷积核，仅支持给定源摘要及器件条件的响应代理。

本目录生成输入，不创建 runner、operation、队列或后台进程。当前 Goal 的持续授权直接用于新的准备入口；不读取旧预算、逐轮 release 或签字字段，不写伪造 approved。原 R10 失败、R12 候选、冻结输运和账本均只读保留。

当前推荐先运行 BCAT Geant4 编译包，再用一个真实质子事件接通 HeavyIon 备选。R12 编译包可独立安排，但 APD 基底的正确 dataset、单位和 tag 路线尚未解决，不能直接声称可用，更不能称 PMI/R12 已修复。

## 已生成输入

- `local_runtime/dram-see-v4/continuous/proton/transport-build-r2/`：Geant4 编译任务，尚未执行。
- `local_runtime/dram-see-v4/continuous/proton/r12-build-r2/`：原 R12 源文件逐字节复制、Cmi 编译、原六向量与12项上下文探针，尚未执行。
- `transport-build-r1/`、`r12-build-r1/` 为初次准备历史，未执行；r1 几何探针包含表面点，已在 r2 修正。不要执行旧输入。

`task.sh` 只含该包声明的编译/测试命令。现有 `transport-probe/operation.py` 要求输入位于自身 runtime，主代理在持有原 owner 并确认原作业状态后，将选中包按原方式复制到 `local_runtime/dram-see-v4/transport-probe/inputs/<unique-label>/`，再调用原 operation。这里不执行该复制或调度。

```powershell
python -B experiments/dram-see-v4/transport-probe/operation.py cgoal-bcat-transport-build-r2 local_runtime/dram-see-v4/transport-probe/inputs/cgoal-bcat-transport-build-r2
```

原编译 operation 完整归档后，准备一个事件的输入；实际 seed/event count 是该批次的数据定义，不是调用额度。`--events 0` 表示原生初始化/几何核验，正整数表示真实事件数。能量与角度在运行请求中保存，无须因改变它们重新编译。

```powershell
python -B experiments/dram-see-v4/continuous/proton/prepare.py transport-run --operation local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-transport-build-r2 --output local_runtime/dram-see-v4/continuous/proton/proton-e5-a0-r1 --label cgoal-proton-e5-a0-r1 --seed 2026101701 --events 1 --energy 5 --theta 0
```

该输入再由主代理通过原 operation 执行。初始化、事件表、完整 steps/tracks/parent links、真实产额/材料/过程 inventory 和退出均保留；沒有新初级粒子种类，H臂沿用 QGSP_BIC+EM Opt4，E臂是相同几何的EM对照。保留原参考物理列表的次级中子处理，但不增加中子初级研究。

原 Geant4 成功归档后生成事件源：

```powershell
python -B experiments/dram-see-v4/continuous/proton/couple.py --operation local_runtime/dram-see-v4/transport-probe/operations/cgoal-proton-e5-a0-r1 --event-id 0 --output local_runtime/dram-see-v4/continuous/proton/proton-e5-a0-event0-source-r1 --epoch-s 1.5e-8
```

输入需原 archive 身份、三项真实退出0、完整事件、BCAT原生材料探针、steps与event Si能量闭合。所用输出按原tar成员核对；缺失或改动拒绝。空沉积事件生成结构无源输入，不丢弃事件或将缺字段填成测得零。

## 几何、源数学和边界

BCAT圆底槽/STI采用与 `s2-inputs-r1/geometry.py` 相同的解析几何，Geant4 Boolean solids原生 `Inside` 对照独立Python材料探针。坐标为恒等变换 `x,y,z_depth`、单位µm。默认charged max step=0.002µm、production cut=0.001µm，分别通过CLI可做数值收敛，不是已收敛结论；范围阈值不是用户杀轨迹。原合同 Si=2.33、SiO2=2.2 g/cm³。**GateVoid保留vacuum**，原因是电学理想金属边界未指定输运金属；不能据此声称含真实金属散射。

原 Geant4 的全部步骤仍原样保存。耦合读取所有正Si电离能 `edep-NIEL`，用3.6eV/电子空穴对换成电荷，保留零路径/零弦长沉积，不按粒子或结果删选。`sources.dat`保留原R12核格式，w=0.03µm、sigma=2ps。

HeavyIon备选将每段的3D各向同性Gaussian卷积沿轴写成解析erf纵向剖面，点沉积则为纵向Gaussian；再用原生 `Length`/`LET_f` 数组和横向Gaussian表示。全部命名源在同一次Poisson/Electron/Hole联立求解中激活，没有步后回填。源时间随段长度变化用等时间子段的中点近似，默认每子段跨度≤sigma/8；纵向节点间距≤w/12，尾部在两端8w截断且不重归一。文件同时保留原分配电荷和表格梯形积分电荷，不能把二者混称测得源电荷。

这是一条明确的源接口修订：有限LET插值、尾部截断和时间中点离散与精确R12核有差别。加密LET节点/时间子段并与精确源核比较，随后核对原生源积分、真实接受BE区间、波形/质心/ROI、双载流子生成和匹配A0，才能判断是否合格。不能伪写PMI time/dt/type，HeavyIon使用它自身的原生源场证据。源末时刻/所需窗口保存在contract，晚二级粒子不能裁掉；若超出器件求解窗口应扩展对应匹配求解。

源片段 `heavyion.physics.inc`、`source.par`、plot/currentplot片段由主代理加入正确的3D器件角色；A0不激活这些源。源场依赖 `HeavyIonGeneration` 的原生实测；已有α审计的期望公式不适用于质子任意多段，不能直接沿用其通过结果。尚未交付任意Si掩膜的独立源积分器，此项是正式器件资格前的真实缺口。

## 当前验证

11项定向Python检查通过：点/斜段/长段电荷、独立中点积分对照erf公式、时间质心、零长度和能量转换、重复步骤/非有限/错误核拒绝、结构无源、原生provenance/祖先记录保留、BCAT探针、旧预算入口不依赖。日志在runtime的 `offline-tests-r2.log`，退出0。初版非均匀端帽节点导致2.5fC样例的梯形积分偏差1.2767100818766863e-05fC；改成均匀节点后原断言通过，没有放宽断言或重归一电荷。

**未做**：SSH、编译、Geant4运行、SDevice运行、原生场提取、源资格、器件响应。全部候选仍 `native_qualified=false`，R12仍未证修复。可编译性/10.7.3 ABI以真实编译日志为准。

现有同版HeavyIon语法依据为本机 `local_runtime/dram-see-v1/heavyion-reference.txt` pp812–816；R12依据与失败指向旧 `PMI-NATIVE-RESULT-R10.md`、`source-update-r12/DECISIONS.md` 和 `source-route-r12/apd-preparation-review/report.md`，不重复旧排查。Geant4 Boolean/placement API核对参考[官方几何文档](https://geant4.web.cern.ch/documentation/pipelines/master/bfad_html/ForApplicationDevelopers/Detector/Geometry/geomSolids.html)；原生10.7.3兼容性仍待编译。
