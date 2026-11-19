# r3：单个A1测量修订

只构建A1、bit1、base候选。新目录不建立19角色矩阵或新runner，不重置预算。所有SDevice实际尝试仍由root的全局调度登记，累计上限19，r2已使用2次；下一次不论成功失败均为第3次。旧r2的输入、契约、失败及后处理证据保持冻结。

## 本次实际改变与未决问题

物理输入从已冻结r2 A1工程逐字复制：几何、材料、电路、网格、位状态、源位置/长度/方向/电荷、Gaussian横向宽度及`s_hi=2ps`全部相同。完整device deck只替换CurrentPlot观测段。`matching_contract`内容及哈希完全不变，源spec仍代表同一个人工事件；重测不是新的独立粒子样本。

输出并列四条路径：

1. 原档真正已成功的命令`HeavyIonGeneration(Integrate(Semiconductor))`，原生列`IntegrSemiconductor HeavyIonGeneration`。输出列名不是命令语法。
2. `G_Plain`：具名无Window积分及Coordinates，仅作测量绑定诊断。
3. `G_2DTotal`：原二维角点全域Window，仅诊断。其零值不补理论值，也不拿其他路径代替。
4. `G_Total/Left/Right/Center/Low/Middle/High/LowerLeft/UpperLeft`：显式三维角点z=±0.5µm窗口，是r3预声明空间验收路径；Total带Coordinates。它仍是二维器件，没有创建三维源或模型。

固定300K的温度在无Window、二维Total及九个三维角点窗口积分后除300，作为独立域面积诊断。deck严格使用SDevice UG p273明确示例的`CurrentPlot { Temperature(...) }`，不把数据集别名当命令。未添加热输运模型或Tcl回调。温度积分的原生列名只允许LatticeTemperature/Temperature这两个精确后缀且拒绝歧义。r2离线函数仅复用空间积分，旧时间窗口字段被移除；r3按正确CDF另算0至4ns的归一化质量。

UG pp180–181、p1618表208支持三分量角点语法及1D/2D/3D窗口，但未明确说明非零第三角点在二维网格上的内部处理。SVisual已在相同二维TDR中接受含z边界窗口，但不能证明SDevice相同。因此这是受控测量诊断假设，**不是已证实根因或修复成功**。r2原生TDR的Center/Total约0.783205，与解析0.842701差约0.0595，超过冻结0.05；r3不能只恢复总量就宣称空间通过，也不把后处理节点场积分与求解内积分混作一种测量。

## 时间oracle及积分修正

实际查看本机SDevice UG p813公式(810)像素确认分母为`√2*s_hi`，故时间Gaussian标准差为`s_hi`。旧r2解析oracle误写为`2*s_hi`；这里修正的是观测预期，TCAD源参数没有改变。`oracle.py`实现原公式归一化、稳定erf/erfc区间质量及BE步平均值。

r2五个实际TDR积分的比值，与原日志成功BE步及PLT精确时刻所定义的步平均核匹配，未拟合sigma、t0或偏移，最大相对差约3.5e-12。文档p812仍称该变量为instant generation，已读章节未找到步平均输出的显式保证；该时间语义来自独立原始数据证据，r3 CurrentPlot必须再次与每个实际接受步的平均核匹配，不能填充或修正实测值。

电荷主积分为`sum(G_i * (t_i-t_(i-1)))`，并另报旧梯形积分。**时间质心使用BE区间中点**：`sum(G_i * dt_i * (t_i+t_(i-1))/2) / sum(G_i*dt_i)`，不把右端输出时刻直接当发生时刻，避免额外约0.25ps偏移。空间质心的预期也按对应步平均生成权重计算。

r3后处理TDR元数据只有state_0/index1，未给内部直接时间戳。保存时间的证据仍是原始成功BE步、Writing日志与PLT对应时刻，而不是文件名/请求时间或拟合出来的时间。五快照保留，但不足以替代完整时间曲线。

## 门槛与控制复用

保留原总量5%、ROI占比0.05、分区5%、空间质心0.01µm、时间质心0.5ps、波形5%及既有等价/细化阈值。只允许三维角点窗口作为本修订空间验收通路；即使legacy总量通过，主窗口失败仍失败。legacy总量也独立要求5%。具名无Window和旧二维Window保留诊断；区域面积没有追加新数值拒收阈值。

本轮不运行细化/分段，契约继续携带原2%生成电荷、`max(1mV,扰动峰值5%)`约束，不能将单次A1通过表述为收敛。

审计必须显式提供旧r2 A0：只读调用已冻结的原r2审计器，要求原审计通过、确为A0 bit1 base、`matching_contract`哈希和内容完全相同、实际mesh哈希完全相同，且r2/r3各自源契约和代码哈希均独立验证。旧r2 A1失败不能当控制或被提升为通过。控制复用会明确标注，避免仅更改观测输出就再求解A0。

## CLI

在仓库根目录运行，只生成候选和做离线检查：

```powershell
python -B experiments/dram-see-v4/source-interface-r3/build_interface.py build local_runtime/dram-see-v4/source-interface-r3/inputs/v4-source-interface-r3-a1-b1-base --reference-project local_runtime/dram-see-v4/source-interface-r2/inputs/v4-source-interface-r2-a1-b1-base
python -B experiments/dram-see-v4/source-interface-r3/build_interface.py check local_runtime/dram-see-v4/source-interface-r3/inputs/v4-source-interface-r3-a1-b1-base
python -B experiments/dram-see-v4/source-interface-r3/test_interface.py
```

build/check返回`OFFLINE_INPUT_CHECK_PASSED`、case/bit/variant、`measurement_revision=3`、物理matching哈希、输入manifest哈希和`new_budget_created=false`。已有输入目录拒绝覆盖。

root唯一调度完成后，对同一真实归档审计，不重发求解：

```powershell
python -B experiments/dram-see-v4/source-interface-r3/audit_interface.py <真实r3-run目录> --control <真实r2-A0-run目录> --project local_runtime/dram-see-v4/source-interface-r3/inputs/v4-source-interface-r3-a1-b1-base --output local_runtime/dram-see-v4/source-interface-r3/audits/<唯一新审计目录>
```

审计沿用严格退出码、归档安全/哈希、串行原runner约束、4ns完整曲线及原电路守恒；输出失败、原生字段、全部可计算源项指标、域面积诊断、控制复用证据和完整电压电流CSV。未知退出码/缺字段失败，缺测不生成理论曲线。输出独占创建，不覆盖历史审计。没有翻转标签或训练。

离线反例包括正确σ及5ps比例、非均匀BE矩形积分与梯形差别、erfc尾部独立数值求积、五实测TDR比值、Center超门槛、主ROI零但legacy有值仍失败、缺legacy/温度字段、禁止复用失败r2 A1及不匹配控制、候选仅改变观测段。合成软件夹具不是TCAD验收证据。
