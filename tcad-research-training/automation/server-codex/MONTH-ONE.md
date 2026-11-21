# r0.6 首月仿真：从计划位到可复现读出

本手册是操作入口，不是上线收据。容量取自当前 readiness、profile 与资源观测；计划数取自[冻结清单](../../plans/dram-se-ddr5-lpddr5/month-one-cases-r06.json)，不是存量任务。不要改冻结设计去迁就槽位。

## 先问为什么空，再问怎样补

```sh
python3 -B controller.py --policy <POLICY> explain
python3 -B controller.py --policy <POLICY> explain --month-one
python3 -B controller.py --policy <POLICY> explain --case <FROZEN_CASE_ID>
python3 -B controller.py --policy <POLICY> reconcile --read-only
```

前三项只读文件，不采样虚拟机。最后一项通过原 runner 做实时只读对账。对齐 UTC、新鲜度、pause 标记、原生进程、租约和释放；`serve --once` **不是**探针。`claimed` 只表示已有 intent，`proposed` 只表示候选；`not_bound` 不代表应重跑。`evidence_record_to_verify` 不做科学验收。不能用最新文件替换首次 intent 的科学对象。公开网页不暴露私有索引、原始观测或完整队列。

1. 396 个计划位含 Z 26、AL 最多 82。214 是统计意图上限，不是合格数。第一阶段只备 D0–D3 的 T/S/R 104 位（32/60/12）、8 个 Z 基线桥、24 个不同的输运池。优先检查 6 个 G0/C1 候选池已有的精确请求/结果。复用须核对几何、种子、源面积、分母、完整原始账本、输入摘要；名字相同不够。
2. 先排整机阻塞：暂停、发现不确定、未知租约、未登记原生求解、存储下限、许可、维护窗口。再看池排空、串行 runner 通道、收集、隔离和按宽度供料。`candidate_supply_by_width` 是通过科学/依赖初筛且未提交的候选数，不是资源准入或在跑数。
3. 已交接的 17 vCPU 配置为 TCAD `12×1 + 1×4`，后台另留 1 核；Geant4 最多 4 项，只在原共享池安全排空后切换。设备的 13 个科学 profile 与 TCAD 的 13 个执行槽互不对应。以冻结输入决定宽度；禁止改线程数、重复选事件、用诊断任务凑数。缺四核供料时如实报空。已有占位不等于原生运行重叠。

## 只跑开发仿真、收原始数据

如果目的只是收集新的开发 TCAD 仿真输出，给原队列一条普通任务：`{"id":"raw-dev-example","backend":"tcad","project":"local_runtime/raw-development/raw-dev-example"}`。由原规划者写队列；示例不是待运行输入。项目目录要放实际的新 deck 和匹配槽宽的 `project.json`，不需要额外的科研准入文件。不把已有正式任务、修复任务、封存样本或诊断复制改名来占槽。

调度器在提交前重验输入，记录 `scope=raw_development` 和输入摘要，使用原槽锁、许可检查与归档释放流程。输出是原始开发数据，不自动进入正式 case、统计或训练。已有正式任务仍按原绑定收集。共享池已开始排空时，不混跑另一种 profile，也不把待派发条目算作在跑。

## 准备并发布一波，不新增调度者

