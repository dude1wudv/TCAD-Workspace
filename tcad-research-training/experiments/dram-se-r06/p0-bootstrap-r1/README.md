# r06 P0 / O2 日志修订 bootstrap r1

本包为本地准备成果，所有文件均位于本目录。未部署、未编译 PMI、未求解、未写服务器、未改队列，也未创建任何 `.so`。生产部署、编译任务和入队均交给原 controller：编译须通过原 Runtime 的 Geant4 operation backend，以新 recipe `pmi_build` 在空闲共享池内执行 compile-only；不直接手工进入虚拟机编译。执行依据为 `plans/dram-se-ddr5-lpddr5/EXECUTION-AUTHORIZATION-r06-20261117.md`、`R06-HANDOFF-AND-PREDICTOR-CONTRACT.md` 及本轮明确的子代理边界。

## 入口与当前状态

- `source/pmi_r04_nodal.C`：新日志源码，版本 `r06-o2-global-r1`。
- `pmi-logging-only.patch`：相对于真实 mc2 冻结源码的逐行差异。
- `logging_patch.py` / `check.py source`：重建并逐字节校验日志专用变换，拒绝其他原源码或额外修改。
- `prepare.py`：仅核验、准备新编译目录、绑定真实新 ELF 后生成新输入和 admission；不调用 SSH、编译器、求解器或队列。
- `compile-in-original-vm.sh`：**待原 Runtime 通过 Geant4 operation / `pmi_build` 调度**的原虚拟机 CMI 编译任务载荷，只编译，不求解。
- `logging-zero-prefix-plan.json`：在任何新求解之前冻结的 bootstrap 目的、验收范围和 prototype 限制。
- `bootstrap-proposal.json`：两条新任务的待编译提案，`submit_ready=false`。它不是可直接发布的 `tcad-work-items-v1` 队列。
- `verification.json` / `verification-*.log`：实际离线验证结果。

本包只推进日志实现和短探针准备。`O2` 科学验收、源积分、新数值比较器、完整 WHR、新 22 ns 时序和正式样本完成量均未通过本包授予。

## 已核实的原输入

只读 SSH 使用 `管理入口`，移除了本机代理变量，保持 SSH 密钥校验。检查时 `tcad-autonomy.service` 为 inactive，进程列表未见活动求解器。旧 observation 中仍有两条 `r05 ... FAILED_BEFORE_LAUNCH` 需原调度者对账；不能把“没有活动求解器”解释为池、锁或租约全部空闲，本包未处理这些状态。

原输入实在路径为：

```text
<SIM_USER_HOME>/course-workspace/experiments/dram-se-r04/electrical/
  mc2-prefix-diagnostic-r1/inputs/r04-l08-mc2-prefix-b0-zero-a-v1
  mc2-prefix-diagnostic-r1/inputs/r04-l08-mc2-prefix-b0-zero-b-v1
  mc2-prefix-diagnostic-r1/inputs/r04-l08-mc2-prefix-b0-event0-v1
```

上述路径在文件系统中连续书写，换行仅为阅读方便。完整路径和每个文件的 SHA-256 见 `evidence/remote-survey.json`。

实际 deck 的唯一 `Transient` 终点是 **`1e-13 s`（0.0001 ns）**，不是 15.2 ns。本轮按浮点终点搜索现有 `experiments/dram-se-r04/**/*.cmd`，未确认终点为 15.2 ns 的冻结输入；这不证明其他目录不存在该输入。本包选择确实存在、已有旧日志及重复性证据的首个 BE prefix，不猜测 15.2 ns 路径，也不把旧失败的 event-prefix 记为已求解。

冻结 mesh：

```text
058a547770051c4047899c2e4faa76eab4da4d1b3d0642d94c9c5962375f4475
```

显式零源 header：

```text
R04_NODAL_SOURCE 1 10170 0 0
```

真实 mc2 输入中的原 PMI 已是**每实例原子计数**，SHA-256 为：

```text
6c2360c8b75840561fb61a61dccc8fddde0d4e14061f65cbd1a6f748bdb77b75
```

它与 `coupling/native-nodal-r1/pmi_r04_nodal.C` 的更早普通计数源码不同。本次以实际 mc2 输入版本为修改基底。原 `.so` 仅记录哈希，未复制或重新标记。

## 日志变更及界限

