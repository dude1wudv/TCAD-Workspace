# DRAM SEE v3 r4 完整数据与最终材料入口

状态：全部代理可完成工作已验收，唯一心跳已暂停并完成应用数据库/TOML回读。完整主线、扩展、原生证据、最终报告、论文、PPT与课程材料均已完成。本文是当前导航，不修改冻结计划或历史快照的原始状态；学生/教师/答辩活动仍待人工。

## 最终交付

- [完整交付入口](../../../reports/final-r4/README.md)与[最终211文件清单](../../../reports/final-r4/delivery-manifest.json)。清单SHA256：`6736d751c7a5b9b1f1bcdaa897eaef29f4810600603fc31faa74bf2c57930c9e`。
- [课程报告PDF，21页](../../../reports/final-r4/course-report.pdf)及[可编辑TeX](../../../reports/final-r4/course-report.tex)。
- [研究论文PDF，14页](../../../reports/final-r4/research-paper.pdf)及[可编辑TeX](../../../reports/final-r4/research-paper.tex)。
- [唯一最终PPT，12核心+4备份页](../../../reports/final-r4/dram-see-v3-r4-r4.pptx)；同目录r3只保留为旧候选证据。
- [7份代理课程材料及人工登记清单](../../../reports/final-r4/materials/index.md)。
- [根最终验收](../../../local_runtime/dram-see-v3/downstream-r4-completion/20261012T0020Z/final-root-acceptance.json)，SHA256 `6bcb1e084cbdba8eb9263dd15d28b350e057249a6ee713560da523838923fde3`。
- [心跳暂停工具及数据库凭证](../../../local_runtime/dram-see-v3/downstream-r4-completion/20261012T0020Z/automation-paused-verification.json)，实际回读01:05:05Z为PAUSED，next_run为空，同一ID/对话/20分钟配置及通知策略保留。

全部35个PDF页面、16张PPT页、13张DATA PLOT及4张原生/真实窗口PNG均已实际逐页/逐图查看。独立封包复验实际exit0，211文件哈希、18个外部证据绑定、50个本地链接通过。PPT经最终文件重新导入和渲染验收，未宣称在原生Microsoft PowerPoint桌面应用执行。

主r4、扩展execute、GUI取证和完整delivery均已完成，不得依据旧PENDING快照或旧心跳提示重复执行。后续如明确修订文稿，应新版本构建并重新验收；冻结科学输入和原失败不变。

## 完整数据

- [唯一完整r4快照](data/delivery-r4/20261012T0033Z-full/report.md)，实际collect退出0，无新增求解或账本费用。
- [128响应](data/delivery-r4/20261012T0033Z-full/responses.csv)、[三阈值分层](data/delivery-r4/20261012T0033Z-full/statistics.csv)、[输出哈希清单](data/delivery-r4/20261012T0033Z-full/snapshot-manifest.json)。
- [原r4冻结模型评分](data/delivery-r4/20261012T0033Z-full/original-r4-prediction-scores.json)与[最终数值评分](data/delivery-r4/20261012T0033Z-full/final-numerical-prediction-scores.json)独立保存，未重新拟合。
- [四alias真实来源](data/delivery-r4/20261012T0033Z-full/response-sources.json)、[完整原账本](data/delivery-r4/20261012T0033Z-full/ledger-snapshot.json)、[全部原失败](data/delivery-r4/20261012T0033Z-full/original-failures.json)。
- [采集时课程材料历史快照](data/delivery-r4/20261012T0033Z-full/materials/index.md)保留原字节；当前材料见上方最终交付。

64独立事件、128配对响应不变，训练64响应、测试64响应全部实测归档。22扩展case含18新求解与4精确复用；氧化层和确定性细化不增加独立事件。5mV主阈值为96正确、20判据误读、8临界、4数值不确定，逻辑槽无缺失或未解决工程失败；这不删除历史失败。三阈值数值不确定数为1/4/1。连续细化满足0.5mV/0.01fC容差仍可能分类跨界。

全部历史、失败、重试及扩展已登记求解成本100022.07秒；当前无限授权下继续保留累计，不将其称为人工工时或AI效率收益。

## 验收证据

根完整原档复核、独立算术复核、真实GUI和逐图验收索引：`local_runtime/dram-see-v3/downstream-r4-completion/20261012T0020Z/`（仓库根相对路径）。其中`root-acceptance.json`、`native-visual-review.json`、`data-plot-visual-review.json`分别记述科学、4张原生/真实窗口及13张DATA PLOT的实际验收范围。

两张原生export的图例右端单位后缀裁切，原文件保留；完整owned窗口清楚显示字段、单位及真实run，最终文稿只采用未修改完整窗口图。这些图是4ns场分布证据，不能充作Workbench Run按钮或学生现场操作证据。

## 解释与人工事项

未校准二维1T1C、受控理想初态、固定硅入口事件；不推出商业DRAM可靠性、真实辐射截面、实际写入成功或持久位翻转。氧化层4/6nm为固定入口事件的TCAD敏感性，不是变化材料栈的全Geant4输运。

学生真实分工/操作、教师方案审核、试讲、正式答辩及教师评价仍须真实人员完成。代理生成材料与课程考核完成分别记录。
