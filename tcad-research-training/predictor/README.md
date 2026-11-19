# DRAM 单粒子效应 R/A/F 数据与训练流程

本目录实现 [已确认训练计划](../plans/dram-se-ddr5-lpddr5/PREDICTOR-TRAINING.md)：
有来源的仿真数据 → 响应模型 R → 完整事件池聚合 A → 两状态截面模型 F。
当前实现面向 r0.4 质子批次；DDR5、LPDDR5 分域，不能把代表结构的代理标签当作商业 DDR5 实验真值。

**已接入首批真实 r0.4 输运数据：6 个开发工况、60,000 个 primary；当前为 `transport_only` 快照，尚无 R/F 监督标签，未启动正式训练。** 结果、来源和缺项见 [本批数据质量报告](reports/r04-20261116.md)。本包没有 SSH、求解器、服务管理或作业提交代码。服务器原有仿真由原运行器继续负责。

## 现在可用的入口

在工程根目录执行：

```powershell
uv sync --project predictor --frozen
& predictor/.venv/Scripts/python.exe -m dram_predictor --help
```

真实数据到位后，先显式指定原始文件清单，再导出新的只读训练快照：

```powershell
uv run --project predictor dram-predictor ingest path/to/intake.json --out predictor/snapshots/batch-001
uv run --project predictor dram-predictor inspect predictor/snapshots/batch-001/manifest.json
uv run --project predictor dram-predictor prepare predictor/snapshots/batch-001/manifest.json --out predictor/prepared/batch-001
```

`inspect` 与 `prepare` 不执行优化器。下面的命令也**不会训练**，只返回可用数据情况：

```powershell
uv run --project predictor dram-predictor train predictor/snapshots/batch-001/manifest.json --stage cv
```

对于服务器已经归档、只读复制并带有 `copy-receipt.json` 的首批 r0.4 输运包，可直接使用新适配入口：

```powershell
& predictor/.venv/Scripts/python.exe -m dram_predictor import-r04 path/to/copied-bundle --out path/to/new-export
```

输出包含 `intake/`、`snapshot/`、`prepared/readiness.json`、`quality.json` 和 `QUALITY.md`。命令只消费清单中已完成的开发结果，不连接服务器。原始 run、输入与输出哈希、全部 primary、零沉积及候选选样身份保留；未建立的电容/源映射/响应保持未知。

`transport_only` 是数据成熟度标记：快照可以检查和维护，但不能进入模型拟合或人为拆成训练 folds，不影响服务器仿真推进。补齐后应生成新的完整快照，不能仅修改阶段字段，也不能把未选样的输运事件补标成 TCAD 随机响应。

以后另行启动训练时，才显式增加 `--execute`、已冻结的 `--prepared` 和新的 `--out`。这轮未执行这些命令：

```powershell
# 先单配置开发 CV 计时，单进程、单线程。
uv run --project predictor dram-predictor train predictor/snapshots/batch-001/manifest.json --prepared predictor/prepared/batch-001 --out predictor/runs/pilot-cv --stage cv --execute

# 12 组联合配置、seed 1729；选中配置再评 2718、31415。
uv run --project predictor dram-predictor train predictor/snapshots/batch-001/manifest.json --prepared predictor/prepared/batch-001 --out predictor/runs/search-001 --stage search --execute

# 四种 R 消融及固定统计基线。
uv run --project predictor dram-predictor train predictor/snapshots/batch-001/manifest.json --prepared predictor/prepared/batch-001 --config predictor/runs/search-001/selected.json --out predictor/runs/ablations-001 --stage ablations --execute

# 最终开发拟合仍先做 3 折 R，生成 F 的折外标签。
uv run --project predictor dram-predictor train predictor/snapshots/batch-001/manifest.json --prepared predictor/prepared/batch-001 --config predictor/runs/search-001/selected.json --out predictor/runs/model-001 --stage final --execute
```

训练代码本身不申请服务器计算槽。未来接入服务器时须由现有运行器安排到同一计算预算中，先给一个训练任务分配一核，不能在九个求解任务之外暗增训练池。CentOS 求解虚拟机的环境不因本包安装而改变。

## 数据与科学定义

输入协议详见 [SCHEMA.md](SCHEMA.md)。读取严格按清单进行，不扫描原始目录，不自动接纳历史 v3/v4 结果。

- 每条波形核对 SHA256；有源与无源对照必须匹配 `profile_id/state/protocol_id`。
- 节点扰动为有源减无源电压；端口电荷为指定窗口内差电流的有符号积分。两条波形可使用不同、不规则网格。
- 电容净电荷与端口收集电荷分别处理。当前低阶层采用已声明适用的常电容、局部 RC 与矩形源近似，不将它写成 L08 提供的完整 DRAM 模型。
- 翻转和裕量只接受原有读出定义给出的标签，不从任意电压阈值产生 SEU 真值。
- 失败、未决、缺失按头掩码；修复用 `supersedes` 替换同一物理样本，不按重试次数重复计权。
- 原生统计必须声明适用的逐状态 Poisson 计数口径和真实暴露。只提供混合图样总计数时，不能伪造两个状态标签；其适配仍需独立实现。
- `primary_count` 是全 Geant4 池独立发射 primary 的分母，不是已有 TCAD 响应数。零沉积保留；池外增强样本仅供 R 学响应。

