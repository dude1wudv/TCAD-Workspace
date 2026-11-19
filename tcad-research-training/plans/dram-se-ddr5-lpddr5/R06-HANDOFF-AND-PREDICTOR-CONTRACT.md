# r0.6 下游适配与 server-codex 执行交接契约

本文件将设计与预算翻译为 predictor 适配和服务器交接。用户已于 2026-11-17 授权整套执行，最新依据为 [EXECUTION-AUTHORIZATION-r06-20261117.md](EXECUTION-AUTHORIZATION-r06-20261117.md)；覆盖下文旧人工放行、细层分配及历史状态的冲突表述。只有原 server-codex/Runtime 可以提出并执行求解任务，不另建调度者。

2026-11-17 上线接口补充：冻结清单不随执行进度回改。科学验收使用独立私有记录，绑定原 case/run、完整逐文件输入 SHA 映射、原结果 SHA 和真实验收证据；实际记录格式见网站 `ops/DATA-SOURCES.md`，执行事实见 [DEPLOYMENT-REPORT-r06-20261117.md](DEPLOYMENT-REPORT-r06-20261117.md)。原生 manifest 的 `input_sha256` 是文件名到 SHA 的映射，不能误当成单个字符串。科学通过与统计资格分别管理；前者不能替代完整抽样、分母和纳入概率核验。网页尚未接入资格快照时须明确提示，不把静态清单中的 0 当成动态资格计数。正式训练只消费经过核验的研究数据快照，公开状态 JSON 不作为训练数据源。

最终网页 revision 为 `e9cea0bfcd8b9c9d4c34ccea1c3c8eaae4653175`。新增的
`tcad-r06-z-baseline-reuse-v1` 私有记录用于把完整 WHR P0 基线绑定到正式 Z：
必须匹配冻结清单 SHA、profile、stored bit、`r06-hold-window-v1` 与保持窗、
两个 bit 的 profile 资格、原 manifest 的完整输入 map/结果 SHA，并声明
`run_kind:"full_whr_baseline"`、`is_prefix:false`。它只打开该 Z 的工程
`solved` 映射，不自动产生 `accepted`、统计资格或训练数据；短 prefix、旧 r04
结果和普通 P0 诊断继续排除。网页最终复跑 122 项，服务器 113 通过、9 项跳过；
第一次同 revision 执行在最终 payload 断言退出，随后完整重跑通过。

最新服务器观测为 `2026-11-17T19:44:44Z`：D0 O2 短零源、D1 网格测量、
D2 网格测量明确运行，D0 prefix-b 已成功收集并释放。该状态只证明 Runtime
继续推进，不授予 O2/O3/WHR/Z、训练、截面或错误率结论。

---

## 1. `predictor/` 升级适配清单（核对现有源码现状）

现有 `predictor/`（参见 [predictor/README.md](../../predictor/README.md) 与 [predictor/SCHEMA.md](../../predictor/SCHEMA.md)）按 `r0.4/r0.5` 契约编写，当前已支持 60,000 条 `transport_only` 输运快照，但尚不能直接消费 `r0.6` 数据。逐模块适配缺口如下：

