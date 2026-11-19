# 设计方案、步骤与进度

科学设计与全部来源见../data/snapshot/sources.json，当前128槽见../data/snapshot/responses.csv，四alias及实际case owner见../data/snapshot/response-sources.json。原训练32事件64响应冻结四个bit/target模型；测试32事件64响应（域内留出32、外推32）先预测后提交，禁止重新拟合。

实施顺序：参考与初态/预充审计→pilot与源隔离→预登记完整匹配细化→64训练响应→模型及64预测冻结→64测试响应→14氧化层case→全128中固定排序的两个边界目标及匹配细化→两个原生目标四张PNG逐图核验→交付。

本快照的实际阶段门槛见../data/snapshot/stage-verification.json。快照采集时的“数据图、最终文稿/PPT尚须单独目视验收”状态保持在原始快照内，不回写历史。后续主调度者已实际逐图完成[13张DATA PLOT验收](../data/data-plot-visual-review.json)、[两PDF共35页验收](../qa/root-pdf-visual-review.json)及[最终PPT共16页验收](../qa/root-ppt-visual-review.json)；完整数据机器与统计验收见[独立证据](../data/delivery-root-acceptance.json)。

课程真实学生分工、教师方案审核、试讲、答辩与考核未由代理执行，仍待人工据实登记。
