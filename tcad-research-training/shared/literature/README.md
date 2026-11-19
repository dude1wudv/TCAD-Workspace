# 共享文献：导师新增资料

正式题名：**AI辅助下的DRAM存储器单粒子效应评估研究**。科研训练、项目设计、毕业设计共用本索引。

先读 [内容拆解与使用建议](mentor-added-20261116.md)。以下ID对应原文及笔记页码；精确SHA256、题录和阅读范围见 [来源清单](../../docs/sources/mentor-references-20261116.json)。

## 两项新增资料的组成

截图中新增的是 `LPDDR5 TCAD` 资料包及纪志罡扫描讲义。包内有7篇论文、2份规格资料和1页PPT；未找到TCAD工程、源代码或原始辐照数据。
`参考文献/` 与 `参考材料/` 中这11个原件逐文件SHA256相同；本索引统一指向前者，保留两处原件，没有重复复制进三门课程。

| ID/原文 | 类型 | 题名 | PDF页数 | 用途 |
|---|---|---|---:|---|
| [J01](../../../参考文献/纪志罡-DRAM可靠性新挑战.pdf) | 讲义 | AI时代DRAM可靠性新挑战：从缺陷机理到跨层协同优化 | 21 | AI代理、BTI与跨层方法；不是SEE实验 |
| [L01](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/datasheet/JESD209-5-Output.pdf) | 标准 | Low Power Double Data Rate 5 (LPDDR5), JESD209-5 | 422 | 命令、刷新及规格边界 |
| [L02](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/datasheet/Micron%20LPDDR5%20datasheet.pdf) | 器件手册 | LPDDR5 SDRAM, Rev. A 05/2021 | 25 | 具体型号规格；原件标注Confidential |
| [L03](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/文献/Analysis_on_SER_failure_mechanism_and_improvement_by_implementing_RHBD_in_DRAM.pdf) | 论文 | Analysis on SER failure mechanism and improvement by implementing RHBD in DRAM | 7 | 外围SEFI；CSI DICE加固 |
| [L04](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/文献/Investigation+of+flux+dependent+sensitivity+on+single+event+effect+in+memory+devices.pdf) | 论文 | Investigation of flux dependent sensitivity on single event effect in memory devices | 8 | Geant4–TCAD接口；粒子与通量条件 |
| [L05](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/文献/Patterns_that_Break_Memory_SEU_Characterization_of_COTS_LPDDR2_and_LPDDR4_SDRAM_via_Stress_Testing_Under_60_MeV_Proton_Beam.pdf) | 论文 | Patterns That Break Memory: SEU Characterization of COTS LPDDR2 and LPDDR4 SDRAM via Stress Testing Under 60 MeV Proton Beam | 11 | LPDDR2/4实验统计；访问图样和观测偏差 |
| [L06](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/文献/Radiation-induced_soft_errors_in_advanced_semiconductor_technologies.pdf) | 论文 | Radiation-Induced Soft Errors in Advanced Semiconductor Technologies | 12 | 基础综述；不能当新代际定量结果 |
| [L07](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/文献/SEU_Sensitivity_of_a_14-nm_SOI_FinFET_eDRAM_Cell_under_Heavy-ion_Irradiation.pdf) | 论文 | SEU Sensitivity of a 14-nm SOI FinFET eDRAM Cell under Heavy-ion Irradiation | 4 | mixed-mode方法对照；非LPDDR5产品模型 |
| [L08](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/文献/Soft_Error_in_Saddle_Fin-Based_DRAM_at_Cryogenic_Temperature.pdf) | 论文 | Soft Error in Saddle Fin-Based DRAM at Cryogenic Temperature | 7 | 优先建模参考；区分共享与直接收集 |
| [L09](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/文献/TCAD%20simulation%20of%20radiation-induced%20leakage%20current%20in%201T1C%20SDRAM.pdf) | 论文 | TCAD simulation of radiation-induced leakage current in 1T1C SDRAM | 5 | 位移损伤/保持退化对照；非瞬态SEU |
| [P01](../../../参考文献/LPDDR5%20TCAD/LPDDR5%20TCAD/logo.pptx) | 附属PPT | logo.pptx | 1页 | 机构版式附件，不计论文 |

## 建议阅读顺序

L08 → L04 → L05 → L03；L07用于混合仿真对照，L09用于划清保持退化边界，L06补基础，J01借鉴AI与跨层方法。L01/L02按实际器件和实验状态查阅。
本次未外网补检；题录来自本地原文/元数据。L07 DOI未在副本中找到，保留待核验。
J01为扫描件OCR主题拆解，细小公式、图中数值不直接录入数据集；规格文件按相关条款阅读，不冒称全文逐条审核。
旧Yifan SRAM论文和周习瑞硕士论文仍保留，未算作本轮新增文献。
