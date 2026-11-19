# 软件验证记录 — 2026-11-16

## 结果

最终整套命令：

```powershell
& predictor/.venv/Scripts/python.exe -m unittest discover -s predictor/tests
```

实际输出：

```text
Ran 137 tests in 18.954s
OK
```

退出码 0。环境为 Windows、Python 3.13.15、独立 `predictor/.venv`、CPU PyTorch。
`uv lock --project predictor --check` 返回成功；模块 CLI `--help` 可运行。

## 覆盖范围

| 测试文件 | 项数 | 核心证据 |
|---|---:|---|
| `test_ingest.py` | 24 | CSV/DF-ISE、单位、异网格积分、配对与哈希、封存路径不读取 |
| `test_data_splits.py` | 25 | 来源连通、42 profile 三折大小、修复去重、封存与特征边界 |
| `test_models.py` | 21 | RC 校准、零源/因果、辅助头、NaN 掩码、概率与计数损失、权重真正生效 |
| `test_aggregation.py` | 14 | 完整池、零源、分母、来源别名、多 bit/状态、面积与率单位 |
| `test_r_training.py` | 14 | 外部标签/对照污染不改变训练权重、停止侧不拟合机理、有效头与缓存 |
| `test_f_training.py` | 21 | 原生优先、训练侧尺度、代理来源、停止侧隔离、头屏蔽与 artifact |
| `test_pipeline.py` | 13 | 实际外三折/内两折、严格 F 早停、最终三折、纯代理及原生 F、默认不训练 |
| `test_calibration.py` | 4 | 随机折外温度估计、来源聚类权重、重复证据与单类处理 |
| `test_baselines.py` | 1 | 实际运行四种 R 消融及固定原生统计基线 |
| 合计 | **137** | 均为人工输入的软件验证 |

端到端测试实际执行了小型 `synthetic_fixture` 的优化步骤，包含仅有代理监督的 R→A→F 路径，也包含 R 缺少翻转监督/RC 对照而 F 仍依靠原生外观计数运行的路径。人工计数不是真实辐照统计。

封存访问使用 poison 文件和 `Path.open` 拦截验证；修改外部验证标签及对照后，当前训练侧编码器、机理参数和 R 权重保持一致。最终 F 标签保留各折 R 的来源，未被全开发集 R 的样本内预测覆盖。

12 候选及选定配置三 seed 的调用安排使用模拟 CV 返回值检查，共 12 次候选 CV 加 2 次选中配置追加 seed。**没有实际执行完整超参搜索**。

整合时修复了方向向量被默认角度覆盖、无来源 ready 代理可绕过审计、低质量权重被归一化抵消、候选 F 失败使选参降级，以及早停模型温度不当转给重拟合模型的问题；当前测试包含相应回归检查。

## 未执行及未证明

- 未启动真实 r0.4 数据训练、服务器训练进程或新仿真；本轮没有服务器写操作。
- 未读取/混入历史 v3/v4 响应作为本批训练数据。
- 未完成真实器件机理适用性、截面精度、置信区间覆盖或独立封存评价。
- 未证明当前样本数足以训练稀有事件预测，未得出结题通过结论。
- 未实现自然语言工具接线、服务器训练槽调度、商业 DDR5 混合图样计数适配或自动稳定版本替换。

服务器原运行器、owner、共享锁及正在推进的队列不属于本次修改范围。

## 2026-11-16：首批真实输运数据接入

- 新增 `data_stage:"transport_only"`、离线 `import-r04` 适配器、来源核对和质量报告；其影响仅限数据读取、准备和训练入口。
- 新增 18 项输运阶段测试、17 项 r0.4 适配器测试；最终完整测试 **172 项通过，18.716 秒**。命令：`python -m unittest discover -s tests -v`。
- 实际读回 `local_runtime/r04-data-intake-20261116T140422Z/export-r2/`：6 工况、60,000 独立 primary，正/零硅沉积 5,963/54,037；随机/增强候选 36/36。五表哈希与源码版本绑定，真实方向向量可编码。
- 监督三表为空，`R_ready=false`、`F_ready=false`；不生成 folds，不建立训练 View，未启动真实数据优化。
- 服务器只读核对和复制保留原任务身份；没有提交、collect、服务重启或队列/锁写入。两项原写保持读仍运行。源注入诊断的问题另见[本批报告](reports/r04-20261116.md)，不因接口测试通过认定科学适用。

证据：`local_runtime/r04-data-intake-20261116T140422Z/unittest-final.log`、`readback-verification.json`、`server-status-final.json`。详细的来源范围、未验证项和快照入口见本批报告。
