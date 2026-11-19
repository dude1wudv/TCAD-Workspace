# GitHub 协作说明

本文件面向通过 GitHub 接入的云端代理、协作者和本地维护者。

## 仓库定位

- 仓库：`https://github.com/dude1wudv/TCAD-Workspace`
- 默认分支：`main`
- 结构：单仓库，不包含 Git 子模块
- 内容：DRAM 单粒子效应研究的仿真代码、计划、对齐文档、前端源码和小型证据
- 不包含：原始数据、运行目录、服务器凭证、许可证、密钥和大型二进制

## 云端代理工作流

1. 从最新 `main` 创建分支，例如 `agent/fix-status-projection`。
2. 只改与任务相关的文件，先读对应目录的 `README.md`、`AGENTS.md` 和计划。
3. 本地或云端执行最小验证，记录实际命令和结果。
4. 提交并开 Pull Request，说明改动、验证、未验证项和风险。
5. 由维护者合并到 `main`。本地自动拉取任务随后更新工作区。

不要直接推送 `main`。不要在 PR 中混入无关格式化、批量重命名或临时文件。

## 改动边界

- 代码和文档可以改；实验账本、运行身份、原始结果和科学结论不能改写成“已完成”。
- 计划、推断、诊断证据和正式结论要分开写。
- 不把短测试、单次求解或静态截图当成完整验收。
- 不提交 `local_runtime/`、`output/`、`node_modules/`、`dist/`、`vendor/`、原始数据、视频、压缩包、PDF、DOCX 或大图。
- 不新增服务器地址、SSH 别名、许可证、Token、密钥和本地 `AGENTS.local.md`；仓库中的部署默认值不含凭证。
- 需要 SSH、求解、部署、清理或许可证操作时，只在 PR 中写建议，不直接执行。

## 验证命令

Python 代码：

```powershell
python -m compileall tcad-research-training/scripts tcad-research-training/automation tcad-research-training/predictor xjtu-shop-site/status-checker
```

前端：

```powershell
cd xjtu-shop-site
npm ci
npm run build
npm run test:status
```

训练工程测试依赖原运行环境、数据路径和许可证，不能保证在云端完整运行。PR 中要写明哪些测试实际运行、哪些未运行。

## Pull Request 要求

- 标题简短说明目的。
- 描述包含：改了什么、为什么改、验证命令、结果、未验证范围。
- 涉及实验计划时，注明对应 run、数据来源和证据等级。
- 涉及前端时，注明桌面/移动、亮色/暗色或状态数据的变化范围。
- 不提交构建产物、缓存、日志和本地配置。

## 合并后的本地自动拉取

Windows 计划任务 `TCAD-Workspace-AutoPull` 每 5 分钟运行一次，并在错过计划后尽快补跑：

```powershell
pwsh -File scripts/git-auto-pull.ps1
```

行为：

- 已跟踪文件没有本地修改时，先 `git fetch`，再尝试 `git merge --ff-only origin/main`；未跟踪的本地数据不阻止拉取，若与远端新增文件冲突则由 Git 拒绝合并并记录日志。
- 已跟踪文件有未提交改动、分支分叉或快进失败时，只写日志，不覆盖文件。
- 不自动 stash、不自动 reset、不自动解决冲突。
- 日志：`logs/git-auto-pull.log`。

手动检查：

```powershell
git status --short --branch
git log --oneline -5
```

关闭自动拉取：

```powershell
Unregister-ScheduledTask -TaskName 'TCAD-Workspace-AutoPull' -Confirm:$false
```

## 旧仓库与恢复

迁移前的两个仓库仍保留在 GitHub：

- `dude1wudv/tcad-research-training`
- `dude1wudv/xjtu-shop-site`

本地迁移前历史备份在工作区外：

- `E:\TCAD-Workspace-git-backup-20261119`

需要恢复某个子仓库的独立 Git 工作区时，把备份中的 `.git` 目录移回对应目录，并核对工作树状态。不要在公开仓库中重新引入子模块，除非维护者明确决定改变仓库结构。

## 安全与隐私

- 公开仓库的文档已脱敏；代码中的部署默认路径来自本机配置，只作默认值，不含密钥，实际路径以本地私有配置为准。
- 发现误提交的密钥或内部地址时，先停止继续推送，通知维护者处理；仅在后续提交删除并不等于从历史中移除。
- 不把公开仓库当作服务器备份或原始数据仓库。
