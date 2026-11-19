# v3 阶段汇总、图件与报告生成

本模块只读取已完成证据并生成派生成果，不提交求解、不连接VM、不修改旧目录。脚本为 `summarize.py`、`plot_results.py`、`report.py`；模型、判据、训练划分和原始证据不由它们改动。

2026-10-10 16:33 UTC更新：获准4项追加诊断完成，独立`report_precharge_diagnostic.py`绑定完成的diagnostic JSON、9份原归档和冻结解析器，生成诊断专用CSV/两张PNG及SVG。两个粒子响应仍FAILED，全部诊断数值不进入主计数或预测评分；见[诊断报告](diagnostic-report.md)及`data/diagnostics/precharge-additional-r1/sources.json`。该脚本实际退出0，主代理查看两张PNG。原主报告生成器未改动，重新publish退出0，快照`20261010T162904634835Z`保留10匹配响应/1主失败/117缺失、全局17782.66s；主阈值图与计数图已查看。32份主报告归档和9份独立诊断归档各按用途复核，不能将审计次数当新增样本数。

最新实际验证（2026-10-10 15:18 UTC）：在训练科学门槛停止并确认无活动调度者后，完成阈值窗口的系列/阈值图例修订，生成快照`20261010T151648658323Z`，实际退出0；主代理查看阈值窗口与分类计数图。快照重审32份已通过归档、绑定两项真实原生取证，保留10匹配响应/1失败/117缺失，且主阈值中有1数值不确定。原生捕获记录的pending视觉标记保持原字节，独立实际目视结论见[native-visual-review.md](native-visual-review.md)。停止原因与依赖见[blocker.md](blocker.md)，不得把报告生成成功当作完整实验通过。

## 主代理调用

一次生成新的阶段快照、图件、课程草案，并更新本实验的自动报告：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/report.py --publish
```

分别执行时：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/summarize.py
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/plot_results.py <snapshot-directory>
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/report.py --snapshot <snapshot-directory> --publish
```

默认快照目录是 `data/summary/<UTC timestamp>/`；所有旧快照保留，不允许覆盖。`data/summary/latest.json` 仅指向最新快照。正式 `report.md` 只有 `--publish` 才更新，其对应字节保存为快照内的 `published-report.md`。`README`、`journal`、`workflow` 均不由生成器修改。没有 `--publish` 时只写快照报告。每个快照自己的报告与materials链接均按其自身位置计算。

完整快照包含 JSON、128行responses.csv、96层statistics.csv、初态CSV、来源哈希及用于显示的曲线。已有真实数据时再加入预测误差/残差CSV、氧化层CSV、PNG/SVG及逐图来源JSON。输出只允许新版summary目录或私有reporting-fixtures。

## 实际状态与分母

`summarize.collect()` 验证冻结设计哈希并读取一次ledger快照。只有 ledger `VERIFIED` 的run才通过 `audit.load_curves()` 重新读取并审计原始归档；`RUNNING`、未提交和失败run的raw不读取。期间ledger变化会拒绝这次汇总，重新调用即可；不会重发求解。

主矩阵固定保留64事件/128槽位。未知或未提交槽位是missing，并保留ledger_state和missing_reason；已知失败与当前原档审计失败是failed，保留原因。临界区间按原阈值分类，数值不确定是独立的按阈值标记。统计复用冻结的 `statistics.py`，不改变N=4，不把0/1、数值复跑、4/6 nm变体增加为新独立事件。

同尺寸事件、控制、中性曲线通过metrics重新匹配。`deltaQ_fC`保留符号；`deltaM_V`统一转为mV。表中保存主指标、读窗口、原分类、有效分类、实际run ID、源哈希、初态和源积分审计。阶段参考/预登记数值门槛未整体完成时，记录 `validation_pending` 并将报告定位为阶段性诊断；不会凭阶段未完成伪称数值容差失败。

主表和预测评分共用 `FAILURE_STATES`：`FAILED`、`FAILED_COLLECTED`、`FAILED_OR_DISCONNECTED`、`TRANSFER_OR_CONNECTION_FAILED`、`NUMERICAL_FAILED`。这些响应在主表记failed，在预测评分记invalid_or_failed；不再把后四类误计为missing。

`reference_gate_progress()` 对固定8项物理无粒子参考和2项粒子源隔离重新调用 `metrics.compare_physical_curves()`，只读取VERIFIED原档。比较结果必须与 `data/reference-validation/<tag>.json` 的原JSON逐项一致，并绑定当前原comparison字节SHA-256和所有原档。阶段中途已完成的physical也记录重审及进度，未完成依赖保持pending；RUNNING原档不读。ledger称references/pilot VERIFIED而任一项缺失、变化或失败时抛 `GateEvidenceError`，其progress给出每项原因，阻止新快照产生。`validation_pending` 只有绑定的8+2复核通过才清除。正式发布已有快照时也核对完整gate证明与文件哈希；旧快照只有stage标签不能作为通过证明。原比较文件不会被汇总器重写。

## 数值不确定与扩展数据

通过ledger对应的路径和SHA-256读取完整 `data/numerical/preregistered.json`、`boundary.json`，并核对其中原始来源归档哈希。不读取runtime中的未完数值输出。每个response_id必须有完整半步与0.7网格两个变体，才可清除“距某阈值≤0.5 mV且尚未确认”的标记。真实连续容差失败使所有阈值数值不确定；真实跨界保留对应阈值。预登记点在boundary报告中再次出现只算重复证据。

