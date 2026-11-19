# 最终文稿/PPT质量与证据记录

稳定交付为课程报告21页、研究论文14页、PPT16页（12核心+4备份）。两PDF SHA256与PPT SHA256列于 `delivery-manifest.json`，对应渲染逐页哈希在 `qa/pdf-r3/render-manifest.json` 和 `qa/ppt-r4/render-manifest.json`。

## 实际构建与修正

| 步骤 | 实际结果 | 保留证据 |
|---|---|---|
| PDF-r3：两文档各XeLaTeX/BibTeX/XeLaTeX/XeLaTeX | 8条命令exit0，末次日志无Overfull、未定义引用或LaTeX Warning | `qa/tex-r3/commands.json`、末次日志；原目录 `local_runtime/dram-see-v3/final-r4-document-build/tex-20261012T0050Z-r3` |
| Poppler 144 dpi逐页渲染 | 两次exit0，21+14张PNG | `qa/pdf-r3/render-manifest.json` |
| PPT-r1 | exit1：嵌入Excel图表数据的全精度兼容检查失败 | 私有 `deck-r1-launch.log`，保留原失败 |
| PPT-r2 | exit1：第一方导入子进程缺少runtime模块路径 | 私有 `deck-r2-launch.log`，保留原失败 |
| PPT-r3 | exit0；作者逐页发现slide2公式列间重叠、slide3间隔及slide15人名需改 | 私有 `deck-r3/`、日志和16张原PNG保留 |
| PPT-r4 | exit0；只修正文案排版三页，全部机检通过，最终文件重新import后渲染 | `qa/ppt-r4/validation.json`、16张PNG、渲染绑定 |
| 文档核验脚本初稿 | exit1：PDF提取可能在FAILED词内插入空白；随后使用空白归一化，且采用pdfplumber正确解析Fandol CID中文 | 私有 `package-r2/verification-development-notes.json`；PDF未改 |
| 首次封包检查 | exit1：链接检查要求尚未生成的自身核验回执；文档/科学数据未变 | 原失败stdout/stderr和命令记录保留；初次只延后两个自身生成文件，封包后全量检查 |
| `verify_package.py`稳定版 | exit0，71来源/64快照输出/35页PDF/16页PPT、图表数值与原生图字节核验通过 | `qa/package-verification.json`，私有命令记录 |

PPT展示层数值经主调度者同意舍入为6位小数，原冻结数据和评分未改。3个原生图的32个数值点逐项对照冻结summary；矩阵事件/响应合计、岭回归所有误差行、4项边界行与费用表均单独核验。PPT机检工具的通用原生表合计检测未自动识别这些表，不能将该工具的零发现替代本包的实际源数值检查。

## 实际目视

作者使用 `tools.view_image` 实看两PDF全部35页，以及PPT-r3全部16页；r4改动的2/3/15三页再次目视，其他13张PNG逐字节与已审r3相同。已修复排版问题，未发现当前裁切、缺字、重叠或图例单位缺失。作者记录见 `qa/author-visual-review.json`。

主调度者独立实看最终两PDF全部35页和最终PPT全部16页，逐页匹配最终文件与PNG哈希，记录分别为 `qa/root-pdf-visual-review.json`、`qa/root-ppt-visual-review.json`。科学证据中的2张完整原生窗口与13张DATA PLOT另有单独逐图验收，见 `data/` 中的外部记录。

## 限制与待人工

PPT通过OOXML/嵌入工作簿检查、第一方最终文件重新导入和PNG视觉核验；未打开原生PowerPoint桌面应用或实际投影。PDF中文可由pdfplumber提取；pypdf在本环境对Fandol CID中文映射不完整，核验仅用它计页，不把其文本输出作为中文内容证据。文稿TeX与PPT原生文本、表、图均可编辑，修改后须重新生成并验收。

文献条目、DOI和元数据复用已核查来源，核查范围见 `reference-verification.json`；不宣称完成任何学生个人全文阅读任务。2–3名学生真实分工、教师审核、资源交接、现场演示、试讲、答辩、成绩均待人工。代理的工程检查不替代这些活动。

本交付步骤没有SSH、VM操作、求解、模型重训、预测改写、软件安装、Git提交/推送或对外发送。科学原档、冻结计划与账本保持不变。