| 文件 / 模块 | 现状（已核实代码行为） | r0.6 必须适配的改动 |
|---|---|---|
| [predictor/SCHEMA.md](../../predictor/SCHEMA.md) | 仅定义 `r0.4`，`sampling` 仅限 `random/enriched`，假定 `b0/b1` 成对 | 升级为支持 `simulation_revision: "0.6"`，补充 `deck_timing_version`、`source_time_ns`、`scale_factor`、`inclusion_probability`（`π_j`）及 `b1`-only 非成对响应协议 |
| `predictor/src/dram_predictor/data.py` | 第 164–166 行硬拒绝 `simulation_revision != "0.4"`；第 11 行 `COHORTS` 不含 `radiation_holdout`/`profile_holdout`；第 291–295 行硬要求 `device_extrapolation` 的 `gate_length_nm > 15.4`（会错误拒绝 `H1/H2` 两个逐轴范围内稀疏组合留出点）；第 350–351 行只允许 `sampling in {"random", "enriched"}` | 1. 放开版本集合 `{"0.4", "0.6"}`；<br>2. 扩展 `COHORTS` 并按 `split/holdout` 区分“外推留出 `H0`”与“逐轴范围内稀疏组合留出 `H1/H2`”，取消对 `H1/H2` 的 `Lg > 15.4` 硬限制；<br>3. `sampling` 扩展为 `{"simple_random", "stratified_pi", "threshold_scaled", "active_learning", "no_particle_control"}` 并校验 `π_j ∈ (0, 1]` 与 `scale_factor > 0` |
| `predictor/src/dram_predictor/features.py` | `DEVICE_FEATURES` 已包含 `oxide_thickness_nm`、`junction_depth_nm`、`acceptor_scale`、`donor_scale`，`LOG_FEATURES` 已对 `acceptor_scale/donor_scale` 取对数 | 在 `record()` 中保留 `scale_factor` 对 `source_features`（`generated_charge_fC` 等）的显式缩放语义或传入 `R`，同时严禁把 `scale_factor` 或 `selection_mechanism` 漏给仿真前模型 `F` |
| `predictor/src/dram_predictor/r_training.py` | 支持逐行 `response_id` 采样与按 `source_primary_id` 分组 mini-batch，但默认假定概率校准只读 `random` 标识 | 允许 `b1`-only、自适应 `threshold_scaled`（`scale_factor > 1`）与 `active_learning` 样本进入 `R` 训练和 `Qcrit,eff` 边界学习；在 `calibration.py` 温度标定阶段严格过滤，只允许 `simple_random`（或经核验 `π_j` 加权的 `stratified_pi`）折外样本参与概率校准 |
| `predictor/src/dram_predictor/aggregation.py` | 当前无权全池聚合不能直接消费稀疏抽样 | 先实现并核验 `A_src/N*Σ(y/π)`；R为`π=n/N`，S/HR/HP为完备粗层内`q_h/N_h`，b0另乘条件选择概率。R/S分别报告，不默认残差修正无偏或自动合并；缺失层/标签/方差自由度如实拒绝相应结论 |
| `predictor/src/dram_predictor/splits.py` & `f_training.py` | 共享 profile、primary、control 可形成跨器件连通组 | 用实例化后的真实来源构图，不预设“必有9组”。每profile模板独立准备，合法CRN共享保留；若只剩1组或不足3组，不能拆来源伪造三折。AL不引入HR/HP，稀疏b0只监督有证据的状态 |

---

## 2. `server-codex` 交接提案（P0 与 Geant4 磁盘安全规则）

### 2.1 历史服务器基线（需由部署前实时核对覆盖）

- 截至 `2026-11-17T14:41:34Z`（`<SERVER_STATE_DIR>/observation.json`）：仅剩 `r04-l08-p000-nodal-whr-b1-zero-mc2-v1` 在 slot 2 运行（`active_count=1`），4 条 `mc2-r2` 与 `b0 zero` 已 `COLLECTED`。**禁止中止该活动作业，等待其自然收集并释放槽位后再启动 `r0.6` P0。**
- 已暴露的阻塞证据（`<SIM_USER_HOME>/course-workspace/experiments/dram-se-r04/electrical/mc2-b0-zero-pairing-result-r1/observations.json`）：`b0 zero` 耗 `4.14 h` / `1,123 万行` 日志，且与 `event0/event7377` 从第 3 行静态步及 `t=1e-13 s` 起存在 `~1e-19 A` 差异，被 `extract.py compare` 拒配对（`exit code 2`）。

### 2.2 P0 按序推进清单（证据核验后自动放行，不再询问用户）

1. **步骤 P0-1（数值可重复性诊断 + O2 重复日志控制）**
   - 虚拟机保持9核/28 GiB，批量采用原r4的4×2；运行器保留读取已收集r5性能测试历史的兼容能力，控制器不启用r5调度配置。2×4仅是后续空闲池内的调试选项。排查实际采用配置的静态/初态微差，保留Optics/PMI同一路径与原失败；旧判据不回改，新比较器须独立版本、误差依据和验证。
   - **2026-11-17 用户确认的 O2 修订**：修改 `pmi_r04_nodal.C` 的日志控制，将每实例 `callbacks_` 改为进程/插件全局原子计数与有界输出，重复初始化日志也纳入限制；保留关键进度、警告、错误、收敛失败和完成摘要。粒子源数据、物理公式、mesh 和求解设置不变，不设“百行级”或固定提速倍数；只有接口能确认接受状态时才写“已接受时间步”，不将回调次数冒充时间步。相同资源配置下完成短探针源数据/积分与波形核对及至少 1 条代表长任务对比，采用事先冻结、有误差依据的数值一致性标准，不要求双核结果必然逐位相同，不按结果放宽；记录日志/归档大小、wall/CPU 时间。并发/线程测试保持同一日志版本，日志优化效果单独比较。验收口径以 [DESIGN-REVIEW-20261117.md](DESIGN-REVIEW-20261117.md) 的 O2 条目为准。
