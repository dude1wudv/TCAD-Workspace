# 有限线多源接口 r2

这是旧 `source-probe` 之后的独立人工二维接口实验。生成器、审计器均不连接SSH、不启动求解器、不恢复任务、不写旧账本。19项上限计**实际TCAD尝试次数**，不是成功数；生成19项输入不等于获得重试权限。唯一调度者仍为主Agent，调用现有 `scripts/tcad.py`。

本目录中的 `source_contract.json` 是本轮固定源、ROI和验收阈值的依据。输出工程携带精确副本、源/实现/几何哈希及离线电荷账本。源码或契约变化后必须生成新输入目录；已存在目录不覆盖。以前 `build-dev` 中的开发输入不是冻结的正式输入。

## 执行接口

仓库根目录下运行；本节所有命令均为本地输入生成或审计，不启动TCAD。

```powershell
python -B experiments/dram-see-v4/source-interface-r2/build_interface.py plan
python -B experiments/dram-see-v4/source-interface-r2/build_interface.py build local_runtime/dram-see-v4/source-interface-r2/inputs/v4-source-interface-r2-a0-b1-base --case A0 --bit 1 --variant base
python -B experiments/dram-see-v4/source-interface-r2/build_interface.py check local_runtime/dram-see-v4/source-interface-r2/inputs/v4-source-interface-r2-a0-b1-base
python -B experiments/dram-see-v4/source-interface-r2/build_interface.py check-source --case A3
python -B experiments/dram-see-v4/source-interface-r2/test_interface.py
```

生成命令返回JSON：`status=OFFLINE_INPUT_CHECK_PASSED`、`solver_started=false`、`project`、`case_id`、`stored_bit`、`variant`、`manifest_sha256`、`offline_source_check`。`project.json`仅包含`sde`、`sdevice`两个既有runner步骤，声明原始曲线、最终TDR和五个生成场TDR。`--spec`只接受与对应预登记工况完全相同的源，防止在19项清单中偷偷换源。

工况名为`A0 A1 A2 A3 A4 A5 A6 A7 A8S2 A8S4`，数值变体为`base time mesh`；输出目录名必须含`v4-source-interface-r2-<小写工况>-b<0或1>-<变体>`，可追加后缀。只允许契约中的19个角色组合；不支持在该轮追加任意源。有限线核心支持显式归一化二维方向，源文件仍保留xyz，`dimension != 2`、`synthetic=false`、非零z及离面方向均拒绝。没有真实三维事件降维接口。

## 源、采样与空间证据

继承0.25µm栅长、5nm氧化层、1µm有效厚度、原电路/电容/材料/读出时序、Gaussian横向宽度0.03µm及时间核`s_hi=2ps`。显式HeavyIon参数沿用上一轮选择，包括`c_2=1,c_3=0,c_4=1`，不声称与安装默认值一致。该径向宽度与时间核仍是接口设置。

每个有限线段独立拥有电荷与step ID。A8沿同一路径均匀切2段或4段，每段电荷按长度分配，LET不重复整条径迹的电荷。解析定义使用半开区间；TCAD顶点端点的离散影响由A8比较测量，不能预先宣称完全等价。A3位于x=0：总规定电荷仍是1fC，预计算域内量0.5fC；不补回域外半量。

注入窗0.95–1.05ns的`MaxStep`为0.5ps；`time`仅将该窗细化为0.25ps。保持所有接受时间点的电流/电压输出，不用单独CurrentPlot时间表稀疏化器件电流。审计还检查**实际原始输出的间距**，deck写了MaxStep不代替输出验收。`mesh`把原网格尺寸因子改为0.5；其他数值和电路设置保留。五个生成场快照为0.995、1.000、1.005、1.010、1.015ns。

原生`HeavyIonGeneration`输出在每个接受时间点计算以下积分：全域；x=0.425两侧；x=0.395–0.455中心带；y=0.45和0.75划分的低/中/高三带；左侧再按y=0.6分上下。左+右、低+中+高、左下+左上+右均覆盖全硅域。中心带能发现A5误重合，左上下能发现A2倾斜被抹掉，A6左右积分的时间质心能发现延迟被丢掉。

采用Sentaurus Device W-2024.09 UG pp180–184的`Integrate(Name="G_..." Semiconductor Window[(x0 y0)(x1 y1)])`和全域`Coordinates`。二维原始积分单位为`µm²·cm⁻³·s⁻¹`，明确乘有效厚度1µm，再乘`1e-12 cm³/µm³`、电子电荷及fC换算；电子—空穴对不乘2。空间质心单位µm。每份审计保留全部原生dataset键，未知或歧义键拒收，不按列序猜字段。

`extract_fields.tcl`是可选的原生TDR后处理脚本，依据本机SVisual UG pp309–310、319：`list_fields`核实真实字段，再用`integrate_field -materials {Silicon} -window ...`提取ROI到`tdr-spatial.csv`。它不启动solver。现有runner没有SVisual步骤，主Agent可对已完成目录另行串行执行；本轮数值验收以原始PLT积分/质心为主，TDR提取不是放行前提。未实际提取时审计明确`tdr_field_extraction_verified=false`，TDR文件存在不等于场数值已被读取。无需GUI截图。

## 本轮门槛

