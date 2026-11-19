# 共享三维材料几何的 Geant4 先行检查

本目录是新的独立修订。`transport_matched.cc` 和 `audit_matched.py` 以已验证的 mechanism-witness 为起点，保留稳定出生关联及原始事件组织，改为读取共享器件几何生成的常量。它们不修改旧实现，不产生 TCAD 输入，不将厚靶记录搬进器件。

## 固定内容

- 几何唯一源：`../source-interface-3d-r1/geometry-contract.json`；`matched-contract.json` 保存完整快照及文件哈希。
- 新接口：二进制只接受冻结请求 label，不接受任意能量、种子或事件数。H/E 各 init 0、normal 2、miss 2，6 次调用共 8 个初级事件，无自动重试预算。
- 几何编译为 `geometry.hh`，运行元数据同时给出完整几何、契约哈希；`geometry-built.csv` 记录实际构建尺寸、材料、密度、步长与重叠检查结果。
- `events/tracks/steps/birth-links.csv` 保持原始完整记录；`material-energy.csv` 逐事件与逐轨迹列出所有已声明材料，包含零值行；Si 汇总按 G4_Si 材料识别，不限制物理体积名称。
- `particles.csv` 加上每阶段粒子原生库存；初始化和事件后均遍历 `reset(false)`，同时保留 `processes.csv` 和 `hadronic-models.csv`。任何已记录粒子没有直接原生过程证据即失败，不再借 GenericIon 补齐。
- `timings.csv` 分开记录初始化、初始化库存、事件循环、事件后库存的 wall/CPU 时间；所有事件计入分母。编译、传输、归档和本地审计另由外层记录。

## 主调度者操作接口

以下命令只冻结/准备本地文件或审核已有输出，不连接远端、不调用求解器。使用仓库已有 Python 环境。

```text
python experiments/dram-see-v4/matched-transport-r1/control.py freeze-contract
python experiments/dram-see-v4/matched-transport-r1/control.py compile-inputs
```

编译包位于 `local_runtime/dram-see-v4/matched-transport-r1/inputs/matched-build-r1`。主调度者将它完整复制到原 `transport-probe/inputs/matched-build-r1`，保存复制前后逐文件哈希相等证据，再使用原 `transport-probe/operation.py` 执行编译任务。编译任务仅编译/链接/检查库，不运行 `transport_matched`。此操作仍必须等待唯一调度者和共享锁放行。

成功编译并归档后，准备单个请求：

```text
python experiments/dram-see-v4/matched-transport-r1/control.py prepare matched-init-h-r1 local_runtime/dram-see-v4/transport-probe/operations/matched-build-r1
```

按同一规则复制包到原 operation 输入目录并执行一次。运行、锁、超时和原始 operation 事实来源全部复用旧 adapter，不改 adapter 的模块全局状态。每次请求具有唯一输入包和 operation 标签；失败、未知状态或重复请求都不生成新的替代请求。

```text
python experiments/dram-see-v4/matched-transport-r1/control.py collect local_runtime/dram-see-v4/transport-probe/operations/matched-init-h-r1
python experiments/dram-see-v4/matched-transport-r1/audit_matched.py init local_runtime/dram-see-v4/matched-transport-r1/runs/matched-init-h-r1 --output local_runtime/dram-see-v4/matched-transport-r1/audits/matched-init-h-r1
```

对 E 初始化重复上述固定请求后，运行 `control.py gate-initialization`。只有两项原生初始化审计通过，才可准备 normal/miss 请求；这些请求使用审计入口 `events`。完整顺序、种子、能量、坐标已写在合同中，不能临时换种子找核事件。

`control.py budget` 只读原始 operation 记录。未知或失败的请求启动保守计入一次调用，不因未证实二进制开始而回收预算。审计输出使用新目录，存在同名 `audit.json` 时拒绝覆盖。连接断开时先核查原进程；`collect` 只接受已收集的终态。

## 验收与边界

本地测试覆盖原始出生链、过程身份、中子截断、零/点沉积、延迟次级、全材料加总、材料缺行/重复、原生动态离子缺失、几何重叠与坐标、固定请求预算和未知状态。测试数据明确是合成反例，不能列为真实粒子事件。

真正放行仍需远端编译成功、H/E 原生初始化通过、四个事件请求各自完整审计通过。`MATCHED_TRANSPORT_RECORDS_PASSED` 仅代表本合同的记录、算术与来源检查通过；不代表核反应已经出现、输运数值收敛、真实器件已校准或三维联合源已完成。

旧薄硅或厚硅源账本的几何键不能直接用于这些新记录。下游需要按本合同材料/实体表接收记录，并保留三维坐标及点沉积阻断规则。详见先于实现声明的 [假设](assumptions.md)。