2. **步骤 P0-2（O3 新保持窗时序 `D0 b1/b0` 验证）**
   - **2026-11-17用户确认的O3修订**：基于`prepare_write_read.py`另建验证输入，不覆写旧目录。将研究场景限定为写释放且位线预充后的18.2–30 ns保持窗；22 ns及`r06-hold-window-v1`目前只是候选，不视为已经冻结的正式时序。
   - 先核对D0的b1/b0无粒子基线，确认22 ns及附近时刻的切换影响、保持漂移与读出裕量；依据该基线事先选择附近保持期时刻，再固定少量代表事件、空间分布、幅度、脉冲形状和数值设置做时刻敏感性验证。源脉冲与其细步长窗口同步平移；验收源积分相对误差`<1e-9`、P0-1配对标准及31.9 ns读出，记录注入状态和到读出的时延。不能按翻转结果挑注入时刻，也不能将保持期结果与旧15 ns写入期结果混作同条件。
   - 验证后再冻结正式时序、读出协议、输入哈希及版本。若最终时间或协议变化，先更新预算来源、清单及下游契约再提交正式批；现有planned清单22 ns字段维持候选含义。诊断单独记录成本和来源，不计入396条正式计划完成量或统计分母；明显时刻依赖须进入后续实验/预测定义，不能外推整个保持期。
3. **步骤 P0-3（13 个 profile `Z` 块全量无粒子 WHR 体检）**
   - **2026-11-17整套执行授权**：13点现有参数保持；各自b0/b1无粒子写入、保持和读出验证，事件标签使用各自匹配对照。不得用D0替代其它锚点；单点不合格仅暂停其依赖分支，不算粒子翻转。
   - 将 [month-one-cases-r06.json](month-one-cases-r06.json) 中 Block `Z` 的 26 条无粒子写保持读任务纳入前置体检；检查 `electrical_candidate.py`（当前硬编码 `x=31 / 123` 仍落在 13 个 profile 柱内，但推荐改为按 `(x0 + Lsn/2)` / `(x1 - Lsn/2)` 动态计算）并生成各 profile 的 `cell_msh.tdr` 与 `WHR` 波形。
   - **隔离纪律**：对 `H0–H2` 仅做与 `D0–D3/LHS` 隔离的“可写/可保持/可读收敛性及工程基线确认”，禁止把留出 `Z` 波形或读出裕量用于调整开发侧 `t0`、电路参数或机理拟合。
   - 汇总P0证据、输入/时序/比较器hash及真实判定，由执行方自动核查放行；不再要求用户再次批准。未通过不得提交依赖版本的正式粒子瞬态，旧15ns结果不得混入；必要P0粒子诊断单独记成本。

### 2.3 Geant4 分波次空间规则（P1/P2/HR/HP 执行期）

- 沿用 `nine` 单核 profile 在空闲池轮换运行（全局最多 4 任务）。
- 当前清单实际去重97池（开发72/HR6/HP19）。历史`10^4`约92MiB只作估计起点，不把线性外推当容量验收；以部署时服务器、虚拟机内和底层写入池实际可用量为准。
- **执行规程**：
  1. 每波按实际字节、在途输出、收集副本与保留事务定额；不承诺固定2–4几何安全，也不保证15–25分钟完成；
  2. 每波收集后即运行输运提取（`extract_transport.py`）生成硅区/事件级紧凑快照，并按 `RESULT-RETENTION.md` 流程即时压缩/清理虚拟机 `.collection/results.tar` 与重复大 `steps.csv`；
  3. 虚拟机`/home`、服务器上虚拟机磁盘文件可增长空间、服务器根均保留缓冲，服务器至少20GiB，之后才提交下一波。
