# 原 runner 几何接线：依据与接口

本目录是未应用、未授权的离线集成候选。`geometry_bridge.py` 仅使用 Python 标准库，按 Python 3.6 语法编写；没有进程、网络、原生求解、编译或提取启动接口。主 runner 的补丁负责将这些数据处理函数接到原执行链。当前没有原生正常路径验证。

## 网格步骤拆分的本机文档依据

来源为本机已保存的 W-2024.09 私有安装手册；只记录接口，不复制手册正文：

- `local_runtime/dram-see-v4/three-dimensional-pilot-r1/references/sde_ug-installed-private.pdf`：p450 的 `sde:build-mesh` 会生成边界和命令文件，并在 SDE 内部启动/等待 Sentaurus Mesh。因此 SDE 整体退出不能充作 mesh 子进程原始退出。p402 的 `(get-body-list)` 返回实际几何 body；p760 的 `(sdeio:save-tdr-bnd body-list file-name)` 写 TDR 边界；p596 的 `(sdedr:write-cmd-file cmd-file)` 写当前全部掺杂与细化定义，供随后 meshing 使用。
- `local_runtime/dram-see-v4/three-dimensional-pilot-r1/references/smesh_ug-installed-private.pdf`：p13-14 的 `snmesh [options] project_name` 读 `project_name_bnd.tdr` 和 `project_name.cmd`，输出 `project_name_msh.tdr` 和 `project_name_msh.log`；p14 明确列出 `--threads` 与 `--max_threads`。p18 的 IOControls 也支持显式 inputFile/outputFile，但当前候选使用上述默认文件命名。

新副本将内嵌 mesher 替换为：

```scheme
(sdeio:save-tdr-bnd (get-body-list) "cell_bnd.tdr")
(sdedr:write-cmd-file "cell.cmd")
```

原 runner 显式 mesh 步骤为 `snmesh --threads 1 --max_threads 1 cell`，只构建一次 mesh。资源 guard 在该步骤成功后、几何 SVisual/SDevice 前执行。原冻结 CAD 不改；本候选没有证明拆分前后原生输出逐字相同，也没有验证边界分片或生成命令文件的真实内容。

## 桥接函数

| 接口 | 职责 |
|---|---|
| `geometry_admit(project, spec, runner_sha256)` | 无配置时返回 None；有配置时在 SSH/原生前拒绝候选、缺件、未授权与 hash/角色/run/预算不一致，返回原 cfg，不写文件 |
| `geometry_record_exit(folder, source_name, canonical_name)` | 仅允许固定三组映射；规范文件以独占方式逐字复制原始退出，保留非零；不从 JSON 或 wrapper 补零 |
| `geometry_prepare(folder, run_id)` | 重核 produce 输入，核实 SDE/mesh 原始退出和实际 mesh，再独占写纯 Tcl 列表描述符 |
| `geometry_finalize(folder, run_id, synthetic_fixture=False)` | 核实三原始退出，写实际 context，调用被冻结的原 evaluate.py 到新 geometry-evaluation 目录；根报告只追加来源绑定，返回 0/2 |
| `geometry_source_bundle(project, cfg, execution, synthetic_fixture=False)` | 只读验证完整 D3 source tar/manifest、明确验收与发布绑定，返回需要逐字导入的成员 hash |
| `geometry_stage_reuse(project, cfg, synthetic_fixture=False)` | 验证已明确验收的完整 D3 source tar/manifest，导入原字节到 A0 输入；不运行任何测量 |

`geometry_prepare`/`geometry_finalize` 只为 produce 模式服务。原生运行时的实际目录名必须等于发布的 run_id。context 的退出数值来自实际文件解析，不由默认值建立。原比较器的 `numeric_checks`、`checks`、阈值和资格语义均不改；原输出保留在 `geometry-evaluation/geometry-validation.json`，桥接版根报告是新文件。

固定退出映射：

| 原捕获文件 | 规范名称 |
|---|---|
| `step-001-sde-exit-code.txt` | `sde-exit-code.txt` |
| `step-002-snmesh-exit-code.txt` | `mesh-exit-code.txt` |
| `step-003-svisual-exit-code.txt` | `svisual-exit-code.txt` |

CLI 仅有数据处理子命令，原 runner 未来使用的形式为：

```text
python3 geometry_bridge.py record-exit --folder . --source step-001-sde-exit-code.txt --canonical sde-exit-code.txt
python3 geometry_bridge.py prepare --folder . --run-id <released-run-id>
python3 geometry_bridge.py finalize --folder . --run-id <released-run-id>
```

`record-exit` 的 CLI 退出 0 只表示原字节成功保存，即使记录的是非零 native 退出。runner 必须独立传播捕获到的 native/admission 退出，不能以 helper 退出码替代。prepare/finalize 不会把非零原始退出继续送去观测/比较。

## 发布与输入的精确字段

使用原有 `s2-execution-release-r1` 和 `s2-geometry-producer-release-r1` schema。execution release 需 RELEASED、execution_enabled/explicit_native_authorization 为 true、synthetic=false、scheduler=root、threads=cpu_count=1，且 role_id/run_id、expected_runner_sha256、input_manifest_sha256、geometry_bridge_sha256 与实际输入一致。人类授权仍由原 `authorization_evidence_file`/`authorization_evidence_sha256` 绑定。

produce 的 execution release 另以 `geometry_release_sha256` 绑定 geometry release。geometry release 按原 evaluator 字段绑定 plan/evaluator/policy/authorization/producer，同时以 `input_manifest_sha256`、`budget_reservation_sha256` 绑定清单和预约。

