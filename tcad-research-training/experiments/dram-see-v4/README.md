# DRAM SEE v4

本轮阶段验收已收口（2026-10-13 UTC），完整计划仍部分完成：212个预注册厚硅初级事件取得9个核非弹性记录见证；三个三维源账本闭合；细网格A0/A1、A1全部205帧源测量和匹配对照的网格比较通过。粗网格空间失败保留，多源扩展尚未执行。已用5/19次求解，剩余15个角色与14次余量的差额见[继续条件](stage2/remaining-checks.md)。

- [本轮执行报告与真实结果](stage2/report.md)
- [更新后的导师批注回应](stage2/mentor-response.md)与[两条物理路线](stage2/route-status.md)
- [核机制见证简报、母子图及212事件证据](mechanism-witness/results/campaign-r1/report.md)
- [三维源账本与定义边界](source-ledger/README.md)
- [二维测量修订](source-interface-r3/README.md)、[细网格诊断](source-interface-r4/README.md)与[原生全帧审计](source-field-audit-r1/README.md)
- [Shin原图核验与90 nm参数缺口](device-evidence-r2/README.md)

三维器件响应、正式160事件矩阵、新尺寸批量、空间谱和训练未启动。v3、原报告与旧合同保持原样；旧心跳未恢复，没有提交推送或外发消息。下方保留前一轮历史导航，不代表本轮最新状态；旧版README另存于[阶段开始快照](stage2/previous-documents/README.md)。

## 前一轮历史导航

日期：2026-10-12（运行归档为2026-10-13 UTC）。状态：**A0/A1/A4的3个TCAD接口算例已通过；首选强子方案的数据已按授权补齐，H/E初始化和22个质子事件记录检查已通过。尚无核反应事件见证，训练未启动。**

研究对象仍为1T1C DRAM。先在历史未校准二维0.25 µm单元上完成存储1的3个源接口算例；随后在独立三维硅体中完成22个初级质子的记录检查，保留66条轨迹、1,724个步骤和两次零沉积射偏事件。次级轨迹全部为电子，没有观察到核反应步骤，不能称核次级联合TCAD验证完成。其余源检查、正式160初级事件设计、新尺寸校准和模型比较仍待开展。

- [历史：强子初始化与22个质子事件报告](transport-probe/report.md)
- [输运运行索引](transport-probe/run-index.json)、[失败记录](transport-probe/results/failures.json)和[环境规格](transport-probe/environment-spec.json)

- [本轮真实验证结果与曲线](source-probe/report.md)
- [运行索引](source-probe/run-index.json)与[失败/阻塞清单](source-probe/results/failures.json)
- [前一轮强子数据缺项记录](source-probe/hadronic-check.md)（历史状态；当前以最新输运报告为准）
- [冻结输入与容差](source-probe/source_contract.json)

- [当前学习结论](stage1/study-notes.md)
- [首批实验设计](stage1/experiment-design.md)
- [器件新增证据与校准缺口](stage1/device-evidence.md)
- [输运与多源实施设计](stage1/transport-design.md)
- [工况与未冻结字段登记](stage1/design-register.json)
- [本轮学习设计验收记录](stage1/review.json)

- [四阶段计划与决策门槛](plan.md)
- [导师批注逐条回应](mentor-response.md)
- [器件参数来源与待校准项](device-basis.md)
- [两条粒子路线、接口与验收合同草案](interface-contract.md)
- [任务顺序与当前状态](work-items.md)
- [初始规划文档检查记录](planning-review.json)
- [产物清单](MANIFEST.md)

v3 数据、四个岭回归模型、失败记录、阈值和报告原样保留。历史入口为 [v3 最终交付导航](../dram-see-v3/r50-main/final-delivery-r4.md)，修改后的报告源文件位于 [mentor-rewrite-r5](../../reports/mentor-rewrite-r5/coordination.json)。旧清单中的外部交付路径不能代替当前文件系统；本轮不迁移或改名任何交付文件。

初始“只形成计划”回合已结束，原始文件保存在 [规划快照](stage1/history/initial-planning-20261012.zip)。TCAD复用原运行器；Geant4沿用严格SSH连接和共享求解锁，所有运行由主代理串行单线程提交，只有预先冻结的请求，没有自动扩展队列。后续已按用户明确授权在v4专用目录补PhotonEvaporation5.7、G4PARTICLEXS3.1.1；原有Geant4、系统库及v3不变。结果、失败清单及原档引用均在v4索引中，旧心跳未恢复，未提交推送Git或对外发消息。下一步先冻结核次级机制见证的独立设计，并补分离/错时源、三维映射和器件依据。