显式ledger连续状态与prediction保持相同白名单：`RAW_AUDIT_PASSED`、`MATCHED_REFINEMENT_PASSED`、`PASSED`；未写该字段不单独构成失败。`continuous_numeric_valid=False` 或非空且不在白名单的status使连续观测无效、三个阈值数值不确定、预测评分排除；原值仍供诊断。未知状态标 `CONTINUOUS_UNRESOLVED`，明确失败标 `CONTINUOUS_FAILED`。单纯critical、近分类边界或分类跨界不会否定已通过审计的连续值。

氧化层只从完整 `data/oxide/results.json` 读取，4/5/6 nm使用同源事件并单独输出。图和CSV不并入128主槽位、不加入栅长预测评分。未完成的厚度比较不补点或连线。

预测得分读取并核对原 `freeze.json`、`freeze.sha256` 和其全部文件哈希，随后调用纯 `score_predictions()`。只有已经审计的真实测试响应才作为观测；未出现测试结果时不生成残差点。不会再拟合或调参。

## 图件与来源

所有图均为DATA PLOT，每张输出PNG与可编辑SVG。图脚注明summary哈希及其来源sidecar；sidecar保存run ID、archive SHA-256、其他冻结来源和图件自身SHA-256。这些不能充当Sentaurus Visual截图或原生导出。

原生取证另由唯一控制器调用 `gui_evidence.py`，本模块不导入或执行GUI启动器。`collect_native_evidence()` 只读 `figures/native/*/evidence.json`，核对ledger tag/run ID、已审计输入条件、results.tar与其中唯一 `final_access_des.tdr` 的实际SHA-256、远端加载前后TDR哈希、场量/单位、取证操作退出码、全部本地取证文件哈希和原生proof标记。源代码依赖也绑定；哈希变化会拒绝汇总。只有VERIFIED run读取原档，未完成取证为pending。

预声明目标固定为 `v3-physical-l018-b1` 及冻结design的numerical.preregistered响应（当前 `v3-l018-alpha-a30-s202610311-b1`）；其他实际证据可收录但标为补充取证。快照的 `native_evidence` 和materials引用真实窗口PNG、原生导出PNG、原证据JSON、run条件及源哈希，并保留 `CAPTURED_PENDING_VISUAL_REVIEW`。本模块的来源核验不会自动把色标、单位和所选run的实际看图检查标成通过；主代理须另记视觉验收。4 ns场图不当作瞬态读出曲线或Workbench Run按钮证据。

已实现图类：统一初态及误差；各尺寸0/1的SN/BL事件、控制和中性曲线；3.8–4 ns裕量与三组阈值；逐层六分类计数；Wilson最佳/最差包络；均值/岭真实测试残差；固定事件氧化层敏感性。无数据的图类在index.json列出skipped原因。全缺失时可以显示计划槽位状态条，不生成虚构指标点或区间估计点。

曲线显示可按最多约600个常规索引稀疏采样，同时保留阶段边界和完整3.8–4 ns窗口。此步骤只影响绘图，指标计算始终使用完整原始曲线。任何已完成正式事件都不能因为结果不理想而从图中择样排除。

## 课程材料

每个快照生成 `materials/index.md`、`index.json` 与 `parameter-sources.csv` 草案，引用可行性、固定设计/实际进度、联合链路、图件与总结报告。参数来源明确区分继承探索模型和4/6 nm受控假设。自然语言接口引用 `demo.md` 与 `data/demo/request-demonstration.json`，并核对其原验证记录、冻结设计和解析器哈希；只称限定模板的真实接口验证，不重复执行解析器或提交求解。学生实际演示、分工、教师审核、实验室交接、答辩与考核继续pending。原生GUI取证按真实证据动态显示，视觉审查另行pending，不再硬编码整项未核验。

## 验证证据与边界

实际合成测试命令：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B local_runtime/dram-see-v3/reporting-fixtures/test_reporting.py
```

原4项检查及修复后的定向检查合计11项通过，退出0；最新日志为 `local_runtime/dram-see-v3/reporting-fixtures/validation-reporting-repair-native-20261010.log`。覆盖128完整槽位、运行中排除、五类failed与预测分母一致、连续失败/未知status传播、8+2物理比较重审及缺失/改动/不通过拒绝、数值两变体规则、全缺失不造点、所有图类、PNG/SVG哈希、不可覆盖快照、禁止发布合成报告、原生archive/TDR/files变更拒绝及人工事项pending。GUI夹具中的TDR和PNG路径仅为明确写有NONPHYSICAL的哈希契约占位字节，不是模拟器TDR或截图，不能作为视觉成果。DATA PLOT合成图有醒目的“SYNTHETIC FIXTURE - NOT PHYSICAL RESULTS”标签，且只存在于私有fixture目录。原图形验证曾目视检查读出曲线和分层计数图，修正图例与标题拥挤；本次修复未修改plot_results.py。

另一次只读真实快照验证：`local_runtime/dram-see-v3/reporting-fixtures/actual-stage-20261010T100702618103Z`。读取10个已完成且复核通过归档，主响应0/128、missing128、计划事件64、预算372.32/86400 s、errors为空；没有读取运行中raw或写正式report.md。该次真实证据仅证明初期阶段汇总链路，不证明粒子/预测/氧化层结果完成。

未来完整真实粒子与扩展IO、实际8+2整组原档重算及真实v3 GUI截图接入尚未由本次修复实测；后续每阶段仍需主代理确认指标与原始证据，并核对原生软件图件。本次未运行正式collect/publish、SSH或求解，未读取RUNNING raw。课程正式验收及商业可靠性不属于此生成器可推导的结论。
