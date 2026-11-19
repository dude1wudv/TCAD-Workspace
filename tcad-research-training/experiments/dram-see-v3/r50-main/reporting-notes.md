# R50-main 独立阶段报告（reporting r1）

本模块生成不可覆盖的部分/主矩阵观测报告；不调度、不提交、不计费、不修改 ledger，也不读取正在写入的结果。它不进入首段 `source-manifest.json`，自己的依赖固定于 `reporting-manifest.json`。适用冻结设计 SHA256 为 `6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740`。

## 使用入口

由主代理在安全读取边界执行。以下是命令模板，不是本模块已经生成真实报告或已经完成仿真的证据。`SNAPSHOT_ID` 必须替换成新目录名。

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/reporting.py `
  --design experiments/dram-see-v3/r50-main/design.json `
  --ledger local_runtime/dram-see-v3/ledger.json `
  --stage-index local_runtime/dram-see-v3/physical-revisions/r50-main-r1/stage-index.json `
  --snapshot experiments/dram-see-v3/r50-main/data/reporting/SNAPSHOT_ID
```

`--design`、`--ledger`、`--snapshot` 均显式必填；只接受本冻结设计和唯一全局 ledger。可省略尚未存在的 `--stage-index`，但相应阶段只能未验证。`--no-plots` 明确跳过绘图依赖，保留 JSON/CSV/Markdown；不是图件验收。默认使用现有 venv 的 matplotlib/numpy，不安装依赖。

正常收集的部分报告返回 0，表示报告生成成功，不表示仿真、门槛或课程完成。原档/ledger/阶段证据错误保留在 `summary.errors` 与 Markdown，并在写完错误可见的部分报告后返回 2。设计/源码漂移、错误输入、预算重复 run ID、正在变化的证据、缺失渲染依赖等致命错误直接抛异常，不能以缺失状态掩盖。已有快照目录始终拒绝覆盖；渲染途中失败留下未完成目录，不能把它当含完整 `snapshot-manifest.json` 的报告，需使用新目录重试。

所有 JSON 禁止 NaN/Infinity。快照包含 `summary.json`、128 行 `responses.csv`、96 行（三阈值）`statistics.csv`、`initial-state.csv`、`sources.json`、数据 PNG/SVG 与逐图来源、`report.md`、课程草案索引和完整输出文件 SHA256 清单。没有已完成观测时只生成计划槽位状态图，其含义是状态计数，不是零响应点。不会造初态、瞬态、拟合/残差或氧化层曲线。

## 原始证据与版本边界

- 只接收全局行 `VERIFIED`、runner exit 0、fresh 非 inherited，且 schema=`dram-see-v3-r50-main`、revision=`r50-main-r1`、probe_only=false、Rpre=50 Ω、关断1e20 Ω。旧100 Ω、probe和未知版本不能作为事件、对照或中性电学观测。
- 每项从 R50 `audit.load_curves(run_id)` 重审 `inputs.tar`、`results.tar`、manifest、哈希、退出码、实际源与模型合同、初态、预充、4 ns终点、KCL/BE/电荷及源积分。归档参数、输入哈希、结果哈希必须等于 ledger；不能以缓存指标代替。
- 原 R50 `metrics.compute_curves` 再要求完整参数合同及实际 mesh bytes 相同，匹配同尺寸/位/氧化层/步长/网格的信号、无粒子对照和中性。main 坐标、粒子、能量、seed及0/1身份逐个对照冻结64事件；变体不补齐 main 槽位。
- 内存缓存仅在一次收集中去重，最终重新哈希全部读取源，并核对 ledger/阶段 JSON 原字节未变化。归档路径、输入/结果/mesh哈希和所有使用源码版本进入快照。输入在收集期间推进则拒绝，不能混合两个 ledger 时点。
- 首段8个物理参考与2个源隔离从原档重新比较两侧BL、D和全部阈值，并精确核对保存的 comparison JSON。声称 VERIFIED 的 references/pilot 还必须含固定20/10项原档记录与每项当前哈希；缺证据不推定通过。
- 预登记细化重新读取自身两组三联归档，调用 R50 纯 `compare_observations` 重算，对照每个已存输出字段、阶段状态及确切6个变体归档。仅真实匹配证据可消除该预登记响应的近界不确定；不能套用到整个矩阵。

上述路径没有调用 `controller.py`、`run.py`、SSH、求解器、GUI，也不执行旧 export。首段运行器与后半开发模块不成为此报告运行依赖。原报告仅复用版本化纯 `statistics.py` 和 `plot_results.plot_snapshot`；旧 `summarize.py`/`report.py` 的收集、预测、oxide/native loader 均不执行。纯解析依赖包含 v1 `analyze.py` 的字节/曲线函数；不复用旧电学数值。

## 科学与统计口径

固定64独立事件、128配对位响应。每个尺寸×粒子×方向×存储位计划N=4，2.5/5/10 mV全部保留。correct、criterion_error、critical、numerically_uncertain、failed、missing分别计数；任何未取得匹配指标的槽位不能填0或自动正确。

带符号 ΔQ 在2.8 ns以fC保留；D=BLsignal−BLneutral，M=(2b−1)D(4 ns)，ΔM=Mcontrol−Mevent，另存3.8–4 ns窗口。critical不筛除连续目标。ledger显式连续数值失败、false标记或未知非空状态使连续量无效，原值仍作诊断保留且全部阈值为数值不确定。距任一±阈值≤0.5 mV且没有完整两种匹配细化证据时，保留该阈值不确定；分类跨界与连续容差失败分别传播。

Wilson双侧95%最佳/最差赋值包络使用原计划N=4；未知赋值形成部分识别区间。只在全部可判且零误读时给单侧95%精确零事件上界，N=4约52.7%。0/1配对不合并成128个独立事件，复跑/网格/氧化层均不增加独立样本。所有区间都是分层描述，不承诺多重比较同时覆盖。

预算仅汇总唯一全局 ledger 的非 inherited 实际计费行，优先 `charged_solver_s`、缺失回退保守 `elapsed_s`。保留旧100 Ω、probe、失败、验证和R50-main的费用；绝不新增计费、清零或将阶段索引重复加总。未结运行、尚无费用单独列出，累计值是当前已登记值，不把未来耗时视作0，不构成提交授权。

## 尚未适配的后半范围

本 r1 对预测冻结/测试评分、氧化层、最近边界、native/实际视觉复核，以及自然语言学生演示统一保持 `UNREVIEWED_OR_MISSING` / PENDING；不加载正在开发的 `prediction.py`、`finish.py`、`transport_adapter.py` 或GUI实现。不根据文件存在或其他阶段状态猜测已通过，不重拟合模型。即使获得128个主响应，状态也仅为 `MAIN_MATRIX_OBSERVED_LATER_GATES_UNREVIEWED`，仍不能宣称全流程完成。

后续适配必须独立版本化、重审新接口与原始证据，保留本版本快照。`CAPTURED_PENDING_VISUAL_REVIEW` 不能作为视觉通过，本版本不展示任何原生图；生成的数据图均标 DATA PLOT。适用模型仍为未校准二维1T1C，理想初态不等于实际写入校准，判据误读不等于持久位翻转或商业DRAM辐射截面。

课程草案按 `docs/course-project-syllabus.md` 的真实要求给入口；不补造2–3学生分工、教师审核、资源交接、答辩、考核或现场演示。旧设计完成记录不自动满足R50项目新证据需求。

## 开发验证

私有 `local_runtime/dram-see-v3/r50-report-dev/self_check.py` 全部显著标 SYNTHETIC。测试在专属时间戳目录生成数据和图，不发布生产报告，原档审计函数在逻辑fixture中明确stub，不能证明新真实TCAD归档通过。

命令：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B local_runtime/dram-see-v3/r50-report-dev/self_check.py
```

最新 `test-reporting-02.log`：15项通过，exit 0。检查空/部分/完整固定矩阵、六类状态、连续量与critical分离、近界两变体规则、旧版本/probe/错槽拒绝、RUNNING不读、ledger与原档哈希/重复run保护、参考虚假完成拒绝、数值重算/六原档绑定及篡改拒绝、全局预算不变、阶段plan哈希、不可覆盖、合成禁止生产路径、全缺失只状态图、部分5图来源及无伪native。原13项日志保留。

没有执行真实收集/发布、SSH、求解、GUI、安装或Git操作。真实新快照、PNG逐图目视及独立验收由主代理执行；上述软件测试不替代这些检查。
