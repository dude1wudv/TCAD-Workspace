# 当前 DRAM SEE v4 器件输入

本目录为当前持续 Goal 生成输入。主代理通过原 `scripts/tcad.py` 独占原生调度、SSH、owner 和共享锁；这些模块只准备或核对数据，不启动原生工具。

受控尺寸和 α 输入使用 [controlled-cases.md](controlled-cases.md)；真实完整 Geant4 质子事件的瞬态准备、同事件 A0、零源与晚源边界使用 [proton-inputs.md](proton-inputs.md)。新增接口的本地检查不表示原生源或响应已获资格。

```powershell
python experiments/dram-see-v4/continuous/device/prepare.py --role B1-D2 --run-id <new-run-id>
python scripts/tcad.py run local_runtime/dram-see-v4/continuous/device/projects/<new-run-id> --run-id <new-run-id> --detach
python scripts/tcad.py status <new-run-id> --json
python scripts/tcad.py collect <new-run-id> --json
```

生成器输出新目录，已存在目录拒绝覆盖。默认绑定生成时 `scripts/tcad.py` 的实际 SHA-256；runner 再改变时，旧项目不会被悄悄刷新。每次新尝试使用新 run ID 并保留旧输入及失败原档。

D3 使用 `--role B1-D3`。两种 bit 的实际写读使用 `--role B1-A0-main-b0` 或 `B1-A0-main-b1`，并添加 `--d3-source <已完成并收集的原D3目录绝对路径>`。A0 直接导入 D3 网格和几何证据，只有一个 SDevice 步骤，不重建或重测几何。

当前输入从已完成审查的 `s2-runner-integration-r1/20261016T155822Z/candidate-r2` 复制。器件、掺杂、单位、偏压、写读时间线、物理参数、几何比较数值和提取脚本保持原值。`provenance.json` 记录每个复用文件的原哈希；`input-manifest.json` 冻结当前实际输入；`execution-context.json` 绑定 run、role、producer、runner、manifest 和本轮授权。旧 release、预约、额度及预测签字文件不参与新执行。

原生失败驱动的修改由 `observer_patch.py`、`doping_patch.py`、`visual_patch.py`、`mesh_patch.py` 应用到新副本，逐项记入 `provenance.json/native_repairs`，不再列入“原样复用”清单。已有项目和原档保持原字节；修改不涉及名义几何或比较容差。深尾处理的非严格等价数值地板、连续有源区网格加密均单独记录，不称物理参数校准。

`geometry_bridge.py` 提供原 runner 所需接口：

- `geometry_admit(project, spec, runner_sha256)`：核对当前上下文、单核单线程、完整输入和步骤顺序；返回 `s2_geometry` 配置。D2/D3 准入不要求未来的 mesh。
- `geometry_stage_reuse(project, cfg)`：只从已收集 D3 原档复制已绑定字节；原 SSH 非零可以保留，但同一原作业的远端退出、完整收集和各工具退出必须真实成功。
- `record-exit --folder . --source step-NNN-tool-exit-code.txt --canonical ...`：逐字节保留原退出；命令捕获成功不代表工具成功。
- `prepare --folder . --run-id ...`：snmesh 后核对真实网格和原退出，写原 mesh 描述符及 TDX 区间起点哈希。
- `finalize --folder . --run-id ...`：几何观测后调用比较器，保留原始证据和当前上下文副本。几何观测通过仍不是完整器件科学验收。

`mesh_resource_guard.py` 记录实际可用空间、内存和网格顶点数，检查非空 mesh、冻结输入及 A0 精确复用。没有调用次数、CPU 小时、训练、存储额度或未来预测门；当前观察不宣称能够预测后续峰值需求。

首 D2 输入为 `local_runtime/dram-see-v4/continuous/device/projects/20261017T041900Z-v4-continuous-b1-d2-r1`。该目录已交给主代理，不能修改。后续源码变更只影响之后生成的新项目。

