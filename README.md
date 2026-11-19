# AI辅助下的DRAM存储器单粒子效应评估研究

这是同一导师课题的工作区，科研训练、项目设计和毕业设计共用实验、代码、文献、图表与报告素材。

公开仓库只保留可复现的代码、计划、对齐文档和小型证据。原始仿真数据、运行目录、服务器凭证、许可证材料和大型交付文件留在本地或服务器，不进入 Git。

## 仓库内容

| 位置 | 内容 |
|---|---|
| `tcad-research-training/courses/` | 三门课程的入口、要求和交付边界 |
| `tcad-research-training/shared/` | 共享研究口径、证据索引、报告复用和文献入口 |
| `tcad-research-training/plans/` | DDR5/LPDDR5 实验计划、预算、对齐与交接文档 |
| `tcad-research-training/experiments/` | 仿真代码、冻结计划、诊断记录和小型结果摘要 |
| `tcad-research-training/automation/` | 云端运行器、控制器和校验代码 |
| `tcad-research-training/predictor/` | 截面与错误率预测模型代码 |
| `tcad-research-training/research-desk/` | 研究台前端源码和服务端说明 |
| `xjtu-shop-site/` | 公开研究主页、状态页和状态检查器源码 |

## 快速开始

### 仿真与脚本

```powershell
cd tcad-research-training
python -m compileall scripts automation predictor
```

真实求解依赖商业 TCAD、Geant4、许可证和共享运行池。本仓库不包含这些环境，也不在云端执行仿真。

### 前端

```powershell
cd xjtu-shop-site
npm ci
npm run build
npm run test:status
```

`node_modules/`、`dist/` 和本地依赖目录不提交。

## 云端协作

云端代理通过 GitHub 连接本仓库，在分支上提交改动并开 Pull Request。协作规则、验证要求和数据边界见 [GitHub 协作说明](docs/GITHUB-COLLABORATION.md)。

本仓库的公开版 `AGENTS.md` 只包含通用协作约定；公开文档中的服务器地址、SSH 别名和许可信息已脱敏。代码中的部署默认路径来自本机运行配置，只作默认值，不含密钥；完整本地约定保存在不入库的 `AGENTS.local.md`。

## 本地自动拉取

Windows 计划任务 `TCAD-Workspace-AutoPull` 每 5 分钟检查一次 `origin/main`。已跟踪文件没有本地改动且可以快进时才拉取；本地有未提交改动、分叉或拉取失败时只写日志，不覆盖本地文件。

手动执行：

```powershell
pwsh -File scripts/git-auto-pull.ps1
```

日志默认写入 `logs/git-auto-pull.log`。

## 不进入仓库

- `local_runtime/`、`output/`、原始仿真结果和大体积数据
- `T2024-09.rar`、Git bundle、视频、构建产物和 `node_modules/`
- 新增的服务器地址、SSH 别名、许可证文件、密钥和本地私有约定；既有部署默认值不含凭证
- 归档副本、Obsidian 数据、临时目录和历史交付压缩包

## 证据边界

仓库中的计划、状态摘要和历史结果摘要按原记录保留，不表示所有实验均已复现或通过科学验收。运行状态、原生求解、收集完成和科学结论分别判断。

旧仓库 `dude1wudv/tcad-research-training` 和 `dude1wudv/xjtu-shop-site` 保留为历史参考；本地迁移前的 Git 历史备份在工作区外，可按需恢复。
