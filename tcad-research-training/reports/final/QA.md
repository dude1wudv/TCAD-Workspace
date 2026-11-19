# 本次文稿交付检查

## 交付结论

课程报告为18页，研究论文为12页。两份文稿均已完成XeLaTeX／BibTeX编译、文字与引用检查和逐页视觉检查。本结论仅验收文稿、数据引用和可复建证据包，不代表R50全实验或课程考核已完成。

## 已执行的检查

| 检查对象 | 方法和结果 |
| --- | --- |
| 数据来源 | 33项来源入索引：32份固定输入及1项本地账本截点观察，均有固定副本和SHA-256。固定账本时刻保持2026-10-11 05:02:41 UTC−08:00 |
| 冻结预测 | 六份冻结核心文件摘要匹配；训练64响应／32事件，64条测试预测，冻结记录中测试响应可见数为0 |
| 重试身份 | 三个原FAILED保留，分别对应唯一有效retry；工程重试不增加粒子事件分母 |
| 数据复建 | `prepare_evidence.py`执行与再次复建均退出0；68项既有输出摘要无变化。补充11项历史来源前后，24项既有图表、CSV和账本文件逐字节不变 |
| 独立内容审查 | 逐项抽核D1参考、100 Ω／R50 probe、样本计数、四个训练LOCO数值、单位、公式与结论边界，未发现阻断性不一致 |
| 题录 | Chen、Xu、Ryder三篇题录核对Crossref记录；陈文完整页码依据期刊页修正。其余原理来源沿用已有核验记录，逐项范围见 `reference-verification.json` |
| 编译 | 两份文稿分别完成XeLaTeX→BibTeX→XeLaTeX×2，最终命令退出0。输出PDF与构建目录PDF摘要一致，所有文稿输入早于对应输出 |
| 自动排版检查 | 两份文稿均无缺失文献键、悬空或重复标签、缺失图件、未完成写作标记、缺字、未解决引用警告或Overfull盒子；PDF抽取无替换字符 |
| 图件视觉检查 | 五张数据图均检查单位、分组、数值标注和来源边界；修正D1注释与虚线重叠、R50参考子图标题空间 |
| PDF逐页检查 | Poppler以108 dpi渲染全部30页。初版逐页查看后修正目录、流程图和附录；最终22页渲染与已检查页面逐字节相同，另8页重新查看并通过 |

初次编译发现公式中的中文顿号缺字，已将其移出数学环境。目录改为独立一页，课程附录表格固定在对应附录内，论文来源表前后段落已分开。最终页面不存在图表裁切、覆盖文字或跨附录漂移。

## 命令与检查记录

实际构建命令在仓库根目录执行：

```powershell
& .\reports\final\build.ps1 -Document all -XeLaTeX 'C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe' -BibTeX 'C:\Program Files\MiKTeX\miktex\bin\x64\bibtex.exe'
& .\local_runtime\vdmos-analysis-venv\Scripts\python.exe -B .\reports\final\verify_documents.py --output .\local_runtime\report-final-20261011\document-qa.json
```

`qa/document-qa.json`保存最终文稿结构、页数、警告与PDF摘要；`qa/independent-review.json`保存独立内容审查；`qa/render-comparison.json`保存最终各页PNG摘要和与初版的比较；`qa/visual-review.json`记录视觉验收覆盖。构建日志与逐页图片留在 `local_runtime/report-final-20261011/`，数据复建结果另见 `data/verification.json`。

本机MiKTeX另有操作系统支持及更新状态提示，不属于此次文稿的编译错误；本次未升级软件或下载宏包。

## 未验证范围和保留项

- 未重新运行Geant4、TCAD，未逐个重审全部原始tar归档，未检查远端实时进程；本次使用已经归档的结果和固定本地副本。
- 未完成独立测试全量评分、尺寸外推、氧化层扩展、最终边界检查和R50原生图形取证；稿件没有填入这些最终结果。
- 未校准真实DRAM工艺，不声称真实器件失效率、辐射截面、核反冲或商业工艺节点结论。
- 学生姓名与贡献、学校正式模板、教师审核、现场演示与答辩事实仍需当事人据实补充。

后续数据接入、对应章节和图组安排见 `README.md`；接入后需要重新完成本文稿检查。
