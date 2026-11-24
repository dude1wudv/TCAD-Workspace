# 论文草稿工程（v2 从零重构）

本目录为课题 **《AI辅助下的DRAM存储器单粒子效应评估研究》** 的全新 v2 论文源码工程。

- **写作机制**：由 Gemini 4 Neon (High) 每日集中推进 1 次（Daily Thesis Sprint），严格遵循 `tcad-research-training/skills/avoid-ai-writing-zh/SKILL.md` 与 `qu-ai-wei/SKILL.md`。
- **素材与编译机制**：Codex (`auto/gpt-6.2-sol`) 负责从真实仿真/预测器产出中提取指标、绘图制表、写入 `materials/asset-registry.jsonl` 并运行 `build.ps1` 验证 LaTeX 编译。
- **科学边界**：正文严格区分已验证结论、阶段性诊断、已登记的判据修订（见 `tcad-research-training/plans/dram-se-ddr5-lpddr5/AUTO-DECISION-LOG.md`）与尚未就绪占位（`\pendingdata{...}`），禁止编造数据或泄露私密主机路径与内部 `run_id`。

## 本地编译

```powershell
.\build.ps1
```
