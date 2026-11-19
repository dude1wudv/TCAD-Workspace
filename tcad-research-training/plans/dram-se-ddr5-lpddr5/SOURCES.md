# 本计划的依据与参考

截至2026-11-16。本页区分导师任务、项目证据和外部方法来源；方法参考不是本项目已实现或通过验证的证明。

## 导师与工作区的一手依据

| 编号 | 来源 | 用途 |
|---|---|---|
| P1 | [导师截图](../../docs/sources/mentor-final-brief.png)与[转录](../../shared/research-brief.md)；本轮用户再次提供同主题截图 | 四项核心研究任务及DDR5前期条件；用户再次强调扣题 |
| P2 | [项目设计大纲](../../docs/course-project-syllabus.md) | 自然语言参数遍历、Geant4→TCAD传递及演示要求 |
| P3 | [导师资料题录](../../docs/sources/mentor-references-20261116.json)、[阅读记录](../../shared/literature/mentor-added-20261116.md) | L08结构、L04耦合、L05统计、L03错误分类；精确参数仍回正文 |
| P4 | [数据字典](../../shared/data-dictionary.md)、[指标口径](../../shared/metrics-and-labels.md) | 事件/响应、统计分母、来源、分组与历史标签边界 |
| P5 | [资料交接清单](../../shared/mentor-materials-request.md)、[研究任务清单](../../shared/research-task-checklist.md) | 原始数据与校准/结题信息缺口；旧任务先后门禁不直接照搬到新研究计划 |
| P6 | [服务器流程](../../docs/server-workflow.md)、[最新迁移交接入口](../../../output/server-benchmark-20261115/HANDOFF.md) | 原runner和共享槽池、资源状态定位；文件快照不等于实时查询 |
| P7 | [三课程入口](../../courses/README.md) | 正式题名、成果共用、各课程独立提交 |

本轮没有重新逐页审读全部参考PDF；复用已存在的阅读范围和题录，不把已有摘要当作新增全文核验。新模型录入精确几何、物理参数和曲线时另做定点核对。

## 外部方法核对

| 编号 | 官方/原作者来源 | 本计划采用的内容 |
|---|---|---|
| W1 | OpenAI, Function calling：`https://developers.openai.com/api/docs/guides/function-calling` | 工具调用与结构化参数；具体Magpie路由能力另实测 |
| W2 | scikit-learn, Cross-validation：`https://scikit-learn.org/stable/modules/cross_validation.html`；Nested versus non-nested CV：`https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html` | 开发/CV/最终测试分离、组间隔离与选参偏差；不直接复用示例数据或划分 |
| W3 | Geant4, Book for Application Developers：`https://geant4.web.cern.ch/documentation/dev/bfad_html/ForApplicationDevelopers/`，Tracking与Scoring章节 | step/track、总沉积/非电离沉积与评分接口；实现时按已部署版本核对 |
| W4 | SciPy, BinomTestResult.proportion_ci：`https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html` | 独立二项事件的精确/Wilson区间方法；加权样本、相关bit计数不能直接套二项区间 |

以上是方法设计依据；不存在由这些文档直接证明本课题模型精度、样本充分性或结题通过的推论。

## 开源科研plan skill的选型

本轮核对原作者仓库，作为模板设计参考，不直接安装或照搬其自动化权限/门禁。

| 候选 | 参考内容 | 本项目处理 |
|---|---|---|
| `luwill/research-skills` 的 `research-proposal` | 问题、现状、方法、工作计划、预期产出及可行性 | 借鉴固定研究计划骨架；本项目增加数据/标签和两路线任务 |
| `K-Dense-AI/claude-scientific-skills` 的 `hypothesis-generation` | 文献证据、可检验假设和验证设计 | 借鉴“假设—观察—检验”分开；不将研究假设变成所有运行的阻塞条件 |
| 本地 `skill-creator` | 简短入口、按需加载模板、控制范围 | 采用项目内维护源，SKILL.md不超过50行 |

候选入口：

```text
https://github.com/luwill/research-skills/blob/main/research-proposal/SKILL.md
https://github.com/K-Dense-AI/claude-scientific-skills/blob/main/skills/hypothesis-generation/SKILL.md
```

推荐是维护一个轻量 `tcad-experiment-plan`，复用上述研究结构思想和本项目证据合同；不为本课题引入整个通用科研代理框架。没有宣称完成全部开源项目的质量排名；模板文字为本项目重新编制。

检索说明：已直接获取W1、W2、Geant4 Tracking章节、W4及两份候选SKILL原文并定点阅读。旧K-Dense `scientific-skills/`路径已失效，本页采用实际存在的`skills/`路径。NIST旧手册入口返回机构首页，未将其当作本轮核验到的统计内容。


