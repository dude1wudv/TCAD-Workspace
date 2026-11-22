# 论文草稿：AI辅助下的DRAM存储器单粒子效应评估研究

- 分支：`agent/thesis-draft`（从本地 main 切出；远端合并走 PR，不直接推送 main）。
- 正式题名（三门课统一）：**AI辅助下的DRAM存储器单粒子效应评估研究**。
- 格式：中文 LaTeX（`ctexart`），仿照 `tcad-research-training/reports/final/` 的工程结构。
- 用途：毕业设计论文的唯一起草区；科研训练、项目设计的成稿素材统一从 `materials/` 索引复用，不复制三套。
- 编译：`powershell -File build.ps1`（需要本机有 xelatex + bibtex + ctex 宏包；编译产物 `*.pdf/*.aux/*.log` 已被仓库 `.gitignore` 排除，不会入库）。

## 目录结构

| 路径 | 内容 |
|---|---|
| `main.tex` / `preamble.tex` | 论文主文件与导言区宏包 |
| `sections/01-*.tex … 07-*.tex` | 七章正文；`01`、`02` 已有初稿，`03`–`07` 为占位 |
| `materials/素材索引.md` | 每章可用素材 → 原路径 + SHA + run ID + 适用边界 + 缺口 |
| `materials/图表引用清单.md` | 已核验 15 图 7 表的引用方式、图注模板、待补图 |
| `materials/证据收集清单.md` | 跑仿真途中每次要收集的证据（run ID、哈希、日志等） |
| `figures/` / `tables/` | 只放新生成的图和表；旧图旧表用相对路径引用，不搬家 |
| `refs/references.bib` | 参考文献（旧稿 8 条 + 导师新增资料 L01–L09、J01） |
| `build.ps1` | 编译脚本 |

## 证据边界（写作红线）

1. 仿真结果 ≠ 实验实测；同一事件的 bit0/bit1 配对与确定性复跑 ≠ 新独立样本。
2. `COLLECTED` / 退出码 0 只代表工程完成，不代表科学验收通过；计划文字不写成已完成事实。
3. v3 结果限原冻结设计（未校准二维代表模型、固定 5 MeV/两角度/固定位置），不冒充真实 DDR5 校准或实测截面。
4. 缺注量 Φ、有效被测比特数、观测时间等分母时，不写"截面"和"环境 SER"。
5. 失败与未决样本必须出现在结果/讨论章节，不删除、不改写为成功。
6. 每句定量结论须能回溯到 `materials/素材索引.md` 中的路径 + 哈希 + run ID。

## 与主仓库的关系

- 共享索引：`tcad-research-training/shared/evidence-index.csv`、`figure-catalog.md`、`reuse-evidence.md`。
- 实验证据：`tcad-research-training/experiments/dram-see-v1…v4/`、`dram-se-r06/`（r0.6 当前排批）。
- 历史报告稿：`tcad-research-training/reports/final/`、`final-r4/`、`outline.md`（可复用文字，注意旧题名与旧结论边界）。
- 原始数据、运行目录、许可证不进本目录，只写路径 + SHA。

## 当前状态

- 2026-11-21：七章全部有实质内容，本地 MiKTeX 编译 22 页、0 错误 / 0 未定义引用（`build/main.pdf`，不入库）。
  - 第 1 章背景与文献综述（bib 14 条）；第 2 章建模与数据链路（参数表+公式）；第 3 章数据集合同与质量门槛；第 4 章 R→A→F 预测链路与 CV/盲测协议；第 5 章结果（15 图 2 表已排）；第 6 章讨论（失败复盘与边界）；第 7 章结论（主要结论+待补+后续）。
- 分支 `agent/thesis-draft` 已推送，PR #12 开向 main（7 个 commit）。
- 待补：学校模板/期限（M06）；导师 DDR5 实验原始数据（M01/M02）；v4/r0.6 合格数据集与新模型盲测结果（补入第 5 章 5.7 节）；导师邮件待发送。
