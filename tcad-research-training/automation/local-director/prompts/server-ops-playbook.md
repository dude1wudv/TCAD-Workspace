# 服务器仿真端到端推进手册（验收、签名、备料、投递、填槽）

本手册是本地 Codex Worker 通过 SSH 接入服务器原生 Runtime 执行端到端仿真运维的实操指南。已获维护者全权授权直接执行核验、签收、备料、批次发布、归档卸载与必要的服务重启，**严禁只做只读巡检或把写入操作“留给维护端处理”**。

## 1. 唯一执行原则
- **必须端到端闭环**：只要服务器存在空槽（`free_slots >= 2` 且 `ready == 0`）、`awaiting_acceptance > 0`、`decision_pending > 0`、`missing_material > 0` 或新收集里程碑，Codex 必须在**同一个工单内**通过 SSH 完成：**核验归档读出 → 触发/签发验收、决定、资格/Z绑定/P2放行 → 备料与更新供料配方 → 调 `month_one_supply.py` 发布验签批次 → 复查 `explain --month-one` 确认 `running + ready` 实际增加**。
- **执行账号与入口**：通过本机配置的 SSH 别名以 `runuser -u tcad -- /opt/tcad-autonomy/python/bin/python3 -B ...` 调用原生 Runtime 脚本，必要时可执行 `systemctl start/restart tcad-r06-lhs-response.service` 刷新验收与备料，但绝不杀死正常求解中的仿真作业。
- **保持唯一调度器与原账本不可篡改**：
  - 严禁另开求解池、严禁删除 `.solver.lock`、严禁杀死在途正常仿真、严禁修改或覆盖原运行目录、原 `run_id` 与原失败记录；
  - 新批次必须经原验签入口 `/opt/tcad-autonomy/python/bin/python3 -B /opt/tcad-autonomy/current/month_one_supply.py --policy /etc/tcad-autonomy/policy.json <workspace-relative-batch> <batch-sha256>` 发布；
  - 已有收据或校验缓存的目录禁止重复执行全目录 `sha256sum`；无真实 OOM/硬件故障证据禁止降并发。

## 2. 逐类里程碑的必做实操动作
1. **待验收响应与读出（`awaiting_acceptance > 0` / `find_or_extract_readout > 0`）**：
   - 使用原归档与项目标准读取器提取 35 ns 终点、三路零源积分、写入/保持极性、31.9 ns 读出裕量与数值判据；
   - 核验通过后，立即按 `r06-gate` 原规范写入或更新 `r06-gate/results/case-acceptance/<case_id>.json` 及 `z-baseline-reuse/` 验收收据；
   - 确认失败的运行按原失败谱系准备新目录与可执行 `repair_package` 交接，不留半截活。
2. **LHS 零源与细步长资格（`lhs_zero_pairs` / `lhs_halfstep_pairs` / `lhs_quartersteps` / `lhs_eighthsteps_collected`）**：
   - 对照同态粗细步长（`h`, `h/2`, `h/4`, `h/8`），核对 35 ns 终点、实际 BE 步长、三路零源积分、写保持极性以及 31.9 ns 读出裕量（原判据：两档裕量均 > 101.56 µV 且粗细差 ≤ 101.56 µV）；
   - 满足原准则的组**立即签署双 bit P0 资格和两个正式 Z 绑定**，并将资格路径写入 `local_runtime/server-codex/r06-full-supply-activation-r3/continuous-recipe.json` 约定的 `lhs_evidence` 位置，立刻解锁该组 8 个已验签输运池；
   - 若某组细化到 `h/4` 或 `h/8` 仍小幅超差且继续细化收益极低：若已获得总监签发的判据修订授权（`AUTO-DECISION-LOG.md`），立即按修订后判据签发带决策引用的资格并保留原超差记录；否则把精确的 `h/4` 与 `h/8` 实测差值与物理量级立即回传总监，下一回合由总监直接拍板放行。
3. **D2 阈值反馈与 P2 放行（`d2_threshold_feedback` / `d2_x30_feedback_collected`）**：
   - 对照原 ×10 / ×30 与同态零源，核对同事件、deck、源积分及阈值区间或删失判据；
   - 证据齐全后立即冻结并发布 P2 决定（绑定同清单 SHA、`p1_evidence.decision` 与 `lhs_native_navigation` 的 `navigation-report.json` 及 SHA-256），由原调度器消费解锁 48 个匹配输运池。
4. **输运池与响应连续供料（`lhs_transport_collected` / `response-status.json`）**：
   - 核查 `local_runtime/server-codex/r06-lhs-response-supply-r1/response-status.json` 与 `tcad-r06-lhs-response.service`；
   - 签署双态资格与输运归档就绪后，确认响应备料器冻结 S 抽样、核验真实事件源并向原调度器交付合格批次；必要时手动以 `tcad` 账号触发一次备料或直接生成 `tcad-r06-approved-supply-v1` 批次并调用 `month_one_supply.py` 入队。
   - T 后续倍率依赖同一粒子事件的首探验收；完成首探验收后立刻放行后续倍率批次；H1/H2 在留出隔离目录推进双零源备料。
5. **供料后现场复核（交卷必检）**：
   - 发布批次或更新配方后，等待 10–20 秒再跑一次 `runuser -u tcad -- /opt/tcad-autonomy/python/bin/python3 -B /opt/tcad-autonomy/current/controller.py --policy /etc/tcad-autonomy/policy.json explain --month-one`，在 `summary` 中写明操作前后的 `running / free / ready / blocked_by_stage` 真实对比数字！
