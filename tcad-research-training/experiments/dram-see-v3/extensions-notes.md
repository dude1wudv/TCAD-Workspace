# 数值验证与氧化层扩展执行接口

状态：2026-10-10 完成实现与隔离 fixture 验证。本文不是数值精度通过、氧化层效应或新增求解完成的证据。真实阶段由主代理统一调度；实现代理未调用 SSH、TCAD、输运或 Git。

## 执行入口与阶段条件

在项目根目录由唯一调度者调用：

```powershell
python -B experiments/dram-see-v3/numerical.py preregistered --label r1
python -B experiments/dram-see-v3/numerical.py boundary --label r1
python -B experiments/dram-see-v3/oxide.py --label r1
```

Python 接口为 `numerical.execute(mode='preregistered', label='r1', limit=None)` 和 `oxide.execute(label='r1', limit=None)`。入口内部持有原 `run.controller_lock()`；调用者不要重复取得同一锁。`--limit N` 仅限制本次新提交数量，不改变冻结清单、样本数或事件选择；同标签续行使用原冻结文件。所有求解通过现有 `run.record()`，因此共用唯一控制器、提交前核查、`scripts/tcad.py`、单线程、原项目锁与 86,400 s 预算。无新 runner，也没有 transport 调用。

预登记数值验证要求 `pilot` 已 `VERIFIED`。主代理必须把连续精度通过作为扩大训练及预测冻结的前置条件。边界验证要求预测冻结有效、`test` 和预登记数值阶段均 `VERIFIED`。氧化层要求预测冻结、`test` 阶段及全部 128 个主矩阵响应均 `VERIFIED`；不会用扩展替代主矩阵失败或缺失项。

## 不可变计划与安全续行

每阶段首先使用 `common.write_json(..., exclusive=True)` 写：

```text
local_runtime/dram-see-v3/extensions/<stage>-<label>/plan.json
local_runtime/dram-see-v3/extensions/<stage>-<label>/plan-sha256.json
```

其中 stage 为 `numerical-preregistered`、`numerical-boundary`、`oxide`。计划绑定 `run.source_hashes()`、`numerical.py` 与 `oxide.py` 自身 SHA-256、设计哈希、全部 case 配方、待比较主响应快照、事件三份原始文件哈希；氧化层还绑定预测冻结。任何实现、设计、事件或计划绑定变化都停止续行，不重写旧冻结。

事件输入需要已完成匹配对照的保存点。因此阶段计划先冻结全部配方（兼容 execution-freeze 的 `inputs` 初始为空）；依赖已满足时才构建一次该 case 输入，并另写：

```text
local_runtime/dram-see-v3/execution-freezes/<stage>-<label>-<tag>.json
```

该文件含标准 `design_sha256`、`source_sha256`、`inputs` 结构和原计划路径/哈希，直接供 `run.record()` 验证。已有且已冻结、从未提交的输入可安全续行。存在输入却缺 execution-freeze 时拒绝自动采用；已有 `RUNNING`、`FAILED` 或未知状态不重发。失败原因、预算停止和原始 runner 证据留在原 ledger；可变进度仅写同阶段目录 `status.json`，不建立第二份运行事实源。中断恢复先由主代理核实远端、收集状态与 ledger。

阶段开始还通过原 `budget()` 检测未结/孤立运行，避免状态不明时准备新输入。已验证且配方/冻结/归档均一致的重复数值 case 可复用，不产生新增求解，也不增加独立事件。

## 数值点、比较与输出

预登记点从冻结设计读取：`L=0.18 µm / alpha / 30° / replicate=1 / bit=1`。两个独立变体为：

| 变体 | step | mesh | 新运行 |
|---|---:|---:|---|
| 半步长 | 0.5 | 1.0 | 匹配 control、neutral、同事件响应 |
| 网格细化 | 1.0 | 0.7 | 匹配 control、neutral、同事件响应 |

共 6 个预登记数值运行。每个粒子响应从自身变体、原存储位的完整无粒子 control 续算；不加载默认尺度保存点。提交粒子前检查匹配 control/neutral 的实际 mesh hash 和完整 matching key。最终计算通过原 metrics 再次核对 signal/control/neutral 三者同网格；不同尺度之间允许 mesh hash 不同。

相对默认步长/网格的比较项目：信号、control、neutral 各自的 `BL(4 ns)`，事件与对照的 `D4`/`M4`，以及 `deltaM`，每项绝对变化 ≤0.5 mV；`deltaQ` 变化 ≤0.01 fC。分别比较三个原阈值的 signal/control 分类。SN 保持末和读出末电压作为诊断随观察量保留，不新增未经登记的判定门槛。

