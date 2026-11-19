# S2 输入包实施规格

目标：离线完成 S2 CAD、物理卡、DC/写读 deck、α 源/场审计适配，并为 B1-D2、B1-D3、B1-A0-main-b0/b1 生成可审查输入包。

输入：course-plan-r13/model-contract.proposed.json、预算/计划、ASTAR与原文证据；现有scripts/tcad.py、source-interface-3d-r1及source-field-audit-3d-r1的已证方法。

输出：本目录独立生成器、实现假设及合同；local_runtime/dram-see-v4/s2-inputs-r1下按时间分离的审查包与离线验收。

成功命令：`python prepare.py prepare --output <new_directory>` 与独立本地检查；不得调用原生工具。project只生成project.review.json，不能直接交给原runner；执行发布/预算/原生资格保持关闭。

Base commit：eb49585b6d1c7c833fa5c17bc83393612232c379。现有大量未提交文件受保护；本轮不提交Git。

范围排除：原生建模/网格/求解/编译/后处理、Geant4、新统计批次、训练、修改旧预算或原失败结论。恢复同一半小时任务只授权离线推进。
