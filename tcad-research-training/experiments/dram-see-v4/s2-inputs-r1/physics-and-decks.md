# S2 物理卡、DC 与实际写读输入

这是离线输入说明。安装版本为 W-2024.09；本轮未调用 SDE、snmesh、SDevice、SVisual、Geant4 或编译器，也没有用版本命令签出许可。

## 冻结物理卡

`decks.py`只接受 r13 模型文件 SHA-256 `a89d30d0429defaa6dd491869470e168a6574125af1b8f27cb7689e4f8241481` 的内容。生成器拒绝修改后的模型，避免部分参数被硬编码忽略。受控自然语言修改接口不在本轮发布范围。

通过既有`tcad.py.connection()`的严格 SSH，只读安装目录中的两份参数卡；完整私有卡只存在被忽略的`local_runtime`审查包中。并非运行`sdevice -P`得到，也不称原文校准卡。

| 卡 | SHA-256 |
|---|---|
| Silicon.par | ce02ba3cc28d8b1319ae070315371469fc4f97c4834d9a72d23f99f686108790 |
| Oxide.par | 1fcb91c12e98e3969cc3fd3b9c6b76f09457d955ed42ad536ba1fd18a6ff23fb |

`physics.par`以`Material`内`Insert`插入完整卡，然后显式覆盖未命名 BTBT 过程参数。选择 Fermi、OldSlotboom、DopingDep/HighFieldSaturation/Enormal mobility、SRH(DopingDep)、Auger、Band2Band(Model=NonlocalPath)，300 K。BTBT参数为Apath=4e14 cm⁻³s⁻¹、Bpath=1.9e7 V/cm、Dpath=0、Ppath=0.037 eV、Rpath=0、MaxTunnelLength=1e−5 cm。值来自安装卡第一过程，现代键名依据同版本手册；无Postprocessing选项，要求参与连续性方程。模型名可查不代表新deck已由原生解释器接受。

对应本地 SDevice 手册：参数Insert p75；NonlocalPath与参数、反馈语义 pp553、562–566；e/hBand2BandGeneration输出 p566。提取工具只读手册PDF，局部摘录留在本轮runtime/private-manual，商业手册不入库。其余默认参数由卡SHA冻结，不在离线期调整使结果追赶文献。

## DC

两个偏置VDS=0.1/1.2 V分别从同一保存平衡态开始，先到VGS=−0.5 V及目标漏压，再扫描到1.5 V。请求每条201个等扫描参数输出点，另外保留求解日志。二维AreaFactor=0.02对应名义20 nm宽；三维AreaFactor=1。命名为source=SN、drain=BL、gate=WL、body=底接触，栅功函数4.6 eV。

预期`idvg_low_dc_des.plt`、`idvg_high_dc_des.plt`、`dc_final_des.tdr`、`dc_des.log`。输出后缀沿既有版本约定，新deck实际文件名仍须核对。报告Ion/Ioff、SS/gm/DIBL与文献差异，不将文献单一电流作为可调参数追赶的通过答案。

## 两bit写入、保持与读出

两角色唯一bit差异是BL写驱动0/1.2 V。共同SN=0.6 V仅用于平衡初始化，瞬态开始前`Unset(sn)`。没有以0/1.2 V强行设置存储节点代替实际写入，也没有额外SN泄漏支路。

| 时间/ns | WL及电路动作 |
|---|---|
| 0–2 | WL=−0.5 V，BL驱动=bit×1.2 V |
| 2–2.1，2.1–6 | WL拉至1.8 V，然后通过访问管写入 |
| 6–6.1 | WL回−0.5 V |
| 6.1–6.2 | BL驱动线性回0.6 V |
| 6.2–8.1 | BL预充；8.1 ns将rdrive由1 kΩ改为1e15 Ω |
| 8.1–20 | 保持；A0无粒子，仍保留与后续源角色相同的15 ns细步窗口 |
| 20–20.1，20.1–22 | WL拉至1.8 V并读出；取21.9–22 ns的BL时间加权平均 |
| 22–22.1，22.1–25 | WL关断并完成；无感放、刷新、恢复写 |

Cstore=20 fF、Cbl=200 fF、plate=0.6 V、body=0。BE积分；一般最大100 ps，0.1 ns边沿段最大10 ps；14.9984–15.0016 ns源窗最大0.04 ps，dt/2变体减半整条瞬态所有最大步长。`Plot Range`不指定Intervals，以保留实际接受BE端点；窗口左端为边界帧，不假定为有正时间宽度的源步。

`circuit.plt`保留所有器件端电流、两电容电流、BL驱动电流及SN/BL/WL/plate/drive电压；独立`i(access,sn)`与CstoreΔV做逐步KCL。`metrics.py`使用右端BE电流积分，电压采用分段线性插值和时间平均。读出边界不判成持久位翻转。

原G1门保持：6 ns写入bit0≤0.12 V、bit1≥1.08 V；8.1–19.9 ns保持漂移≤5 mV；8.1 ns预充误差≤1 mV；有符号读出裕量≥20 mV；逐BE KCL≤max(1e−4 fC,1%相关电荷尺度)。单个main包的候选功能指标不构成G1：仍需原生工程链和两bit各自的main/h2/dt2比较。

数值控制固定为Digits=5、e/h ErrRef=1e7 cm⁻³、Iterations=30、Notdamped=100、初始化Coupled上限100、ExitOnFailure。DC使用ParDiSo；混合瞬态使用Blocked/SubMethod=ParDiSo。DC扫描参数的Initial/MinStep为0.001/1e−8，settle/scan MaxStep分别0.02/0.005，Increment=1.3。瞬态MinStep=1e−18 s、InitialStep=min(MaxStep/10,1e−13 s)、Increment=1.3。这组实现控制由独立扫查发现账本漏列后补记为A018，不冒称事前登记或原生稳定性已证；失败时按原停止/纠错规则处理，不自动放宽。

## 实施边界

首4角色为D2→D3→A0-main-b0→A0-main-b1。D2/D3各包含唯一mesh构建；两个A0只有SDevice步骤，待引用同一未来D3的实际mesh和日志，不伪造TDR/hash、不重复建mesh。每角色只有`project.review.json`，没有runner可直接读的`project.json`。执行包必须另发布，不能简单改名启动。

`mesh_resource_guard.py`检查未来原生mesh日志/哈希和远端资源，当前所有策略`approved=false`、预测为空，必定拒绝。它不替代唯一调度者的本机20 GiB、远端8 GiB、内存4 GiB、总存储160 GiB、共享锁/原owner、预算预约检查。新网格节点与峰值内存未知；不套用旧几何410帧预测，不放宽1/5/40 nm网格。