**连续误差失败与分类跨界分开。** 连续门槛任一失败，最终状态 `NUMERICAL_FAILED`，保存完整比较并抛出异常，阻止扩大。若连续门槛通过但分类跨界，状态仍为 `VERIFIED`、`continuous_passed=true`、`classification_stable=false`；受影响阈值列为 `numerically_uncertain`，原始分类保留。仅接近分类边界且没有连续精度失败，不据此阻断连续响应回归。

边界附加点在完整主矩阵结束后，对 128 个主响应按

```text
distance = min(|M-epsilon|, |M+epsilon|), epsilon in {2.5,5,10} mV
sort key = (distance, condition_id, replicate, stored_bit)
```

选前两个不同 response ID，并在计划中冻结全排序、全部状态与来源。若含失败/缺失，无法完成全排序，则保存 `selection-blocked.json` 并停止，不从剩余样本替补。每个附加点同样检查两种变体及各自对照/中性参考；若命中预登记点，按相同 tag 复用原验证。其他尚未获得匹配细化确认的近边界结果仍应由统计阶段按冻结设计标记数值不确定，不能从“没有运行细化”推断稳定。

完整阶段比较完成后只写一次：

```text
experiments/dram-see-v3/data/numerical/preregistered.json
experiments/dram-see-v3/data/numerical/boundary.json
```

schema 为 `dram-see-v3-numerical-validation`。关键字段：

- 顶层 `state`、`continuous_passed`、`classification_stable`、`execution_plan_sha256`、`comparisons`；boundary 另含完整 `selection`。
- 每个 comparison 含 `response_id=v3-<event.label>-b<bit>`、完整 `event`、`stored_bit`、`variation={step,mesh}`、`differences_V`、`deltaQ_difference_fC`、`continuous_passed`、`classification_stable`。
- `classification_comparison[str(threshold_V)]` 同时保存 signal/control 的 baseline/refined 分类；`numerically_uncertain_thresholds_V` 单位为 V。
- `baseline_sources` / `refined_sources` 的 signal/control/neutral 分别含真实 `run_id`、`archive_sha256`、`mesh_sha256` 与匹配契约；`baseline_metrics` / `refined_metrics` 保留完整指标。

ledger 的 `stages.numerical_preregistered` / `stages.numerical_boundary` 保存结果状态及 `evidence`、`evidence_sha256`、连续与分类两个标志。预测与报告必须验证证据哈希，不能仅凭阶段名称或运行收集完成判断精度通过。

## 氧化层矩阵与解释边界

从冻结设计选 `L=0.25 µm`、alpha/proton、0°、replicate 1 的两个主事件。每种新厚度 4 nm、6 nm 先完整生成并求解 bit 0 control、bit 1 control、neutral；随后该厚度下两事件分别配对 0/1 响应，粒子输入使用该厚度对应 bit control 的保存点。每厚度 7 个运行，总 14 个，其中粒子响应 8 个；原 5 nm 的 4 个响应和各自 control/neutral直接复用主矩阵。

提交粒子前核对该厚度两个 control/neutral 的实际 mesh 一致；最终拒绝新厚度直接复用 5 nm 的实际 mesh bytes。builder 负责已有冻结的氧化层边界、栅接触与网格修改；本模块不修改输运事件、不生成随机种子。

完成后只写一次 `experiments/dram-see-v3/data/oxide/results.json`，schema `dram-see-v3-oxide-sensitivity`，并更新 ledger `stages.oxide` 的来源哈希。结果包括 `baseline_5nm` 的 4 份原响应、`responses` 的 8 份扩展响应、各自原始指标与相对 5 nm 差异、分类和来源。每行 `event`、`stored_bit`、`main_response_id` 保持主事件绑定；`observation.metrics.sources` 可追溯三个真实 run。

`new_independent_events=0`，不把厚度配对或数值复跑计作独立事件；氧化层结果不进入栅长留出/外推评分。参数来源是原 5 nm 未校准模型的 ±20% 受控假设，解释仅为固定硅入口事件下的 TCAD 敏感性，不代表完整工艺栈输运或商业器件可靠性。

## 本地验证与未做项

验证命令：

```powershell
python -B local_runtime/dram-see-v3/extensions-fixtures/test_extensions.py
```

9 项测试通过，退出码 0：连续误差/分类跨界分离；两侧共同电压误差无法由 D 相消；deltaQ 门槛及非有限拒绝；边界排序/并列/未决分母；数值 6 case 与氧化层 14 case 配方；源码哈希冻结；已冻结待提交输入续行；孤立输入拒绝；FAILED 不重发；完整预登记/氧化层 mock 报告和重复执行零新提交。

全部 mock 用替代 controller 与独立临时目录，覆盖真实 `record`、`prepare` 和审计入口，不触碰生产 ledger、冻结输入、VM 或归档。测试与完整日志在 `local_runtime/dram-see-v3/extensions-fixtures/{test_extensions.py,test-output.txt}`。未验证真实新增求解耗时、网格兼容或数值/氧化层效应；实际执行后才能据原始归档确认。