离线对旋转矩形内高斯横向积分求解析解，仅沿径迹进行分段求积；256/512采样互查。闭合阈值`max(1e-6fC,0.1%×域内电荷)`，这是规定核函数的检查，不是TCAD结果。全域TCAD生成电荷与预计算域内量差≤5%。每个ROI占总量的比例与预计算比例差≤0.05，分区总和误差≤5%；全域源质心x/y误差≤0.01µm。总G波形按解析峰值归一化的误差≤5%，总量及有效ROI的时间质心误差≤0.5ps。ROI波形幅度另保存为诊断，不对小ROI追加未授权相对门槛。质心只在瞬时总G达到观察峰值0.1%时评价；有效ROI的积分占比下限0.1%预冻结。

A0也请求全部ROI，但不请求未定义的零源质心。若求解器完全不输出辐射字段，只接受“完整无源deck且请求已核对”的结构证据：`generated_fC=null`、`numerical_zero_observed=false`。不把缺字段补成测量零。有字段时要求九个ROI全齐且积分均≤1e-6fC；部分缺字段拒收。工程、有限完整曲线与电路验收照常执行。

A1/A4及A5/A7严格等价比较要求同一实际网格、同模型/时间契约，沿用旧门槛：Q差≤1e-4fC；生成曲线差≤成对峰值0.1%；电压差≤1e-5V；电流差≤1e-12A+成对峰值0.1%。A7须保留同一物理源名称及参数，仅反转输入顺序。

A8S2、A8S4分别以**本实现单段A1**及匹配A0为参照。时间/网格细化使用各自匹配的A0，不将不同数值基线的原始电压直接相减作判断。生成电荷变化≤基准生成量2%；从0.95ns到4ns的`Vsn`、`Vbl`扰动曲线差≤`max(1mV,成对扰动峰值5%)`。端电流和电荷积分是诊断项，不新增拒收门槛。不设置翻转标签。单项通过或一对细化通过均不声称完整网格/时间收敛或器件校准。

## 原始归档审计

输入为现有runner形成的完成目录，必须包含`manifest.json`、`inputs.tar`、`results.tar`、原始`run.sh`。审计复用旧只读tar/曲线解析及R50电路守恒函数，不调用旧审计入口或写旧账本。检查实际SSH退出码为整数0、归档内远端退出码0、原始完成标志、COLLECTED归档状态、输入/输出哈希、线程/锁约束、4ns终点及完整电压电流。未知原始退出码不能通过；恢复后的新码不能替代原始执行码。旧runner不单独保存归档传输退出码，该限制在工程证据中原样披露，不能伪造额外码。

tar不解压，预先检查成员路径与类型，拒绝路径穿越、链接、特殊文件和重复成员。失败返回JSON并以CLI退出1；输出目录必须为r2 local_runtime子目录且不覆盖已有`audit.json`。`circuit*.csv`、`device*.csv`保留完整原始/清理后曲线。

```powershell
python -B experiments/dram-see-v4/source-interface-r2/audit_interface.py audit <真实run目录> --project <冻结输入工程> --output local_runtime/dram-see-v4/source-interface-r2/audits/<run-id>
python -B experiments/dram-see-v4/source-interface-r2/audit_interface.py compare <A1-run> <A4-run> --control-a <A0-run> --control-b <A0-run> --mode equivalent --output local_runtime/dram-see-v4/source-interface-r2/comparisons/a1-a4-b1
python -B experiments/dram-see-v4/source-interface-r2/audit_interface.py compare <A5-run> <A7-run> --control-a <A0-run> --control-b <A0-run> --mode equivalent --output local_runtime/dram-see-v4/source-interface-r2/comparisons/a5-a7
python -B experiments/dram-see-v4/source-interface-r2/audit_interface.py compare <base-A1-run> <A8S2-run> --control-a <base-A0-run> --control-b <base-A0-run> --mode refinement --output local_runtime/dram-see-v4/source-interface-r2/comparisons/a8s2
python -B experiments/dram-see-v4/source-interface-r2/audit_interface.py compare <base-A6-run> <time-A6-run> --control-a <base-A0-run> --control-b <time-A0-run> --mode refinement --output local_runtime/dram-see-v4/source-interface-r2/comparisons/a6-time
```

返回`passed`、`status`、逐项`checks/errors`、原生字段键、空间/时间/电荷数值、完整曲线、哈希、适用边界。首次真实A1原始PLT核实的拼写为`IntegrG_<ROI> HeavyIonGeneration`及`IntegrG_Total X_HeavyIonGeneration`、`IntegrG_Total Y_HeavyIonGeneration`；`Integr`直接连接`Name`。审计按这些完整原生键识别，不用模糊子串或列顺序。`--field-map`先于自动缺字段判断处理，仍只允许对应角色的精确原生键；不能换量、交换x/y、映射同列到多个角色、遗漏已观察字段或用空映射伪装A0字段缺失。原始数值及单位不变。

首次A1字段识别失败报告及修复前实现快照保留于`local_runtime/dram-see-v4/source-interface-r2/audit-dev/field-name-fix-r1/before/`。修正仅涉及原生字段解析，冻结契约、builder、原工程与物理门槛均未修改；使用同一归档复验，不重跑A1。

离线反例覆盖：3D/离面/真实事件拒绝、重复step能量、错误LET、总量正确但轨迹重合、丢失延迟、质心偏移、缺空间字段、输出时间过稀、未知退出码、tar目录穿越/链接、输入篡改与不可覆盖。合成场仅用于这些软件断言，绝不作为真实TCAD通过证据。
