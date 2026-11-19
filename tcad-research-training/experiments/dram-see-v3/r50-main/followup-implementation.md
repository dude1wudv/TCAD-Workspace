# R50-main 后半首段：预测与测试

本入口仅实现 `训练原档/参考/数值重审 → 32 个固定测试 Geant4 输入 → 实际四模型与64条预测冻结 → 64 个测试响应`。终态明确为 `TEST_FINISHED_PENDING_EXTENSIONS`。氧化层、边界、报告、原生图与课程验收不由此入口执行，也不因测试完成而标为完成。完整分母始终为64独立事件、128个位响应；probe、数值细化和同事件两位不增加独立样本。

首段的 `controller.py`、`source-manifest.json`、派生源码、plan/design全部保持原字节。本段只通过只读接口重审首段证据。`prediction.py` 逐函数复制原v3纯算法，唯一文本变化是输出schema，无旧IO/ledger路径；全部均值、四目标分位模型、8组LOCO、训练折标准化、ridge候选、平均折RMSE及tie规则不变。具体原/新哈希与差异见 `followup-derivation.json`、`prediction.py.diff`。

`transport_adapter.py` 是原 transport 的显式拷贝，只把依赖导入改为原字节编译，并将HERE定位为原v3目录。实际Geant4命令、既有二进制、seed规则、许可证/VM、不可覆盖操作目录与源转换均不变。测试输入仍保存原v3 `data/geant4/<label>/`，不另生成重复事件。复用已有事件时要求原操作明确 `VALIDATED`、runner/收集退出0、原 `events.tar` 中三个文件和导出CSV字节一致；失败/断连/部分输出不能因metadata存在而自动晋升成功或重发。

## 验收和运行接口

只有首段真实完成且原controller退出后，root可填写：

`local_runtime/dram-see-v3/physical-revisions/r50-main-followup-r1-acceptance.json`

字段契约（这里是说明，不能当已发生的验收）：

```json
{
  "schema": "dram-see-v3-r50-main-followup-acceptance",
  "approved": true,
  "design_sha256": "实际冻结design文件SHA256",
  "first_plan_sha256": "首段实际执行plan.json文件SHA256",
  "source_manifest_sha256": "followup-source-manifest.json文件原始字节SHA256",
  "accepted_utc": "实际UTC验收时间",
  "evidence": "独立验收证据路径或说明"
}
```

主代理通过源码/原档验收后调用：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/finish.py freeze --label r1
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/finish.py execute --label r1
```

`freeze` 是执行计划冻结，不是模型拟合，也不生成G4或调用求解器。它重审首段全部92原档、10项物理/源隔离比较和2项数值比较，确认真实64训练响应，冻结来源与受保护global ledger快照。`execute` 持同一controller.lock，经主机controller退出检查、原preflight、预算与UTC截止检查后，按固定顺序生成32份测试输入，再拟合四模型并冻结64条逐bit预测，最后串行求解64测试响应。

运行目录为 `local_runtime/dram-see-v3/physical-revisions/r50-main-followup-r1/`，包括 `plan.json`/`plan-sha256.json`、`source-snapshot/`、`ledger-before.json`、`case-freezes/`、`prediction-binding.json`、`status.json`、最终 `test-result.json`。status保留controller PID、父PID、开始UTC、当前case、错误及完整128槽位。只允许新增本段64个测试run及其失败历史，原全部行、原stages和首段stage-index不修改；成本仍只读原唯一global ledger。

`followup-source-manifest.json` 固定绑定全部本段源码、原算法/transport来源、Geant4源码，以及首段manifest与其每个实际依赖。它不glob目录，因此不绑定将来新增的reporting/GUI/扩展源码，也不要求修改首段manifest。所有manifest哈希都指文件原字节；计划自哈希放在邻近 `plan-sha256.json`。

## 防泄漏与实际预测

预测只在全部训练连续有效、物理参考和预登记连续数值门槛通过后生成。单纯critical保留连续值；显式连续失败/未知拒绝。训练行记录分类与近边界/跨界不确定，不靠分类结果挑样。

防泄漏检查枚举实际 `inputs.tar` 的参数与manifest哈希，按R50-main schema/revision/source/尺寸判定，不靠旧tag字符串，不打开尚未允许的测试响应。旧100Ω/probe不能充当新训练/对照/中性；全部匹配及实际网格仍由新main审计与metrics核对。

真实预测目录为 `experiments/dram-see-v3/r50-main/data/predictions/`：`models.json`保存系数、scaler、每折拟合/预测、CV评分及配置；`training-data.json`与`test-inputs.json`保存64个训练位响应和64个测试位输入；`predictions.json`保存实际64条逐位预测；另有ledger快照、provenance、`freeze.json`/`freeze.sha256`。freeze绑定每个训练原档、所有测试G4及匹配参考、物理/数值证据和源码。不能覆盖已有目录；部分失败必须保全并人工核查，不自动重建。

`frozen_utc`使用带 `+00:00` 的真实UTC，在任何测试提交之前落盘。每项输入冻结再绑定该prediction freeze哈希。实际ledger的精确 `started_utc` 必须严格晚于freeze；真实runner ID秒级UTC用区间检查辅助，不声称它提供微秒精度。接续时所有已提交测试须为固定顺序的连续前缀、真实VERIFIED且原输入归档匹配；FAILED/未知/空档立即阻断，不重发。

测试结束产出 `data/prediction-scores.json` 和 runtime `test-result.json`，只评分冻结模型，不重拟合。普通测试逐项预留600s，原全局86400s包含历史与失败费用；检查新提交早于 `2026-10-11T04:37:00Z`。超预算/过期保留未提交槽位，不终止正常在途求解。实际成本超过已冻结预留时要求安全边界的版本化审核，不自动降低估计。

## 开发验证边界

私有 `local_runtime/dram-see-v3/r50-main-followup-dev/self_check.py` 完全隔离开发输出；最新 `self-check-03.log` 为10项通过、退出0。覆盖纯算法AST/8fold和四拟合、缺失/失败训练与输入泄漏拒绝、真实input metadata判别、时间先后/UTC、失败/非前缀接续拒绝、预算/旧账保护、私有合成模型文件冻结与篡改拒绝，以及64项模拟串行控制流/首项失败停止。另只读核查32份已完成训练G4的原操作及收集tar，未重新生成事件。

合成模型位于带NONPHYSICAL标识的私有fixture，不能作为科研预测。没有真实freeze/execute、SSH、solver、GUI、生产ledger/data写入、安装或Git操作。真实train门槛、真实模型冻结和真实测试均待主代理调度及独立验收。NumPy沿用既有环境，其版本与Python版本随模型记录，没有安装新依赖。


## 独立验收修订：账本快照原字节

独立worker在合法CRLF账本fixture中复现provenance哈希与重新序列化的ledger-snapshot文件不一致；原交付源码与manifest保存在local_runtime/dram-see-v3/r50-main-followup-dev/before-ledger-byte-fix/，失败日志保留。root仅将ledger-snapshot改为原ledger_bytes的独占二进制写出，并增加读取冻结预测时的哈希一致性检查；物理设计、统计模型和调度顺序不变。该代码尚未实际激活，真实预测不存在；修订后须独立复验，不能沿用先前版本通过状态。
