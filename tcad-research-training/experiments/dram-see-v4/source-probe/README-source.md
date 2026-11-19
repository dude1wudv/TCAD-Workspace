# A0/A1/A4 源接口输入

生成器只准备独立的 v4 输入，不连接 VM、不调用求解器。首轮真实范围由主代理冻结为 **bit1 的 A0、A1、A4**；bit0 仅支持离线生成，不能据此宣称已验证两个存储状态。全部工况是合成源能力探针，不进入事件概率或正式训练集。

输入复用只读的 `dram-see-v3/r50-main/build_case.py` 中 `_single_device` 与 `_geometry`。几何助手在指定 v4 临时目录调用 v1 的无事件纯生成器；不调用受 v3 路径约束的 `build()`，不改 v3 代码或输入。完整初态、50 Ω 预充电、4 ns 读出及二维有效厚度 1 µm 保持继承设置；这不是新的 90 nm 器件。

源合同见 [source_contract.json](source_contract.json)。A0 保留非空事件标识且 tracks 为空；A1 是起点 (0.425,0.3) µm、方向 (0,1)、长度 0.6 µm 的 1 fC 源；A4 是同位置同时的两个 0.5 fC 源。半径参数 0.03 µm、Time=1 ns、s_hi=2 ps 均显式固定。A1 使用 Ion1，A4 使用 Ion1、Ion2，两者提供同一套显式参数。

本地 W-2024.09 指南 p813–816 支持时间/空间高斯核、命名源和参数；p73/88 支持 `File { Parameter="heavyion.par" }`。命名头来自 p816，参数块体使用主代理实际读到的 Silicon.par 花括号。手册表143的 c2=1、c3=0、c4=1 与安装默认 c2=0、c3=1、c4=0 不同，本轮明确选择前者，使 `(c2+c3*l)^c4` 恒为1；不能称两份默认记录一致。命名组合语法仍须真实 parser 验证；失败保留独立输入/日志，不覆盖输入或放宽物理门槛。

从仓库根运行纯离线命令：

```powershell
python -B experiments/dram-see-v4/source-probe/build_probe.py check-source --case A4
python -B experiments/dram-see-v4/source-probe/build_probe.py build local_runtime/dram-see-v4/source-probe/inputs/v4-source-probe-a0-b1-r1 --case A0 --bit 1
python -B experiments/dram-see-v4/source-probe/build_probe.py build local_runtime/dram-see-v4/source-probe/inputs/v4-source-probe-a1-b1-r1 --case A1 --bit 1
python -B experiments/dram-see-v4/source-probe/build_probe.py build local_runtime/dram-see-v4/source-probe/inputs/v4-source-probe-a4-b1-r1 --case A4 --bit 1
python -B experiments/dram-see-v4/source-probe/build_probe.py check local_runtime/dram-see-v4/source-probe/inputs/v4-source-probe-a1-b1-r1
```

输出目录必须位于 `local_runtime/dram-see-v4/source-probe/`，目录名绑定工况和存储位；已有输出拒绝覆盖。可用 `--spec` 提供完整 source-spec JSON，缺字段、额外字段、冲突单位/电荷和不匹配工况均拒绝。不把该入口当作任意粒子源生成器。

每个工程含 `project.json`、几何/器件 deck、参数文件、独立 `source-spec.json`、合同原字节副本 `source-contract.json`、`parameters.json`、解析检查及输入哈希清单。原始软件与参考的哈希进入证据链。`check` 是离线输入检查，不证明源真正进入 TCAD。

主代理完成运行前检查后，使用既有入口：

```powershell
python scripts/tcad.py run local_runtime/dram-see-v4/source-probe/inputs/v4-source-probe-a0-b1-r1
```

运行只能由唯一调度者执行，保留串行单线程、原始归档和退出码。生成器从不调用上述命令。求解后由独立的 `audit_probe.py` 验收；存在输入不能证明运行完成。A0 若无生成率数据集，只能说明结构零源，不能冒充数值零源观测。

离线算法按有限纵向区间、归一化横向高斯和 t≥0 归一化时间核解析积分，并与数值积分核对；1 fC 对应约 6241.509 个电子空穴对。A4 每份半电荷仅计一次。解析门槛为 max(1e-6 fC,0.1%×Qin)，真实 TCAD 门槛另见合同，不能混用。后续分步、多段映射必须审核核端点和重叠；不能把完整轨迹电荷/LET重复写到每一段。

开发验证记录在 `local_runtime/dram-see-v4/source-probe/build-dev/`，包含纯离线测试、生成的两存储态夹具及旧输入哈希检查。此目录的 synthetic 输出都不是实测。