原生 r2、r3 均在 SDE 接触 bbox 观测时退出 1；r4 越过 SDE，但 snmesh 因浮点异常退出 1；r5 通过 SDE/snmesh 并取得真实掺杂探针，SVisual 积分/极值上下文失败。当前候选 `20261017T044000Z-v4-continuous-b1-d2-r6` 按实际 r5 结果修正显式 plot/geom、仅识别当前物理区域派生的 Interface 元数据，并连续加密有源掺杂梯度。完整原因及待原生确认的边界见 `native-repairs.md`；候选生成或本地检查不证明后续阶段已通过。

r6 的 SDE、snmesh、SVisual 实际退出均为 0，但原 runner 未识别真正的 `svisual_exec` ELF，因此运行以 admission 86 停止；未进入 DC。其 42 个掺杂探针和 4 个 Si 掺杂极值全部满足原门，接触坐标与 SiO2 掺杂的 SVisual field 极值却是 `nan`。只读转换原 mesh 的成功诊断 `cgoal-tdr-observe-20261017t045517z` 已证明：TDX 元数据和 CLI 转换均退出 0、原 mesh 前后哈希一致，实际接触拓扑有可测节点，SiO2 三个字段各有 3243 个有限的零值。

新 `s2_geometry` schema 为 `dram-see-v4-continuous-geometry-r2`。D2/D3 使用 `sde → snmesh → tdx metadata → tdx CLI → svisual → sdevice` 六步，两个 TDX 原退出分别保留。`dfise_observer.py` 直接解析原导出的节点、接触元素和完整区域字段，检查计数、归属、索引、有限值、单位与变换；D2 另用所有实体三角形的闭环、正面积及唯一顶点数核对原数据，并与 SVisual 域边界、材料积分独立对应。比较器保留原 SVisual `nan` 行，只将原接触范围和非 Si 掺杂极值固定交给实际 DF-ISE 观测；期望值与容差不变。

`20261017T050348Z-v4-continuous-b1-d2-r7` 已生成冻结输入，manifest 为 `8046d46960cf8ac5cd91c59443ad748eb6d64f91b80dabe0ba7af89dde928fe9`，runner 为 `502737272a2ae02b2263fcb7e4606c28c73078d233ebf38e267cc0e38e989cdc`。r6 真实原观察和成功转换的数值组合审计已通过 105 项比较，但这没有改写 r6 的原失败状态，也未证明 DC 或后续器件任务完成。

r7 随后在真实运行中通过 105 项几何检查，前五工具退出均为 0；SDevice 因缺少 `sdevice-pathsearchtun` 许可在迭代前退出 255。当前 `physics_patch.py` 按主线决定在新副本中显式采用 local Hurkx，保留自洽 BTBT，并映射原声子辅助均匀场参考参数；D2/D3/两种 A0 bit 保持同一物理假设。安装卡、r7 和全部旧冻结包未改。模型边界和敏感性方案见 `btbt-local-branch.md`。

新输入为 `20261017T051217Z-v4-continuous-b1-d2-r8`，manifest 为 `830f49738df000115613d3db6b02440e7907f89826e9932f70a3cb1d78010b89`，绑定同一 `502737...` runner。其语法、许可、DC 收敛与物理结果仍待原作业确认。新增本地 3 项检查仅覆盖这次物理分支映射和四角色一致传播，未重跑旧检查。

新增 8 项定向软件检查的日志与退出码在 `local_runtime/dram-see-v4/continuous/device/test-current-context-r1.*`。它们验证无旧审批字段准入、输入/runner 错配拒绝、合成标记拒绝、失败退出原样保存、A0 缺真实来源拒绝、资源观察及数值比较逻辑未变；旧套件沿用已通过证据，未重跑。真实原生语法、收敛、DC 与写读物理结果以主代理实际运行和分析为准。
