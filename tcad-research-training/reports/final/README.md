# DRAM课程报告与中文研究论文

本目录是可编辑、可编译的阶段写作包，按已确认方案分别组织课程报告和研究论文。正文、摘要与结论仅使用当前已完成证据；独立测试、尺寸外推和工艺扩展的最终结论留待其原流程验收后接入。

## 阅读与修改入口

| 文件 | 用途 |
| --- | --- |
| `course-report.pdf`、`course-report.tex` | 《AI辅助下的多特征尺寸DRAM单粒子效应评估》：7章课程报告、课程要求对应表、分工登记和只读演示步骤 |
| `research-paper.pdf`、`research-paper.tex` | 《AI辅助Geant4–TCAD联合仿真的DRAM单粒子读出裕量评估》：6节中文阶段研究稿 |
| `sections/course/`、`sections/paper/` | 两份稿件分别编辑的章节正文 |
| `artifact-ledger.csv` | 按阶段产物组织的成果台账、结论边界与对应章节 |
| `evidence-index.csv`、`sources.json` | 文件级来源、固定副本、摘要值及图表输出关系 |
| `data/evidence.json`、`data/source-snapshots/` | 写作使用的结构化证据及其固定输入副本 |
| `figures/`、`tables/` | 共用图表；每张数据图均附来源说明，流程图为概念示意 |
| `references.bib`、`reference-verification.json` | 共用题录和核验范围；Crossref原始记录另存 `reference-metadata.json` |
| `QA.md`、`delivery-manifest.json` | 本次交付的检查范围、结果及文件摘要值 |

学校模板、学生姓名、学号、实际分工、教师审核与答辩信息按真实情况补充。指导教师姓名来源于已有课程大纲。原 `reports/paper/` 阶段稿及实验原件保持原位置。

## 固定证据截止点

本稿采用 **2026-10-11 05:02:41 UTC−08:00** 的本地账本副本（即 13:02:41 UTC），沿用项目指定的固定 UTC−08:00 口径。它不是远端进程实时检查。

| 逻辑响应集合 | 计划分母 | 已验证 | 账本在途 | 待提交 |
| --- | ---: | ---: | ---: | ---: |
| 训练，0.18／0.35 μm | 64 | 64 | 0 | 0 |
| 插值留出，0.25 μm | 32 | 19 | 1 | 12 |
| 尺寸外推，0.45 μm | 32 | 0 | 0 | 32 |

完整设计为64个独立粒子事件、128个0/1配对响应。工程重试、同事件的0/1响应、数值变体与氧化层变体均不增加独立事件数。训练交叉验证来自原冻结模型，未对这19项部分留出响应进行重新选模或最终评分。

“多特征尺寸”指本探索模型的访问管栅长。自然语言入口是限定模板的受约束映射；质子结果限于已用电磁输运配置；全部结论限于未校准模型的电荷和读出判据响应。

## 本机复建

以下命令在 `E:\TCAD-Workspace\tcad-research-training` 运行，仅生成文稿或由固定副本重建图表，不启动仿真。

```powershell
$analysisPython = '.\local_runtime\vdmos-analysis-venv\Scripts\python.exe'
& $analysisPython -B .\reports\final\prepare_evidence.py
& .\reports\final\build.ps1 -XeLaTeX 'C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe' -BibTeX 'C:\Program Files\MiKTeX\miktex\bin\x64\bibtex.exe'
& $analysisPython -B .\reports\final\verify_documents.py --output .\local_runtime\report-final-20261011\document-qa.json
```

`prepare_evidence.py`默认读取已经保存的证据副本和账本截点。不要删除这些副本来刷新文稿。重新绘图需要NumPy、Matplotlib；PDF文字检查使用PyMuPDF或pypdf。LaTeX使用XeLaTeX、BibTeX、ctex/Fandol字体、TikZ、booktabs、tabularx、longtable、caption、placeins和hyperref。本机脚本复用已有 `local_runtime/report-writing-20261010/tex-deps/`；标准TeX环境安装相应宏包后也可编译。

构建中间文件、控制台日志和逐页PNG均位于 `local_runtime/report-final-20261011/`。`build.ps1`仅在该文稿全部编译步骤成功后更新其PDF。每份文稿完成一轮XeLaTeX、BibTeX及两轮XeLaTeX；修订正文后应重新检查引用和版面。

## 最终结果的接入规则

后续工作以 `experiments/dram-see-v3/r50-main/restart-r3/downstream-notes.md` 为入口。当前写作包不调用旧版 `extensions.py` 或 `delivery.py`。

1. 从 `local_runtime/dram-see-v3/physical-revisions/r50-main-restart-r3/` 读取实际封存且重审通过的 `test-result.json`、`prediction-scores.json` 和 `metrics/`。只有存在文件且通过对应验收，才更新完成状态和测试结果；不能仅凭账本计数补写最终结论。
2. 核对原失败与唯一有效retry的逻辑对应，包括r2的一项训练重试及r3的两项测试重试。保留原失败，不增加分母，不使用旧canonical导出覆盖新结果。
3. 复用 `r50-main/data/predictions/` 原冻结模型与64条预测。分别报告留出和外推的MAE、RMSE、最大绝对误差、训练均值基准和分层残差；最终测试不反向参与调参。
4. 仅在14项氧化层扩展、预定边界细化及各自匹配参考与对照验收后接入对应图表。氧化层扩展按固定硅入口事件解释为TCAD敏感性，不写为完整材料栈的输运外推。
5. 建立新的版本化证据快照，保留本次快照；统一更新数据、两份正文、摘要与结论，重新编译并逐页验收。实际学生分工和课程审核记录单独据实补齐。

## 图组接入安排

| 图组 | 当前可用内容 | 最终接入条件 |
| --- | --- | --- |
| 流程与结构 | 概念流程图、正文1T1C结构说明与参数表 | 如补原生模型图，绑定实际R50输入和物理量 |
| D1参考比较 | 已完成的历史无粒子参考比较图 | 保留D1身份，不改写为R50数据 |
| R50基线与数值验证 | 固定事件预充比较、初态及代表尺寸BL曲线；数值门槛与已检查范围见正文 | 全矩阵边界验证完成后补相应数据 |
| 多尺寸粒子响应 | 两训练栅长的真实连续响应 | 全128主响应验收后加入留出与外推尺寸 |
| 预测与误差 | 当前仅展示训练LOCO和均值基准 | 封存评分后新增预测—真值、残差及分集合误差表 |
| 氧化层敏感性 | 已写明设计与解释范围，未绘制结果 | 4／6 nm扩展及匹配条件全部验收 |

没有数据的图组只保留此处设计，不在PDF中绘制虚构曲线或结果占位图。
