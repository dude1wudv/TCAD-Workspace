# R13 器件证据：常规非对称结 BCAT 代表单元

任务 `R13-BCAT-EVIDENCE`；取证时间 `2026-10-16 UTC`。状态：**原文取证与选型建议完成，待主代理验收；未建模、未编译、未运行、未校准。** 本文只为新模型合同提供输入，不授予执行预算。

## 1. 选定依据与命名

建议选 **Lee 等，Electronics 2020, 9, 1908，Figure 2(c) 的常规非对称结 BCAT**，建成“公开文献支持、缺失项显式假设的 BCAT 1T1C 代表模型”。该图是文章用于比较的常规结构，**不加入 Figure 2(e) 的 Pi 埋置绝缘层**，也不继承 Pi 结构的改进百分比或创新归属。

- Lee, J.-s.; Park, J.-h.; Kim, G.; Choi, H. D.; Lee, M. J. *Partial Isolation Type Buried Channel Array Transistor (Pi-BCAT) for a Sub-20 nm DRAM Cell Transistor*. DOI：[10.3390/electronics9111908](https://doi.org/10.3390/electronics9111908)。[出版者页面](https://www.mdpi.com/2079-9292/9/11/1908)、[原版 PDF](https://mdpi-res.com/d_attachment/electronics/electronics-09-01908/article_deploy/electronics-09-01908.pdf)、[XML](https://mdpi-res.com/d_attachment/electronics/electronics-09-01908/article_deploy/electronics-09-01908.xml)。
- 选它是因为正文给出垂直埋栅/结深、峰值掺杂、Gaussian 剖面类别，并给出常规对照的偏压、电流、SS、gm 与 DIBL；采用 3D Sentaurus。它仍**没有完整公开输入 deck，也没有足够信息支持原文数值的严格复现**。
- Kim 等 2024 文章保留为更先进尺寸背景及结构对照：*Mitigating WL-to-WL Disturbance in Dynamic Random-Access Memory (DRAM) through Adopted Spherical Shallow Trench Isolation with Silicon Nitride Layer in the Buried Channel Array Transistor (BCAT)*。DOI：[10.3390/electronics13040681](https://doi.org/10.3390/electronics13040681)。[出版者页面](https://www.mdpi.com/2079-9292/13/4/681)、[原版 PDF](https://mdpi-res.com/d_attachment/electronics/electronics-13-00681/article_deploy/electronics-13-00681.pdf)、[XML](https://mdpi-res.com/d_attachment/electronics/electronics-13-00681/article_deploy/electronics-13-00681.xml)。其主结果为 SILVACO 中的 PGE 分析，Figure 3 明称 2D 结果；虽有 3D 结构示意，不能据此认为提供了完整的可运行 3D 单元。
- 两文都不能证明商业 LPDDR5/6 工艺复现。`sub-20 nm`、`10 nm node` 只保留为原文技术背景标签；它们不是已知物理栅长、fin 宽、STI 宽或 pitch。两文的数值不拼成一个原文模型。

## 2. 2020 常规基准：可直接采用的证据

表中“直接”指原文正文/表格给数，不等于本项目已验证。所有深度以原文接触表面为基准；工程坐标约定另见第 4 节。

| 项目 | 原文值/定义 | 原文位置 | 使用边界 |
|---|---|---|---|
| 结构分支 | Asymmetry junction BCAT | p2 §2，p3 Fig.2(c) | SN 侧浅结、BL 侧深结；无 Pi 埋置绝缘层 |
| 求解平台 | 3D Sentaurus TCAD | p2 §1 最后一段 | 未给版本、网格、完整物理模型、求解器/收敛设置 |
| 掺杂形状 | Gaussian | p2 §1 最后一段 | 未给峰位置、sigma、横向扩散、物种与背景浓度 |
| gate depth | 80 nm | p2 定义，p3 §2 Fig.2(c–e) 前段 | 接触表面至埋栅顶端；不能写为沟道长 |
| gate recess depth | 150 nm | p3 同段 | 需在几何合同中明确是原图的槽底深度参照，不用缩放节点代替 |
| BCAT 峰值掺杂 | 1.45 × 10²⁰ cm⁻³ | p3 同段 | 属 Fig.2(c–e) 的 BCAT；不采用 Fig.2(a,b) 的 1.05 × 10²⁰ cm⁻³ |
| SN 短结深 | 82–92 nm | p2 分支定义、p3 数值 | 原文为范围，没有给唯一值及空间轮廓；不可把端点当独立工艺样本 |
| BL 长结深 | 134–141 nm | p2 分支定义、p3 数值 | 同上 |
| 半导体 | Silicon | Fig.1、§3 的 Si/绝缘层论述 | n 型接触区、p 型体区可从 Fig.5/6 讨论识别；具体掺杂物种未给 |
| Ioff 基准 | 5.95 × 10⁻¹⁴ A | p3 §3 第1段 | 对应常规 Asymmetry BCAT，不是 Pi 的 2.54 × 10⁻¹⁴ A |
| Ioff 偏压 | VGS = −0.5 V，VDS = 1.2 V | p4 Fig.3 蓝轴/图例 | 图像目视核对；源/body 的绝对电势未明确给出 |
| Ion 偏压 | VGS = 1.0 V，VDS = 0.1 V | p4 Fig.3 黑轴/图例 | 不是 1T1C 写入字线脉冲或存储节点供电规范 |
| Ion 图读 | 约 (2.79 ± 0.03) µA | p4 Fig.3 的 Asymmetry 黑方点 | 手工栅格图读，±0.03 µA 是保守读图范围而非统计标准差；不设精确拟合门 |
| Id–Vg 扫描 | VGS 从 −0.5 到 1.5 V；VDS = 0.1/1.2 V | p4 Fig.4 轴和图注 | linear/log 两条测试偏压；不是公开原始曲线数据 |

**更强的同结构系列证据**在 p12 Table 1（XML id `electronics-09-01908-t001`），常规 Asymmetry BCAT 行为：

| 原文 gate depth | SS | gm,max | DIBL |
|---|---:|---:|---:|
| 70 nm | 65.0 mV/dec | 7.22 µA/V | 1.81 mV/V |
| 80 nm | 65.4 mV/dec | 7.40 µA/V | 3.63 mV/V |
| 90 nm | 66.0 mV/dec | 7.64 µA/V | 4.73 mV/V |

Fig.5 的 gm 图例给 VDS = 0.1 V。SS 提取区间、阈值电流准则、DIBL 提取细节和温度没有完整披露，故这些数字是**有条件的文献比较锚点**，不是无需模型校准即可承诺的通过阈值。Table 1 中 Pi 的 Ion 和 80% 比值只能反推出约 2.7625/2.8125/2.8875 µA 的常规 Ion；比值及电流均已取整，不能把这些小数当原文精确值。基准 80 nm 反推值与 Fig.3 图读也提示不能设置过窄的拟合容差。

## 3. 缺失项与不能隐含的假设

| 未给出的关键输入 | 核查结果 | 新合同应如何处理 |
|---|---|---|
| WL 金属横向宽、平面 Lg、pitch | Fig.1/2 无数值横向标尺 | 全部显式工程假设；不由 sub-20 nm 赋值；不从图像宽高比推出精确尺寸 |
| SN/BL 接触宽、active/fin 宽、器件总 x/y 尺寸 | 未给 | 明确参数及接触面；3D 电流是 A，不能任意挤出宽度后要求匹配原文绝对电流 |
| STI 宽/深、fin 暴露高、侧栅伸展、圆角半径 | 未给数值 | 3D 结构合同必须给出；禁止把 2024 的 Dfin=20 nm 当 2020 值 |
| gate oxide 厚度、具体介质、栅材料/功函数 | “gate oxide”有名，无可复建参数表 | SiO2、金属/功函数如采用，均为工程假设；Pi 埋置绝缘层为 SiO2 不证明所有 gate oxide 的厚度/工艺 |
| p-body 浓度/剖面、掺杂物种、Gaussian 宽度/峰位置 | 未给 | 先冻结名义值与实现公式；不能仅靠峰值加结深范围唯一反演 3D 剖面 |
| SN/BL 精确结深 | 仅给范围 | 若取中点 SN=87、BL=137.5 nm，须标“范围中点工程选择”，不可标“文献精确值” |
| 接触模型、body 偏压、温度 | 未给 | 合同独立指定；300 K、ohmic、body=0 V 若采用均属假设 |
| mobility、SRH、Auger、BGN、BTBT、量子/界面模型及参数 | 讨论 BTBT/GIDL，未披露完整模型卡 | 用当前安装版本支持且可审计的物理集合，保存参数；本轮未验证任何 native 语法 |
| 存储电容 Cstore、位线 Cbl、plate 电压 | 未给 | 文章研究访问管，不提供完整 1T1C 电路；必须独立假设/取证并记来源，不从 Io 或 LPDDR 速率反推 |
| 写0/1、保持、预充、读取时序与 sense 判据 | 未给 | 独立电路合同；原文 DC 曲线不代表可保持/可读写，更不提供持久位翻转判据 |
| 实验校准和源 deck | 未取得，正文仅仿真对照 | 不能称经过商业芯片实验校准；不因匹配单个 Ion 就认定模型真实 |

这些缺失不妨碍建立明确标为“代表模型”的离线参数合同，但阻止“原文精确复现”和“商业 LPDDR5/6 复现”两种表述。工程假设的科学有效性仍须靠新模型自己的无粒子、网格、时间、端电流和读写/保持检查。

## 4. 几何合同可采用的坐标与三个尺寸点

原文 p2 明确 Fig.2 为 `y=0` 的 `x–z` 剖面。推荐合同定义：`x` 从 SN 经过埋栅槽指向 BL；`y` 为有限 active/fin 横向宽度方向，字线跨 active 方向也须在版图映射中明确；`z_depth≥0` 从 SN/BL 接触表面向硅内取正。`z_depth` 是便于输入审计的深度坐标，**不是声称原图 z 箭头也向下**。转换至 SDE 和 Geant4 坐标须保存单一明确变换。

Fig.1 是局部三维示意，Fig.2 是中心截面：能确认埋栅绕过槽底、SN/BL 在两侧；无法从它们确定 fin 两侧 STI 的边界或深度。不得将 Figure 2 的平面挤出默认视为已复原三侧栅 BCAT。正式 3D 几何须另列 y 方向 fin 宽、侧栅暴露高度、STI 与边界，逐项标假设并留三方向剖面验收。

同篇同族最有依据的三个尺寸点是**埋栅顶深轴**，不是工艺节点轴：

| 点 | gate_top_depth | 固定 recess 时的垂直金属跨度 | 证据/假设边界 |
|---|---:|---:|---|
| S1 | 70 nm | 80 nm | gate depth 为 Table 1 直接值；recess 固定 150 nm 是本项目参数化约定 |
| S2 基准 | 80 nm | 70 nm | gate/recess 均由 p3 直接给出 |
| S3 | 90 nm | 60 nm | 同 S1 |

跨度只按 `150 nm - gate_top_depth` 派生，**不等于沿槽的电学有效沟道长**。建议其余横向长度、掺杂剖面、结深、氧化层、电容和偏压先固定；这是一条可审阅的单因素工程规则，不是文章披露完整 scaling law。三点各做独立无粒子准入。若 S1/S2 训练、S3 留出，可称该显式深度参数上的外推；不可称完成先进商业节点外推。课程若要求横向尺度也变化，应另建立有界工程轴和预算，不在此自动追加第四点或全部等比缩放。

## 5. 2024 参数确已取到，但不混入 2020 基准

2024 p3 Table 1（XML id `electronics-13-00681-t001`）已与 PDF 目视对照：侧/底栅氧厚 8/6 nm；Wsi=23 nm；WSTI=28 nm；WAWL=WFPWL=12 nm；Dfin=20 nm；BL=1 V；AWL 与 FPWL 的 on/off 均为 3/−0.2 V；substrate=−0.6 V。Figure 2 将 Dfin 标在 AWL 与 FPWL 槽底的深度差位置，**不是整段槽深或横向 fin 宽**。Wsi 位于图中的 CAP 接触侧硅段；不能未经 3D 坐标核对直接把它当另一轴的有限厚度。

2024 仍未给常规基准的完整掺杂数值、结深、绝对槽深、全 3D 横向尺寸、完整物理参数与 Cstore/Cbl。§4.3.2 还说明为消除 trap 引起的阈值变化调整了掺杂，却没有给出可复建数值。Figure 3 的恒流阈值点是 10⁻⁷ A；它与 2020 的阈值提取不能无条件等同。其 2 nm Si3N4、编程时间及改善幅度属于提出的改进结构，均不用于本项目常规基准。2024 适合支撑“现代 BCAT 仍值得研究”与将来结构扩展，不适合本轮把缺失的 2020 参数补成伪同源工艺。

## 6. 已做检查、原档与移交

- 4 份出版者原文（两文 PDF/XML）均经 PowerShell `Invoke-WebRequest` 返回 HTTP 200；哈希、URL、字节数见 [device-source-manifest.json](device-source-manifest.json)。浏览工具访问 mdpi.com 正文为 429；从出版者公开静态附件取得原档，未登录、未联系作者。
- PDF 共 14/11 页；使用已存在的 bundled Python `pypdf` 提取全文，XML 用标准库解析；使用已存在的 `pdftoppm` 渲染 2020 p2–6、p12 与 2024 p3。本轮实际目视 p2、p3、p4、p5、p12（2020）和 p3（2024）中的相关参数/坐标/图表；p6 仅缓存待用，未把其图读数字用于结论。
- 原档/提取/图像都只放在 `local_runtime/dram-see-v4/course-plan-r13/device-evidence/`，没有修改旧失败材料、运行索引、预算或 runner。机器可读证据见 [device-parameters.csv](device-parameters.csv)。
- 第一条文本提取命令所猜 bundled `pdftotext.exe` 不存在；改用已安装 `pypdf` 后成功。XML 摘录第一次在控制台 GBK 编码遇 U+2212 退出 1；改为 UTF-8 后重做并完成。未安装软件。以上是取证工具问题，不是仿真执行失败。
- 原始 Ion 图读依据：`2020-page-04.png`，150 dpi，1241×1754 px；只做格线手读，未生成伪精确数字化曲线或精确容差。本报告所有其他定量常规指标均来自正文/表格/图注或图轴明确文字。
- 未运行 SDE/SDevice/Geant4、未 SSH、未训练、未编译、未发布、未修改预算。当前还没有无粒子“通过”或 α/质子“通过”。主代理可据此冻结公开值与假设合同，然后按新预算和质量门实施。

