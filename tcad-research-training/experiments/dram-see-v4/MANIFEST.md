# v4 产物清单

本清单仅覆盖v4新目录。初始规划回合使用aris-anything路由至experiment-plan，按仓库既有实验目录格式组织；后续学习及真实验证按阶段追加，以下原始规划条目不表示当时已运行仿真。

| Timestamp | Skill | File | Stage | Description |
|---|---|---|---|---|
| 2026-10-12 | experiment-plan | README.md | implementation | 本轮状态、保护边界和导航 |
| 2026-10-12 | experiment-plan | plan.md | implementation | 四阶段工作、证据主张、模型对照和准入条件 |
| 2026-10-12 | experiment-plan | work-items.md | implementation | 规划及后续任务、依赖和未执行状态 |
| 2026-10-12 | experiment-plan | mentor-response.md | implementation | 用户提供单页截图的8条批注回应 |
| 2026-10-12 | experiment-plan | device-basis.md | implementation | 器件/文献来源、缺口与v3迁移定位 |
| 2026-10-12 | experiment-plan | interface-contract.md | implementation | 两条路线、数据合同、源积分和验收草案 |
| 2026-10-12 | experiment-plan | evidence/mentor-comments-page1.png | implementation | 原样复制用户截图，非生成/编辑图 |
| 2026-10-12 | experiment-plan | planning-review.json | implementation | 主代理的文档/链接/关键历史哈希检查 |

Stage 使用工作流的 implementation 分类仅表示计划服务于后续实现，不表示实现或实验已经完成。后续变更追加记录，不覆盖历史实验。

## 学习与设计阶段

用户后续要求逐步落实；2026-10-12完成首轮学习与实验设计。以下产物不表示仿真已执行。

| 2026-10-12 | research-lit / experiment-plan | stage1/design-calculations.json | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/design-register.json | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/device-evidence.md | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/experiment-design.md | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/history/initial-planning-20261012.zip | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/source-register.json | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/start-record.json | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/study-notes.md | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | research-lit / experiment-plan | stage1/transport-design.md | implementation | 学习设计证据或工况记录 |
| 2026-10-12 | experiment-plan | stage1/review.json | review | 文档、数值算例与保护检查 |
| 2026-10-12 | experiment-plan | README.md / work-items.md / plan.md / device-basis.md / interface-contract.md | implementation | 更新当前学习设计状态与新证据入口；初版保存在快照 |

## A0 / A1 / A4 小规模实施与验证

2026-10-12用户授权实施；运行器UTC归档日期为2026-10-13。仅存储1、历史二维器件的3个接口探针，实际通过；强子输运未就绪，未训练。小型交付与索引在下列路径，完整原档仍由既有运行器保存。

| 日期 | 类别 | 文件 | 状态/用途 |
|---|---|---|---|
| 2026-10-13 UTC | 实施 | source-probe/build_probe.py、source_contract.json、README-source.md | 不可覆盖的独立工程、源项与容差冻结 |
| 2026-10-13 UTC | 实施 | source-probe/preflight.py、run_once.py、run-plan.md | 只读核查和单次原运行器调用；唯一主调度，无自动重试/扩展 |
| 2026-10-13 UTC | 验证 | source-probe/audit_probe.py、README-audit.md、test_source_probe.py | 原档审计、成对比较及9项独立软件测试 |
| 2026-10-13 UTC | 结果 | source-probe/report.md、run-index.json | 中文实际结果与三个独立run_id |
| 2026-10-13 UTC | 结果 | source-probe/results/a0-b1-r1.json、a1-b1-r1.json、a4-b1-r1.json、comparison.json | 单例7项和比较5项检查通过 |
| 2026-10-13 UTC | 结果 | source-probe/results/summary.json、case-summary.csv、raw-artifact-index.json | 数值、原始归档/曲线精确路径和SHA-256 |
| 2026-10-13 UTC | 证据 | source-probe/results/readiness.json、execution-freeze.json、failures.json、final-review.json | 前置核查、冻结记录、失败/阻塞分类与最终保护检查 |
| 2026-10-13 UTC | 证据 | source-probe/hadronic-check.md | 缺失数据及条件依赖分层；没有安装或强子初始化 |
| 2026-10-13 UTC | 图表 | source-probe/plot_results.py、results/source-probe-curves.png、source-probe-curves.pdf、figure-provenance.json | 实际原始曲线图与输入哈希，主代理已目视检查 |
| 2026-10-13 UTC | 导航 | README.md、work-items.md、plan.md | 更新实际进度，整体G1–G4仍未通过 |

`local_runtime/dram-see-v4/`内另有冻结输入、每次启动执行记录、审计导出CSV、独立验证日志和只读环境证据，均由结果索引引用；不作为随机粒子概率或新尺寸数据。

## 强子环境与质子小规模检查

用户后续明确授权补齐匹配数据；本地日期2026-10-12、运行归档为2026-10-13 UTC。首选H/E零事件建表及22个初级事件检查通过，未发生核反应步骤，未进行联合TCAD映射或训练。以下追加结果不改写上一轮缺包的历史记录。

| 类别 | 路径（transport-probe/下） | 内容 |
|---|---|---|
| 冻结设计 | environment-spec.json、environment.md、probe-contract.json、run-plan.md | 版本/数据/资源、环境指纹和真实就绪边界、固定种子/几何/22事件与准入规则 |
| 实施 | transport_probe.cc、README-transport.md | 独立v4程序，完整世界/硅轨迹与逐步记录、实际过程/模型/cut表 |
| 实施 | download_data.py、operation.py、prepare_run.py、collect_record.py | 校验下载、原严格连接/锁/affinity适配、不可覆盖输入和可核验receipt |
| 审计 | audit_transport.py、README-audit.md、test_transport.py | 固定算术容差、实际归档/出口/模型及事件账本检查；8项独立测试 |
| 结果 | report.md、run-index.json、results/summary.json、event-run-summary.csv | 22初级、66轨迹、1724步骤；其中44条电子次级、2个零沉积负向事件 |
| 证据 | results/download-record.json、installed-dataset-inventory.json、installed-environment.sh | 两个官方匹配包、5110新增文件及四数据集内容指纹 |
| 准入 | results/initialization-gate.json、format-gate.json、initialization-summary.json | 零事件物理表及过程检查通过后才执行粒子；格式通过才进入小矩阵 |
| 原档 | results/raw-artifact-index.json、各run的*-audit.json | 13个成功请求的原始归档/输入/二进制/环境/结果哈希；所有raw在local_runtime/v4下 |
| 过程 | results/h-processes.csv、e-processes.csv、h-hadronic-models.csv及两臂constructors/cuts | 完整实际清单；不以配置文件声明代替实际注册 |
| 失败/验收 | results/failures.json、final-review.json | 两项准备失败及修复保留；验证工具问题和额度中断接管范围分开说明 |
| 图 | plot_results.py、results/proton-checks.png、proton-checks.pdf、figure-provenance.json | 实际3D电子次级径迹与每条件2个样本散点，无发生率/拟合外推 |

安装、初始化、格式探针和8项测试由独立验证员复核；验证员额度不可用后，剩余10个事件运行由主代理接管复核，见结果中的范围说明。没有擅自补写独立验证结论。
