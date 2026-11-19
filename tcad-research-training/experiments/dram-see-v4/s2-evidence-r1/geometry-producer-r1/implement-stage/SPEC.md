# S2 几何测量生产者离线候选

目标：为既有首4角色补齐真实mesh的材料、接触、掺杂测量生产者候选，兼容现有geometry-validation消费合同。仅离线准备与合成检查，不取得原生资格。

输入：冻结packages-r2中B1-D2/B1-D3的geometry-contract；将来的同次原生mesh及原始测量。名义几何只提供比较预期。

输出：新目录的测量计划、未执行原生脚本候选、未批准比较策略、只读测量评估器和可审阅报告；三个测量CSV及geometry-validation.json的合同。A0复用获验收D3 mesh与测量，不重复测量。

成功命令：既有Python运行producer.py prepare；新tests/test_geometry_producer.py离线套件。保留准确命令、退出码及失败原档。旧29项套件复用。

Base commit：eb49585b6d1c7c833fa5c17bc83393612232c379。原工作树有未提交文件，原指纹以runtime protected-baseline.json为准。

边界：不改原S2/F5–F7源码、冻结包、capture/r3、candidate-r2、原runner、账本、门槛或原验收。不运行原生/SSH/编译/提取/训练，不提交Git。本候选无project.json、实际mesh或执行授权；原生语法、真实数据和G1/G2仍待验证。