- 生产者先核对[开发首波范围](../../plans/dram-se-ddr5-lpddr5/P0-CLOSEOUT-AND-D0-D3-FIRST-WAVE-PREP-r06-20261120.md)，用现有科研脚本 **stage** 到新目录：基线复用 → 原输运池 → 完整 primary frame（保留零沉积）→ 冻结 selection/case_draw_map → 材料化输入、依赖、正式准入 → 单任务 proposal。不要把 `stage` 和 `publish` 混用；服务器独有科学脚本不在控制器包内。未有生成规则时交给规划者补，不凭位置推造 deck。
- 日常模式保留原异步规划器；可选确定性波次模式需要明确的**队列写权交接**：停用所有其他发布者、确认 readiness/暂停归属，在被审阅的私有策略用 `planner_mode=disabled`。模型不在数值派发的关键路径。两种模式不能同时写队列；默认不启用波次。
- 用只读命令 `python3 -B controller.py --policy <POLICY> prepare-wave <相对路径/proposal.json> [...]` 打印波次 JSON。只接受显式指定的 1–13 份 staged proposal；缺任何准入先移出该项补证。以新版本名独占保存，核对 SHA，把 `{ "path": "<工作区相对路径>", "sha256": "<64位SHA>" }` 放入策略 `month_one_wave`，重新交接后生效。**无需为每个空槽造一个 proposal**。manifest 中 entries 的顺序即显式次序；运行顺序仍由原优先级、依赖、池和资源决定。
- 在服务持锁且恢复对账通过后，唯一发布者将尚未存在的候选追加到原队列。错摘要/超范围/有冲突的条目单独记录 `scheduler.month_one_wave.blocked`。已存在的相同条目不重写。队列竞争/暂停拒绝新写入。无门禁通过就无 intent。原 Runtime 临提交重验输入与准入，仍按原租约收集、释放；`repair_of` 要求原归档、独立新身份和变化输入。
- 不热换运行中的策略/波次。旧波次尚有已发布条目时会继续受原 Runtime 保护；替换策略不会撤销原 intent 或证明队列里工作已经结束。

## 抽样拒绝怎么办

先核对 manifest/authority/校验器、frame、selection、case_draw_map 及原 intent。冻结算法把 **Python 精确版本**写进设计 SHA，且 b0 选取依赖此 SHA。不能改版本字段、跳过相等判断、伪造权重或重选另一个事件。确需跨解释器重放时，仅在管理员拥有的策略中配置 `scientific_gate.sampling_interpreters`，如 `{"3.12.15":"/usr/bin/python3.12"}`；先核对可执行文件所有者和真实版本。缺失或重放不符时只暂缓该任务。

实际只读回放：D3/C1 老候选 r2 的原件在 3.12.15 全字段重放一致，在 3.11.17 设计版本/摘要不一致。但完整门禁**仍拒绝 r2**：r3 已占同一 case 并有成功收集观测。保持原始身份，优先查 r3 的 readout 证据，不再派发 r2。收集不等于科学验收。

## 交付数据，不把未知填成零

以服务器已有 `r06_export_readout_features.py <冻结自然读出索引> --output <新版本路径>` 在对应的冻结环境导出。此导出器和绑定/来源分组/截面脚本配套，不把未跟踪的服务器脚本偷偷覆盖到公开仓库。验收时独立重建并比较规范化 JSON（UTF-8、键排序、无空白、禁 NaN）SHA；文件字节 SHA 另记。变更 exporter/输入/证据时生成新版本。

- 自然响应保留 SN1 读出裕量 V、0/1 错误、存储位、源条件/单位、case/event/run、原验收、来源组、分母/源面积、精确入选概率和 HT 权重。空源等价必须有自身的基线绑定；无数据不是零。放大的 T 单列，不混入天然 R/S；配对 b0/b1 不独立。
- 只读 r4 重建：索引 SHA `74a7252da9c5ce9363748ed37082cc7abbe05f9e5d402736c751092df7d157b7`，导出器 SHA `61a483b6c5a145c5d17b7860cf82028613ed9c029c2a7ddf784ab1cbc486b4cc`。3.11.17 两次产生相同规范化负载 SHA `bd073ef3597c6e92729c528295df6d3d527ca54263bc9cd3e045a8b2def97b35`。9 行、2 个来源组、已观测错误类别只有 0。不是 9 个独立来源，不训练、不做三折、不推导产品 SER。HR/HP 在训练冻结前保持封存。

## 发布、验收、回滚

等待前序负责人确认版本与暂停用途；核对真实 ExecStart/解释器、原租约/内核锁、未登记原生进程、各存储和内存下限及 readiness。保留旧 release 和确切配置备份，仅从干净提交打包 runtime-only SHA 清单；保留服务器独有科研源码、私有队列和账本。切换后先 `check`、只读对账和按 case 核对。暂停仅由持有人在确认后解除。小波用合法新任务验证原 intent → 原生进程 → 归档释放 → 原 case 验收；记录 UTC、槽宽、峰值原生重叠、空闲原因和数据快照。只在资源允许且有匹配工作时扩到 13。异常则停止新增、恢复前一代码/配置，保留所有新旧事实和失败证据；不得恢复旧账本覆盖新 intent。
