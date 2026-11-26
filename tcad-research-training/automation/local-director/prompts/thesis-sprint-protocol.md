# 每日一次论文重写与增量拼接协议（Daily Thesis Sprint）

本协议保留为历史参考，不由当前 Local Director 自动触发。

## 总原则
- **从零构建，不继承旧废稿**：`论文草稿/` 为全新 v2 工程，围绕真实课题目标（《AI辅助下的DRAM存储器单粒子效应评估研究》）、真实物理建模与已核验工况从头设计结构与行文。
- **文风与去 AI 味**：严格遵守仓库内 `tcad-research-training/skills/avoid-ai-writing-zh/SKILL.md` 与 `qu-ai-wei/SKILL.md`：
  - 优先保护事实、数字、单位、物理因果、公式与引用绑定；
  - 禁止空泛意义膨胀、模板套话、机械排比、虚假让步、翻译腔和整齐空洞的收尾；
  - 用明确主语和直接动词，保留真实失败、数值局限、未验证项与判据修订披露。

## 证据红线
1. **零编造**：所有数值、样本量、误差、阈值、截面与耗时只能引用 `论文草稿/materials/asset-registry.jsonl` 中已登记的条目，并标注对应 `asset_id` 注释（`% asset: <id>`）。
2. **四态严格区分**：
   - 已验证科学结论 → 正常陈述；
   - 阶段性/诊断性结果 → 明确限定“诊断/阶段性样本”；
   - 自主放宽或修订后的判据 → 明确说明修订理由、原判据偏差与对不确定度的影响（对照 `AUTO-DECISION-LOG.md`）；
   - 尚缺外部数据或未完成批次（如导师材料 M01–M06 或在途矩阵） → 使用 `\pendingdata{...}` 显式留白，绝不提前写成“已完成”。
3. **术语统一**：遵守 `AGENTS.local.md` 术语（“服务器 / 虚拟机”，不混用磁盘/内存层级，公开正文不出现服务器别名、IP、私密路径或内部 `run_id`）。

## 每日单轮闭环步骤
1. **第 1 天（骨架定稿）**：若 `论文草稿/thesis-blueprint.json` 尚处 `BOOTSTRAP` 阶段，先结合 `shared/research-brief.md`、`plans/dram-se-ddr5-lpddr5/PLAN.md` 与当前已存在有效素材，定出精炼合理的章目大纲并写入 `thesis-blueprint.json`，同时更新 `main.tex` 与各 `sections/*.tex` 骨架。
2. **常规日（聚焦增量）**：
   - 读取当日新增的 `asset-registry.jsonl` 条目与 `thesis-blueprint.json`；
   - 选定 **1 个最高优先级章节或证据块**，由本地 Codex Worker 撰写或修订对应 `.tex` 正文与 `refs/references.bib`；
   - 更新 `thesis-blueprint.json` 中该章状态（`SKELETON -> DRAFTING -> EVIDENCE_BOUND -> REVISED`）与最近写作日期。
3. **交由 Codex 编译验收**：写完立即派发 `category=latex_build` 工单给 Codex，要求其运行 `论文草稿/build.ps1`（MiKTeX `xelatex + bibtex`），修复任何 LaTeX 语法/交叉引用/图表路径/表格溢出报错，确认零 fatal error 且无敏感泄露后提交到滚动分支。
