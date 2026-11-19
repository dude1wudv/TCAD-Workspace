# 云端独立入口

## 当前覆盖：r0.6 执行（2026-11-17）

本节覆盖下文旧九并发和r0.4预算。先读AGENTS.md、docs/server-workflow.md与plans/dram-se-ddr5-lpddr5/EXECUTION-AUTHORIZATION-r06-20261117.md；当前13个profile、396计划槽位，214统计用途上限、当前合格0。P0通过后按证据自行推进，无须再问用户。

服务器12核/32GB，虚拟机当前9核/28GiB。TCAD原mc2-four/r4为4并发×2核；Geant4固定原nine单核profile，只在原池空闲边界轮换，全局最多4项。唯一调度者为tcad-autonomy.service的原Runtime；保持原池、锁、身份和收集租约，不重投未知run，不另开求解器。服务器使用python3.12运行原runner。

最新release为20261117T184322Z-r06-intent-reconcile-r1，部署证据在<SERVER_STATE_DIR>/operations/20261117-r06-intent-reconciliation-r1/。最新执行事实读<SERVER_STATE_DIR>/observation.json；服务在线、工程收集与科学通过分别判断。网站已用r06正式清单投影，P0单独记账，HR/HP明细封存。磁盘分别报告服务器剩余空间、虚拟机分配空间、虚拟机剩余空间和服务器上虚拟机磁盘文件可增长空间，不相加。

## r0.4自主运行交接（2026-11-16）

tcad-autonomy.service已获授权启用，server-codex是本批唯一调度者，使用原九槽profile和原runner。本地代理只读跟踪、提供决定和必要修复，不另开提交者。断连后沿原run身份恢复；当前状态查<SERVER_STATE_DIR>/observation.json，执行历史见plans/dram-se-ddr5-lpddr5/EXECUTION.md。正式模型训练尚未启动。

## 当前运行入口（2026-11-16）

服务器12vCPU/32GB，完整CentOS7.9虚拟机9vCPU/28GiB；新授权任务使用九槽r3 profile，最多9个单核任务，QEMU仅用CPU0–8，CPU9–11暂留管理。旧3/7 profile、旧结果和失败证据保留，两接口共享同一池，原任务不重投；实际验收范围见docs/server-workflow.md。许可证许可校验工具原完整性失败仍未解除，不由实际求解成功替代。

本目录部署现有runner、说明/技能、验收输入和本次云端归档；未迁入本机旧仿真结果。
Rocky服务器管理通过管理入口；虚拟机SSH通过私有回环转发。

```sh
cd ~/course-workspace
python3.12 scripts/tcad.py --connection local_runtime/cloud-benchmark/connection-local-centos79-nine.json --help
ssh -F <VM_SSH_CONFIG> 虚拟机仿真入口
```

新任务必须先读AGENTS.md、docs/server-workflow.md和当前迁移验收报告。
不启动源VM，不根据旧文档重投D2；数值、资源及正式许可分别以docs/server-workflow.md的实际验收为准。
Codex/Magpie在Rocky服务器运行，商业仿真工具在CentOS虚拟机内运行。