`mechanism_validated`、`area_normalization_validated` 和标签定义是来自科学审阅的声明，软件不会因为数值有限或测试通过就自动把它们置为真。

## 分组与防泄漏

`splits.py` 按 profile、实际复用的输运 primary、无源对照及原生统计来源连通分组。波形时间点、配对状态、bit、重试不独立切分。分组算法不使用标签结果。

```text
开发外折 T / V
  T 内两折 R：各自只用训练半侧的预处理、对照与响应
    → 预测另一半的完整 Geant4 池
    → A 为 T 产生折外代理
  F(T 的折外代理 + 原生统计)
  R(T) 预测 V 的真实响应；F 仅用 V 的仿真前输入
```

早停同样按来源组划分。R 用训练侧内部停止组选择轮数，再按选定轮数重拟合该训练侧。F 的停止集不能从既有代理表随手切出：先分 C/S，C 内另做 R 交叉拟合，S 由只见过 C 的 R 预测；选轮数后重拟合 T。组或监督不足时明确使用固定轮数，并保留原因。

`prepare` 保存 `splits.json`、快照指纹和来源足迹；快照变化后须形成新版本并重新准备。训练入口不读取封存标签。相同器件的新组合/高能测试可以共享 profile，但不能共享训练 primary；器件外推 profile 及对照独立保留。

模型包包含所有拟合来源。`ready` 代理必须有完整 R 训练足迹；F 拒绝目标 profile、primary 或对照来源进入该代理的拟合集，即使同一目标最终会被原生计数覆盖。

## 模型、损失与校准

| 部分 | 实现 |
|---|---|
| R | 默认 64–64 SiLU；共享 `log(tau)` 与有符号收集增益校准；4 个因果残差驱动系数 |
| 物理结构 | `r(x)-r(x_off)` 保证完整源关闭时增量为零；正时间常数、常电容支路关系；端口头独立 |
| R 监督 | 有效电压、电荷、裕量 Huber；真实两类 upset 的 BCE；训练侧尺度与残差正则 |
| A | `A_src × sum(p_jsb) / (N_primary × N_bits)`，分别计算状态 0/1；面积或事件池不完整则不生成截面 |
| F | 默认 32–32 SiLU，两个带训练侧尺度的 softplus 截面头；只读仿真前字段 |
| F 监督 | 原生 Poisson 含暴露 offset；代理 asinh-Huber；同工况/状态原生优先，避免双计 |
| 质量权重 | 代理权重上限 1；未校准代理为 0.25，实际降低损失，不在归一化中抵消 |
| 比较 | 机理单独、纯 MLP、无附加正则的混合模型、选定正则混合模型；原生计数常量 MLE 基线 |

没有真实两类翻转监督的 R 不发布概率，不能用随机初始化头生成 A/F 标签；仍能训练已有连续响应，F 也仍可利用独立原生计数。

早停模型的温度只保留为诊断，不转给不同的重拟合模型。最终拟合复用规定的三折 R，收集开发侧随机事件折外 logits 估计温度；标记为 `estimated_oof_for_refit`，不是“已完成独立概率校准验证”。最终 R 的温度不会反过来修改已冻结的 F 折外标签。

代理始终标记 `model_derived_proxy`。运输 Monte Carlo 标准误仅描述固定模型下事件池的抽样变化；三个 seed 的差异也不直接叫 95% 预测区间。

## 输出与自然语言工具衔接

最终目录包含：

```text
R/                           权重、编码器、机理参数、全部来源
F/                           权重、训练尺度、有效状态头、代理来源
F_development_oof_proxies.json
R_three_fold_provenance.json   含随机事件折外概率校准证据
model_card.json
cache/                       训练范围 + R 配置 + 数据版本 + 代码哈希
```

R/F 权重和元数据均核对哈希；加载使用 `weights_only=True`。现有模型目录及预测结果不覆盖。未监督的头返回 `null`，未知粒子/结构类别或另一模型域明确拒绝，数值外推返回越界字段。

```powershell
uv run --project predictor dram-predictor predict-f predictor/runs/model-001/F inputs.json --out prediction.json
uv run --project predictor dram-predictor predict-r predictor/runs/model-001/R response-inputs.json --out response-prediction.json
```

`predict-f` 接收 `{"conditions":[...]}`。可另传明确的 `state_weights` 和与能量/方向分箱、参考面对应的 `integrated_flux_by_bin`；没有通量只给截面。`predict-r` 接收 `{"samples":[{"condition":...,"primary":...,"state":0,"bit":...}]}`。

这些是以后大语言模型调用的结构化工具入口。本轮未训练语言模型，也未接入自然语言工具路由、服务器自动训练或正式盲测评价。

## 验证与当前限制

```powershell
& predictor/.venv/Scripts/python.exe -m unittest discover -s predictor/tests -v
```

测试数据在临时目录内生成，全部声明 `synthetic_fixture`，网络最多运行极少轮。测试覆盖来源连通、波形提取、泄漏污染、分母、头掩码、真实两级调用顺序、缓存、保存加载与默认不训练。

实际验证结果见 [VALIDATION.md](VALIDATION.md)。真实 r0.4 快照尚未在本地接入，所以目前没有真实参数校准、预测精度、数据充分性或结题通过结论。商业 DDR5 外部试验表适配、独立封存评价、树模型对比及因素分析报告留在后续真实数据阶段。
