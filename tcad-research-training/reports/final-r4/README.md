# DRAM SEE v3：完整 r4 报告与课程交付包

本包绑定 `20261012T0033Z-full` 完整冻结证据。训练64/64、测试64/64响应已完成，原64独立事件、128配对响应与64条预先冻结测试预测保持不变。两份PDF和PPT已由作者自查、主调度者逐页目视验收；真实学生操作、教师审核、试讲、答辩和考核仍待人工。

| 文件 | 用途 | 稳定版本 |
|---|---|---|
| [course-report.pdf](course-report.pdf) / [可编辑TeX](course-report.tex) | 完整课程设计报告 | 21页，PDF-r3 |
| [research-paper.pdf](research-paper.pdf) / [可编辑TeX](research-paper.tex) | 研究论文 | 14页，PDF-r3 |
| [dram-see-v3-r4-r4.pptx](dram-see-v3-r4-r4.pptx) / [生成源](build_deck.mjs) | 原生可编辑演示文稿 | 12页核心+4页备份；末尾r4为排版构建版本 |
| [课程支持材料](materials/index.md) | 可行性、方案、步骤、进度、AI披露、只读演示、答辩准备和人工登记 | 7份Markdown |
| [完整数据快照](data/snapshot/report.md) / [证据索引](evidence-index.csv) | 原始来源、全分层统计、评分、历史失败和成本 | 保留采集时原字节 |
| [来源清单](sources.json) / [最终文件清单](delivery-manifest.json) | 逐文件SHA256及输入绑定 | 用于版本核对 |

唯一交付PPT为 **`dram-see-v3-r4-r4.pptx`**。同目录的 `dram-see-v3-r4-r3.pptx` 仅保留前候选构建证据，已被r4修正替代，不作为最终演示文稿。

## 结论与边界

5 mV主阈值下，128个逻辑响应为96正确、20判据误读、8临界、4数值不确定，逻辑槽失败/缺失均为0。完整账本仍保留全部7条历史FAILED；其中R50主线的4个别名重试保持原逻辑槽和原失败，未知退出码仍为null。全部费用100022.07 s（约27.7839 h），包含失败、旧版本、probe、重试和扩展；预算已取消上限。

三阈值2.5/5/10 mV保留数值不确定1/4/1项。4项边界比较的连续量门槛通过，其中半步长结果在5 mV跨界；其余3项近界未选响应亦保留不确定。14个氧化层case与4个边界case合计18次新扩展，不增加独立N。氧化层受控敏感性最大变化约0.112560497 mV和0.005783687 fC；幅度小于预定0.5 mV/0.01 fC验收容差，容差并非统计误差条或分辨率，未对每个厚度追加独立细化/统计校准，不作微小效应显著性主张。

结论限定于固定5 MeV、两角度、固定入射位置和未校准二维模型。准静态初态、理想电容及判据读出不等同于真实写入保持、感放锁存、持久位翻转或商业DRAM可靠性。旧 `reports/final` 的19/64历史结论保持原状，不作为当前结果。

## 验收证据

- [最终数据独立验收](data/delivery-root-acceptance.json)：64输出和77来源清单、全128响应、96个N=4分层Wilson区间等复核。
- [真实原生图逐图记录](data/native-visual-review.json)与[13张DATA PLOT记录](data/data-plot-visual-review.json)。文稿/PPT仅展示两张未改动的完整 `own-window.png`；另两张导出图右端单位后缀裁切已如实记录，原图未修改。
- [PDF逐页根目视](qa/root-pdf-visual-review.json)，[35页PNG和PDF绑定](qa/pdf-r3/render-manifest.json)；[课程页图](qa/pdf-r3/course-report/)与[论文页图](qa/pdf-r3/research-paper/)。
- [PPT逐页根目视](qa/root-ppt-visual-review.json)，[16页PNG与最终PPT绑定](qa/ppt-r4/render-manifest.json)，[PPT机检](qa/ppt-r4/validation.json)。PPT有6个原生表、3个原生图及3个嵌入工作簿；图表展示数值舍入至6位小数，全精度冻结数据保留。
- [作者核验说明](QA.md)与[只读机器核验](qa/package-verification.json)。原生PowerPoint桌面应用打开/演示未实测；最终PPT已通过结构检查、第一方重新导入及逐页渲染目视。

`data/snapshot` 内采集时的PENDING标签是历史状态；以上后续验收为独立记录，不回写原快照。主调度者审核是代理工程验收，不等同于课程教师审核。

## 只读复核与可编辑源

在仓库根目录用现有bundled Python执行以下命令，仅核验/输出JSON，不重建文稿、不启动求解：

```powershell
& 'C:\Users\sun\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 'reports\final-r4\verify_package.py'
```

TeX正文位于 `sections/course`、`sections/paper`，共享样式为 `shared-preamble.tex`，文献为 `references.bib`。实际PDF构建使用现有XeLaTeX与BibTeX、禁止自动安装和shell-escape，8条编译命令均exit0，记录在 [commands.json](qa/tex-r3/commands.json)。最后两次Poppler渲染均exit0。

`prepare_final.py` 是本次已完成的数据绑定/排版准备源，不是常规复核入口。`build.ps1` 与 `build_deck.mjs` 用于后续明确的文稿修订；它们生成新构建日志，重编后的文件须重新绑定哈希并逐页验收，不能继续沿用本次证书。PPT脚本使用bundled Node和 `@oai/artifact-tool`，本次从私有构建目录运行；具体命令见 [渲染绑定](qa/ppt-r4/render-manifest.json)。所有原失败构建日志保留在 `local_runtime/dram-see-v3/final-r4-document-build/`。

学生姓名学号、2–3人真实贡献、实验室资源交接、教师意见、演示录像、试讲和答辩考核见[人工登记清单](materials/index.md)。保留待填写并不代表相关活动已发生，也不以元数据核查冒充文献全文阅读。
