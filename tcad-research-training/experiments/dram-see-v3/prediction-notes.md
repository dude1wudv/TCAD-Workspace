# v3 预测冻结与统计实现

本说明对应 `prediction.py` 和 `statistics.py`。仅完成合成契约与数值检查，尚未调用真实模型冻结或读取留出/外推粒子响应。合成数值不属于物理实验结果。

## 纯函数接口

`prediction.fit_models(training_rows, design)` 需要完整的 64 个训练位响应，对应冻结设计的 32 个事件。每行字段为：

```text
event_label, stored_bit, gate_length_um, particle, angle_deg, seed,
condition_id, replicate, split, Qdep_fC,
continuous_valid=True, continuous_numerical_status,
targets={deltaQ_fC: value, deltaM_mV: value}
```

身份、事件划分和配对电荷必须精确匹配；重复、缺失、非主厚度/网格/步长、非有限值、已知连续数值失败均拒绝。已知 `critical` 分类仍有连续目标，可训练。分类边界未复验不独自否定原始审计通过的连续观测；训练记录同时保留原分类、按阈值的数值不确定和相应证据。

特征固定为实际 Geant4 沉积 `Qdep_fC`、`Qdep_fC/L_um`、`Qdep_fC*sin(theta)`。四个独立的位/目标组合分别比较训练均值与岭回归。八组 LOCO 每次保留整个尺寸×粒子×方向工况，每位各四次重复一起留出。每折仅使用其余 28 个该位训练值计算总体均值/标准差，零标准差替换为 1。最终模型重新使用全部 32 个该位训练值。

岭目标是 SSE+α‖β‖²，截距不惩罚；候选 `0/0.01/0.1/1/10`。α=0 用 `numpy.linalg.lstsq(rcond=None)`，其他用正规方程求解。选择八个折 RMSE 的算术均值，距最小值不超过 `1e-12` 目标单位时取最小 α。输出保留每折训练/验证事件、标准化参数、系数和各候选预测/RMSE，以及最终两模型参数。

`prediction.predict_inputs(models, test_rows, design)` 需要完整的 64 个测试输入/位组合。输入只有冻结身份、Geant4 沉积和已知无粒子信息，拒绝出现 `targets`、实际响应 run ID 或目标指标字段。输出逐事件、逐位、逐目标的均值/岭预测。

`prediction.score_predictions(frozen_predictions, observed_rows, design)` 是未来测试完成后的纯评估接口，永不拟合。按留出/外推、位、目标、模型报告 MAE/RMSE/最大误差及逐事件分层残差；每组计划 N=16，缺失和无效响应单列，误差分数明确使用有效观测数。工艺变体、数值复跑不能混入评分。

## 真实冻结入口与防泄漏

主调度者在必要阶段完成后调用：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/prediction.py freeze
```

`freeze()` 自己获取现有 `controller.lock`，应在 `run.py` 的锁外调用。它不运行求解器或 Geant4。

必要条件与实际检查：

1. frozen design 文件与本地 `stats-design.sha256` 一致，且算法配置受实现检查。
2. references/pilot/train 阶段为 `VERIFIED`；`numerical_preregistered.continuous_passed=True`，证据路径/哈希正确，两项半步/细网格比较均连续通过。分类跨界保持单列。
3. 对八项物理参考及两项粒子源隔离重新从原始归档加载、验证并比较，不单凭 ledger 标签接受。
4. 64 个训练响应、匹配对照和中性参考均重新做原档审计及 metrics 计算。目标键实际取 `deltaQ_fC` 和 `1000*deltaM_V`；源事件 JSON 哈希必须与响应输入完全相同。
5. 所有测试事件来自正式 v3 `data/geant4`，原始元数据/CSV 全部验证；测试侧仅打开无粒子对照和中性参考，没有打开测试粒子输出。
6. 冻结前后检查 ledger 和所有 v3 提交 manifest 的身份/输入元数据。任意状态的测试提交都会拒绝，无法检查的 v3 输入也阻塞。生成期间 ledger 必须不变。

输出目录为 `data/predictions/`，不存在才允许创建；任何已有目录均拒绝覆盖，部分写入也保留为需调查的证据。文件包括 `models.json`、`training-data.json`、`test-inputs.json`、`predictions.json`、`ledger-snapshot.json`、`provenance.json`、最后写出的 `freeze.json` 及 `freeze.sha256`。运行器可直接按 `freeze.json.files_sha256` 和 design_sha256 检查。

哈希绑定原始训练/对照/参考/数值证据归档、全部 Geant4 事件文件、源码、设计和预测产物。活动 ledger 使用冻结快照，后续新增测试记录不会使已保存快照失效。Python/NumPy 版本记录在模型及 provenance 中。不含未来测试响应，不复用旧 pilot 做训练。

## 统计接口与分母

`statistics.summarize_classes(classes, planned_n=4)` 用冻结计划 N=4；省略槽位计为 missing，超过四项拒绝。`correct`、`criterion_error`、`critical`、`numerically_uncertain`、`failed`、`missing` 互斥列出；`valid=correct+criterion_error+critical` 表示可按数值阈值直接分类的响应数，数值未决另列。

点范围为 `[k_error/N,(k_error+全部未决)/N]`。Wilson 双侧 95% 使用 `z=1.959963984540054`，区间包络取全部未决按最佳赋值的下端和最差赋值的上端。只有四个计划响应全部可判且零误读，才返回 `1-0.05**(1/4)=0.5271291955` 的单侧上界。

`statistics.summarize_matrix(design, outcomes)` 遍历 16 个工况×两位×三个阈值；缺失保留。每条 outcome 包含 event_label/stored_bit/status，`status='measured'` 时给 `M_mV`，以及可选 `numerically_uncertain_thresholds_mV`。重复、未知事件、厚度/网格/步长变体拒绝。0/1 只在各位自己的同事件分组里报告，不合并成新增独立样本；区间为描述性，非多重检验覆盖保证。

## 验证与未做项

实际命令：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B local_runtime/dram-see-v3/prediction-fixtures/test_prediction_statistics.py
```

10 项合成检查通过，退出 0，最终日志 `local_runtime/dram-see-v3/prediction-fixtures/validation-final-20261010.log`。包括已知线性目标、8 折训练专用标准化、合法零沉积/零方差、并列选 α=0、训练完整性与泄漏/覆盖拒绝、冻结哈希、缺失评分分母、Wilson 与零事件上界、配对重复拒绝。合成冻结产物全部在 prediction-fixtures；正式 `data/predictions` 尚未创建。

尚未验证完整真实 IO 冻结流程、真实训练拟合、测试预测精度及后续评分；这些需要真实阶段通过后由主代理执行。实现不能证明真实预测一定优于训练均值。