1. 删除每实例的 `callbacks_`，改用该加载插件映像共享的原子计数，`memory_order_relaxed`。
2. 全部实例合计最多打印 4 条成功初始化明细，随后最多 1 条初始化限额通知。每实例的真实 source 加载、验证和错误路径仍执行。
3. 全部实例合计最多打印 512 条回调明细，随后最多 1 条回调限额通知；自 1024 开始只在二的幂计数打印进度。64 位计数下，进度位置最多 54 个。此限制只针对本 PMI 重复跟踪，不限制求解器总日志、错误、警告或完成信息，也不预设日志总行数或提速倍数。
4. 插件卸载时向原进程 stderr 输出一次计数摘要。摘要明确写 `solver_success=unknown accepted_steps=unknown`；它既不是求解完成钩子，也不是接受时间步证据。原生求解完成仍须核查原退出码、收敛和完成日志。
5. 没有改变源读取内容、每次回调的 `ReadTime`、步长、步类型、坐标、region/material、平均公式、归一化、用户场输出和异常错误调用。准备出的 `device.cmd`、mesh、源表、辅助源和头文件保持字节一致。

保留的 `Math Number_Of_Threads=1` 也不改写。原 mc2 runner 在真实执行时施加 2 threads / 2 cores；新提案继续声明 `native_threads=2`、`native_cores=2`，原 controller 仍须核对实际资源准入和求解器线程证据，不能仅凭 deck 或 proposal 宣称线程已生效。

## 给原 controller 的具体 bootstrap 顺序

以下 Linux 命令仅为交接，**本子代理没有执行它们**。主代理将完整包部署到服务器同名新目录后，在 `<SIM_USER_HOME>/course-workspace` 执行：

```bash
P=experiments/dram-se-r06/p0-bootstrap-r1
python3 "$P/prepare.py" audit --workspace <SIM_USER_HOME>/course-workspace
python3 "$P/prepare.py" stage-build --workspace <SIM_USER_HOME>/course-workspace
```

`audit` 会重新核验冻结原目录的全部文件哈希，包含原元数据和旧 ELF 的哈希。`stage-build` 只新建 `$P/build-original-vm-r1/`，其中有新源码、原头文件、编译脚本、冻结请求和校验清单，**没有 ELF，也不调用编译器**。目标已存在就停止，不原地覆盖。

原 controller 将整个 build bundle 包装成原 Runtime 的 Geant4 operation backend 的 **compile-only** 任务，使用新 recipe `pmi_build`；任务 admission、资源准入及发布由主代理整合，本包不修改 gate recipe。须等待原共享池空闲，通过原 runner/gate/锁执行，禁止直接手工编译或另开池。载荷在原 CentOS 7 虚拟机中的**新目录**执行 `compile-in-original-vm.sh`，由原 Runtime 正常收集。

该载荷检查 CentOS 7 / x86-64、原 vendor header SHA 和预期源文件，内部只调用已核实的原安装命令：

```bash
/usr/synopsys/sentaurus/W-2024.09/bin/cmi -O -v pmi_r04_nodal.C
```

脚本沿用原编译证据中的 SDK / include / runtime-library 路径。它保留编译 stdout、stderr、退出码、导出符号、`ldd`、vendor header 与输入校验，并在成功后生成 `build-receipt.json`。旧 ELF、旧编译收据或编译输出已经存在时拒绝继续；失败保留证据，下一次另建新目录。脚本没有 SSH、求解器、runner 或队列动作。

compile-only 经原 operation backend **collect 完成后**，原 controller 才将**完整真实编译目录**及收据物化到服务器本包下的另一个新目录，例如 `$P/build-returned-r1/`，然后：

```bash
python3 "$P/prepare.py" materialize \
  --workspace <SIM_USER_HOME>/course-workspace \
  --build-dir "$P/build-returned-r1"
```

`materialize` 先核验真实新 ELF、版本字符串、源/头文件、编译路径、证据哈希和原输入，然后才创建 `$P/prepared-prefix-r1/`，生成：

```text
inputs/r06-p0-d0-o2-zero-prefix-a-r1/
inputs/r06-p0-d0-o2-zero-prefix-b-r1/
admissions/<task_id>.json
diagnostic-plan.json
build-receipt.json
proposals.json
preparation-receipt.json
```

第二条依赖第一条，采用相同物理执行文件和同一实际新 ELF。它们是新日志版本的两条零源重复性诊断，合计占 **2 条 P0、0 条粒子诊断**；实际预算仍由原 runtime 的 submission intents 计算并检查 `64 / 12` 上限。