`geometry-budget-reservation.json` 必须为 `s2-geometry-budget-reservation-r1`、status=RESERVED、synthetic=false、category=native_geometry_extractions、units=1；budget_id、budget_reservation_id、role_id、run_id 与 geometry release/cfg 一致。几何预约的 budget_id、budget_ledger_sha256 还必须与本角色 execution release 相同，几何 reservation ID 必须不同于本角色执行预约 ID，不能以一笔预约同时覆盖两类调用。预算 ID 必须明确属于新的 S2 账本，拒绝 nuclear 旧账。bridge 不创建、修改或扣减账本；真实 owner 对预约与总预算的准入仍是执行前置条件。

准入同时复核原资源策略的 schema、approved/execution_enabled=true、匹配 role、非空 release_id、正数且有限的空间/内存预测，以及 forecast_evidence_sha256/scheduler_preflight_sha256。这只是复用原 guard 的审批前提；实际网格和资源仍由原 guard 在 mesh 后检查。

`input-manifest.json.files_sha256` 必须覆盖实际 `project.json`、helper、原 evaluator、计划、两个观察脚本、几何合同、资源 guard/policy、device deck，以及策略、授权、预约。execution release、geometry release 和 input-manifest 自身不进入该映射，以避免循环 hash。bridge 不改写清单。候选只保留 project.review.json、execution=false/null 字段，不能被此入口放行。

produce step 顺序和参数严格固定为：

```text
sde -e -l geometry-with-measurements.scm
snmesh --threads 1 --max_threads 1 cell
svisual --threads 1 --max_threads 1 -b -tcl -script measure-geometry.tcl
sdevice device.cmd
```

SDevice 的原 `--threads 1 --exit-on-failure` 仍由原 runner 加入。此处没有第二 runner，也不创建发布/运行子命令。

## A0 的 D3 复用合同

A0 cfg 明确 source_run_directory 与 acceptance_file。当前 A0 execution release 以 `d3_acceptance_sha256`、`d3_source_manifest_sha256`、`d3_source_archive_sha256`、`d3_mesh_sha256`、`d3_producer_run_id` 绑定源，不要求 A0 新增几何预约。

验收文件字段为：schema=`s2-d3-geometry-reuse-acceptance-r1`、status=ACCEPTED、synthetic=false、source_run_id、source_manifest_sha256、source_archive_sha256、mesh_sha256、geometry_validation_sha256。源 manifest 必须 COLLECTED、origin=native_pipeline、synthetic=false、真实 SSH/remote/collection 和声明的工具退出均为 0；results_sha256 必须匹配完整 source results.tar。

原生源目录名必须等于 D3 producer_run_id。源报告必须保留 B1-D3 的 producer_run_id、native origin、四项 geometry checks 通过以及一致的 mesh/context。导入 `cell_msh.tdr`、`cell_msh.log`、根几何报告和报告 evidence_sha256 指定的全部原始证据。A0 的输入清单先列精确导入 hash；admit 只允许这些导入项暂不存在，stage_reuse 末尾逐项核验。已有同 hash 文件只核对，冲突拒绝，不覆盖；源 tar 的重复、路径逃逸和非普通成员拒绝。

生产者的原发布/授权/预约/清单以原字节放在 `geometry-producer-bindings/`，根报告引用这些相对路径。A0 复制这个固定命名空间，不把 D3 execution release 或授权覆盖当前 A0 根输入；observation-context 保持 D3 身份，不重标成 A0。

## 隔离合成验证入口

`synthetic_fixture=True` 只允许直接 Python 函数调用，CLI 没有对应开关，`geometry_admit` 固定使用 False。原生入口拒绝路径含 `UNIT_FIXTURE_NOT_NATIVE` 或存在 `SYNTHETIC_NOT_NATIVE` 标记的目录。

finalize 合成模式要求目录路径含 `UNIT_FIXTURE_NOT_NATIVE`、普通文件标记 `SYNTHETIC_NOT_NATIVE`、project cfg 明确 synthetic=true/execution_enabled=false，且输入清单覆盖并匹配 project/helper/evaluator/plan/脚本/合同。若存在 release 文件，也必须 synthetic=true/execution_enabled=false。它调用原 evaluator 的 synthetic 模式，context 和报告保留 origin=synthetic_fixture、synthetic=true、native_qualified=false。只有 input-manifest 的原字节副本进入 producer-bindings，不伪造原生授权。

A0 合成复用要求当前 A0 和 D3 源目录均满足路径与标记隔离；当前 cfg 和 D3 tar 中的 project.json cfg 均 synthetic=true/execution_enabled=false。当前 execution 描述也须关闭执行；源 manifest、report、context、acceptance 均须 synthetic=true/origin=synthetic_fixture。正常复制与错绑检查复用同一归档/hash/run/退出/冲突路径，复制后仍是原字节合成证据。隔离夹具的目录名不冒充原生 run 目录身份。

最小内部调用为 `geometry_finalize(fixture_folder, run_id, synthetic_fixture=True)` 和 `geometry_stage_reuse(a0_fixture_folder, cfg, synthetic_fixture=True)`。这些入口只验证软件数据接线，不取得原生运行、预算、科学验收或发布资格；本文件不声明测试已执行或通过。

## 当前边界

首切片分账提案为 D2/D3 各一次几何 SVisual，A0-b0/b1 各一次原字段 SVisual，共四次；旧 postprocess=2 是已花历史成本，不能抵扣。两个几何观察没有额外 SDE/mesh 构建，原四 CPU 小时和八 GiB 包络不扩大。当前仍无真实授权、预约、原生调用、预算写入或旧档改写。原资源、owner、严格 SSH、共享锁、单线程/单核准入继续由原执行链负责。
