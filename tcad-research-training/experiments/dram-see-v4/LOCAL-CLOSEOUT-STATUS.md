# DRAM SEE v4 当前原作业收尾状态

最后实际观察：**2026-10-21 08:38:12 UTC，RUNNING**。

用户最新要求尽快结束当前任务。本轮停止自动推进并暂停 Goal；当前正常原作业保留原 owner/runner/共享锁自然运行，没有终止、清锁、重投或启动其他原生任务。**原作业尚未单次收集；完整课程没有完成。** 本文件记录的是最后观察，不会在暂停后自动刷新。

| 项目 | 原始身份/状态 |
|---|---|
| run ID | `20261021T004925Z-v4-2d-a0-g80-2p4v-waveform-frames161-main-b1-r1` |
| 原目录 | `/srv/tcad-dram-see-v4/runs/20261021T004925Z-v4-2d-a0-g80-2p4v-waveform-frames161-main-b1-r1` |
| 本地 manifest | `local_runtime/runs/20261021T004925Z-v4-2d-a0-g80-2p4v-waveform-frames161-main-b1-r1/manifest.json` |
| wrapper | PID `102071`，start ticks `25679406` |
| SDevice | PID `102162`，start ticks `25680306`，CPU0，数值线程1 |
| boot | `ed9b6579-cd76-45c0-8242-a3bcec06b401` |
| input-manifest SHA256 | `ae12d3f9447f929a3437df01aa4b56c3e80345fcddf5cc9656b2877f04265071` |
| 最后模拟时间 | `7.61016e-8 s`，已到本次A0源窗口末端，尚待后续读出与终态核对 |
| 最后电压 | SN `1.15350678327225 V`，BL `0.600039655924155 V`，WL `-0.5 V` |
| 已观察实际用量 | SDevice CPU `25972.77 s`；RSS `1873844 KiB`；swap `0 KiB`。不是最终全程用量。 |
| 终态 native/remote/SSH/collect 退出 | 尚未取得终态与收集证据，不填0 |
| results.tar / collection_verified | 尚未收集，SHA与验证状态待补 |
| 新版完整源帧/字段/科学/训练资格 | 尚未验证，不能宣称通过 |

原始观察：`local_runtime/dram-see-v4/continuous/actual-usage/20261021T083812Z-a0-waveform-frames161-main-b1-r1-native.json`。

接续时沿 [服务器接续计划](SERVER-CONTINUATION-PLAN.md) 第2节查询原作业。确认终态且尚未收集后，只通过原 `scripts/tcad.py collect <原Run ID> --json` 收集；若已收集就复用。断连先查原目录，身份不符保留中断证据，不重复提交，不清锁。

接续收尾尚需：真实退出与归档完整性、输入/结果SHA对应、完整时钟和源帧Writing对应、完整写读/KCL本地减缩，并补齐本文件和机器状态。字段提取、dt2/h2、粒子及后续矩阵全部留给服务器阶段，本轮不启动。
