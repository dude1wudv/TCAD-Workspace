# 相关技能清单

本次扫描了用户 Codex 技能和工作区技能入口；本项目专用旧入口只有 sentaurus-vm-runner。
一并整理文献、推导、科研路由与中文写作的五个相关用户技能，新增三课程技能。
所有 SKILL.md 含 YAML 文件头在内均不超过 50 行，核心流程可独立阅读。

| 技能 | 行数 | 用途 |
|---|---:|---|
| `sentaurus-vm-runner` | 30 | 9vCPU/28GiB虚拟机最多9任务各1核，12核服务器留CPU9–11管理；运行/恢复/收集 |
| `research-lit` | 23 | 文献和引用证据 |
| `formula-derivation` | 22 | 公式与假设 |
| `aris-anything` | 11 | 科研任务路由 |
| `avoid-ai-writing-zh` | 25 | 中文审核 |
| `qu-ai-wei` | 26 | 中文改写 |
| `dram-course-workspace` | 23 | 三课程共用资料与交付，沿用九任务上限及资源准入 |
| `tcad-experiment-plan` | 28 | 按导师任务生成/修订研究计划、数据与训练设计、服务器交接；项目源已创建，未同步安装 |

维护源：仓库 `skills/`；本机安装：用户 `~/.codex/skills/`。
服务器安装目标：TCAD 仿真用户 `~/.codex/skills/`，具体同步状态见本次整理报告。
`sentaurus-vm-runner` 保留技能名，行为改为复用云端现有运行器。
已授权的新批次使用9vCPU/28GiB的CentOS7.9虚拟机，新profile显式parallel_capacity=9（r3），共享slot0–8；12核/32GB的Rocky9服务器限定QEMU使用CPU0–8，CPU9–11留管理。旧profile缺省3及显式7保留，旧任务不改、不另开池，容量仅在空闲池切换；内存/许可不足降并发。九槽已部署，九并发短探针已完成收集，授权或离线检查通过不表示性能验收通过；实际状态见server-workflow与最新交接。
旧固定 IP、自动许可恢复和第二套 PN 运行脚本已从有效入口移除；旧脚本已校验归档。
原通用技能仍可用于其他项目；TCAD 专有规则只在相应项目上下文生效。
老版说明及界面元数据修改前副本见工作区归档，不把冗长旧文作为每次必读附件。

documents、pdf、presentations 等为系统/插件托管技能，按实际文件任务调用；
不直接重写插件缓存，也不把其长篇内容复制进本次技能包。
系统 skill-creator 用于本次维护，不作为课程运行技能复制。
技能文件部署不表示远端已安装/登录 Codex，也不表示仿真或课程成果已验收。

2026-11-16新增计划技能见 [tcad-experiment-plan](../skills/tcad-experiment-plan/SKILL.md)，实例为 [DDR5/LPDDR5实施计划](../plans/dram-se-ddr5-lpddr5/PLAN.md)。用户最新资源选择为9个独立单核任务并行；计划、运行技能维护源和已部署九槽profile现已对齐。九并发短探针已完成收集，数值与资源验收见server-workflow；本机及远端技能安装状态以nine-guidance-sync.json收据为准。