这里的 `D0-nominal` 是 gate 使用的 prototype 诊断桶，输入实际来源为 r04 L08/p000；它不等于 r06 D0 几何/掺杂与 WHR 已合格。`formal_case_id=null`、`statistics_eligible=false`、`budget_account=p0_diagnostics`，正式清单完成量始终为 0。

新 admission 使用最终 gate 所需的 schema、身份、profile、`zero_whr` recipe、真实全文件 `input_sha256`、时间戳及 `diagnostic_plan` 路径/哈希。零源日志探针明确用 `zero_whr`，不把它错误归入需要独立事件来源的粒子 recipe。

原 controller 最后按最终 contract 的 `p0_admissions_dir` 纳入 admission，保持引用路径和哈希不变；对实际任务、实际策略和现有 intents 调用 `r06_gate.verify(...)`，成功后由原调度入口按原 r4 配置发布短 prefix。顺序固定为：原 Runtime compile-only → 原 backend collect → `prepare.materialize` → r4 短 prefix。**本包不自动合并队列，也不替换 admission 配置或原 gate。**

## 收集后的检查与后续门槛

日志检查可在本机或服务器只读执行：

```bash
python3 "$P/check.py" source
python3 "$P/check.py" log --log /path/to/original-process-execution.log \
  --require-unload-summary
```

第二条需要原进程完整输出流，包含 PMI 明细和 stderr 卸载摘要。不要把原生日志与已镜像同一批内容的 stdout 拼接后重复统计；若 solver `.log` 没有卸载摘要，核对原进程 stderr/原归档。检查器不以计数到达某值推断接受时间步，日志计数也不能代替源积分或波形验收。

短任务收集后仍须用原 reader 核查真实完成、有限电学表、零 `G/UF0/UF4`、原始行序/时间、原波形差分，并保存 wall/CPU、日志及归档字节。保留旧严格比较器的失败，不按新结果放宽阈值。这两个首步零源任务不够验证写入/保持/读出、不包含非零源激活，也不足以建立完整瞬态误差界。

推进长任务前，原 controller 仍须准备并冻结**同一新 PMI 版本**的短非零源/零源对照，绑定真实单 primary 来源及积分，完成适用的数值比较。此后再做至少一条代表长任务比较。若采用 `logging_short_probe` 等粒子 recipe，plan 必须是 `independent_primary_count=1`，并给出真实 `event_provenance` 的路径和 SHA-256；不能拿本包的零源 plan 代替。

旧 `local_runtime/dram-se-r04/mc2-zero-b0-native-r1`、对应 b1 的 extraction/receipt 可用于检查旧 WHR 在 22 ns 附近的保持稳定性，但不是本日志版本或新 22 ns 时序的匹配零源。不重跑旧 b0/b1 完整长零源来凑配对；也不将旧 15 ns 写入期标签转成新保持期标签。

## 实际验证

`verification.json` 记录 10 个离线测试、源码确定性变换检查和 Bash 语法检查。测试覆盖父输入漂移拒绝、排他创建、禁止路径逃逸、缺少真实 CMI 收据时在写输入前停止、旧每实例重复计数识别、日志缺失/非法进度识别，以及只读加载主代理的实际 `r06_gate.py` 验证新零源 admission schema。

测试数据明确是离线合成 fixture，没有生成或执行任何 ELF。首次联调暴露过 gate 在并行开发中增加返回元数据和 intents 参数，以及文件句柄警告；已改为测试公开 `verify` 接口并修复文件关闭，最终完整测试通过。未执行原虚拟机 CMI、真实新 ELF 输入物化、原生短探针、长任务、波形或科学验收。

## 冻结与交付

主代理确认采用原 Runtime 的 Geant4 operation / `pmi_build` compile-only 调度后，本次最终仅更新了上述交接说明、编译脚本注释及 `build-request.json` 的部署说明文本；源码 patch 与执行逻辑未改变，未新增任务。现有离线验证记录保留其实际执行时间和 gate 版本，不声称已测试尚待主代理实现的 `pmi_build` recipe。

最终 `PACKAGE-SHA256SUMS` 绑定本包的源码、脚本、计划、提案、README、JSON 验证及必要来源证据，排除 `.test-work/`、`__pycache__/`、`*.log` 和清单自身，便于主代理过滤 bundle。原始测试日志可留在本地，不作为部署必需文件。以交付消息中的清单 SHA-256 校验冻结版本；本子代理交付后停止写入。