## r0.4新增核对：宽能区、物理神经网络与联合设计

2026-11-16。L05原PDF第7页能量图例、L08第2页表1及第5页图8/9、导师SRAM论文第70–71页方法/限制，复用本对话已完成的原文核对。L08基准尺寸不等于本计划0.8–1.2倍扰动域；其结区82/92 nm两端有原文，中间为项目插值。NA/ND绝对剖面仍需结构级来源和电学校准。

| 编号 | 一手来源和阅读范围 | 可用于本计划的事实与边界 |
|---|---|---|
| W5 | Radiation Performance of 1 Gbit DDR SDRAMs Fabricated in the 90 nm CMOS Technology Node，NASA记录20080039559原作者稿；PDF第1页质子测试段及第2页测试方法 | 质子20、30、50、98、200 MeV，法向；旧90/100 nm DDR，不作DDR5/LPDDR5标签真值 |
| W6 | SciPy LatinHypercube官方文档，定义、strength及采样/缩放说明 | 支持空间填充方法；本计划48配置及联合组合是项目设计，不来自文献样本数 |
| W7 | Geant4 PhysicsListGuide，FTFP_BERT非弹性/弹性/电磁组件 | 相关质子过程的模型能量覆盖；按已部署版本核对，不等同纳米DRAM已校准 |
| W8 | Experimental Study of Proton-Induced Radiation Effects on DDR5 Modules，DOI 10.1109/TNS.2025.3565125；作者机构题录/摘要 | IEEE TNS 72(6), 1907–1918，多能质子/模块研究线索；未取得原文逐能量条件，不使用二手表中的数值 |

```text
W5 https://ntrs.nasa.gov/api/citations/20080039559/downloads/20080039559.pdf
W6 https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.LatinHypercube.html
W7 https://geant4.web.cern.ch/documentation/dev/plg_html/PhysicsListGuide/reference_PL/FTFP_BERT.html
W8 https://kyushu-u.elsevierpure.com/en/publications/experimental-study-of-proton-induced-radiation-effects-on-ddr5-modul/
```

1–200 MeV整体范围、1–<20 MeV探索段、几何/掺杂扰动、斜角/方位、384工况及两级神经网络均是本课题设计，未声称存在一篇论文已验证完整组合。物理规则以适用电路关系、源/统计定义为依据，必须做同数据消融，不能由方法名称推出精度改善。

W1工具调用官方文档本轮重新核对；结构化调用原理不证明Magpie全部schema或研究工具已实现。分组CV与区间方法继续引用W2/W4，整个两级链都纳入分组验证。

## 训练设计1.0：机理残差网络与分组评价

2026-11-16定点核对。用户选择的是轻量多头MLP、机理模型＋残差修正、3折CV；网络宽度、低阶电路形式、搜索12组和折内2折交叉拟合是本项目据此作出的设计，不是文献给定的DRAM标准参数。

| 编号 | 一手来源与阅读范围 | 使用范围 |
|---|---|---|
| W9 | scikit-learn, GroupKFold官方API文档：`https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html`；已读分组不重叠定义 | 开发profile/来源连通组不可跨训练验证折；不意味着共享profile的新组合最终测试必须被合并回开发 |
| W10 | Rackauckas等，Universal Differential Equations for Scientific Machine Learning，arXiv:2001.04385：`https://arxiv.org/abs/2001.04385`；本轮只读题录与摘要 | 物理知识与学习项结合的方法路线；不证明本项目RC近似、残差时间基或参数可辨识性 |
| W11 | Gorishniy等，Revisiting Deep Learning Models for Tabular Data，arXiv:2106.11959：`https://arxiv.org/abs/2106.11959`；本轮只读题录与摘要 | 小型表格神经网络需与强基线公平比较；未证明MLP在本DRAM数据上最优 |

W2的nested/non-nested CV官方示例正文再次核对：同一CV分数用于选参并报告性能会产生乐观偏差。本项目3折明确作为开发选参，另保留最终独立测试；训练侧2折用于生成F的折外代理，不宣称它等于完整嵌套HPO。

L08原文提取中定点核对了结构/模拟方法和电荷收集、共享、漏电及节点电压响应段落；其重离子/低温结果用于机理参考，不直接充当本批质子标签。L04的输运—器件连接继续复用已有阅读记录。单节点扰动电路是待开发数据校准的项目近似，端口收集电荷和电容支路净电荷在训练方案中分别定义，不声称两者恒等。
