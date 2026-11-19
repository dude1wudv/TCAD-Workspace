# 三维原生场审计 r1

只服务已冻结的三维人工 A0/A1、bit1、主网格。这里没有求解器调度、SSH、训练、真实事件导入或二维降维入口。完整三维核事件仍属于后续里程碑。

## 接口

当前实现固定使用 `referenced_original_tdr_not_copied`。旧复制模式完整冻结在 `revisions/copy-payload-r1/`，当前入口不接受该模式。

`audit_fields.py` 提供：

- `source_provenance(run, project=None)`：只读核验原始 solver manifest、inputs/results tar、串行运行证据、输入合同、完整曲线及注入窗口帧；返回 `(manifest, proof)`，不创建文件。
- `prepare(run, label, project=None)`：由唯一调度者显式调用，在一个尚不存在的 `local_runtime/dram-see-v4/transport-probe/inputs/<label>` 创建原生后处理输入，返回帧数、TDR 字节数及最大帧字节数。不提交作业，不接受覆盖重提。
- `collect_receipt(operation)`：独立核验无 TDR payload 的原生操作包、四次原始文件哈希及文件/目录身份后，创建本三维修订专用 receipt，不调用旧复制模式收集器。
- `audit(run, extraction, project=None, output=None)`：只读原始 solver/operation 归档。`output` 若给出，必须是本修订 runtime 下的新目录；保存 `audit.json` 与完整 `frames.csv`。失败也保留已取得证据，缺失值写空值而非实测零。

CLI 与同名函数一致。后处理沿用已有 `transport-probe/operation.py` 和共享锁，由 root 调用；成功后由 `audit_fields.py collect <operation_path>` 生成 `dram-see-v4-native-field-reference-receipt-3d-r1`；不要调用旧 `stage2/collect_field_audit.py`。本实现独立重核退出码、归档哈希、执行输入、原始 TDR 全组前后与逐帧前后四次哈希和 receipt，而不把 receipt 存在当作通过。

## 原生观测与独立期望

SVisual W-2024.09 私有用户指南第 237、309–310、331、339、426 页已本地核验：`create_field` 支持三维字段，`integrate_field` 支持三维体积，六参数窗口为 `xmin ymin zmin xmax ymax zmax`；`load_file` 支持绝对路径与显式 dataset 名；`probe_field` 支持三维坐标，默认按指定坐标插值。原指南及核验来源 SHA 保留在忽略的 `local_runtime`；详细 API 核验记录为该目录下 `native-api-readcheck-reference-r2.json`（初版核验档仍保留）。这只证明接口文档支持，真实三维命令执行需待 A0/A1 验证。

每帧提取 `G`、`XG`、`YG`、`ZG`、`ONE`，在完整硅域、旧九分区沿 z 延展的体积、两个 z 半域和中心矩形观测管内积分。中心管为 x=0.395–0.455 µm、z=−0.03–0.03 µm、完整硅域高度；其半宽取注册源宽度 0.03 µm，不将矩形观测管误称圆柱源。

生成量换算只有 `∫G dV[µm³] × 10⁻¹² × e × 10¹⁵`，没有二维有效厚度或 `AreaFactor` 因子。A1 独立闭式期望采用有限 y 径迹和横向 `exp(−r²/w²)/(πw²)`，时间高斯的标准差为 `s_hi=2 ps`。分区电荷、xyz 一阶矩、时间中心及 BE 区间平均波形分别验收，不拟合振幅、不重归一裁剪量。

所有注入窗 `gstep` 原始帧必须逐一关联已接受 BE 步、原始 Writing 记录与完整精确 PLT 时间，窗口步长不大于 0.5 ps。不根据文件序号推断时间，不稀疏插值。窗口起点状态仅保留为边界证据，不重复积分。TDR 内部时间戳未直接解码的边界持续明确标记。

A0 若存在 G，核查其所有空间积分及矩为实测零；若字段不存在，仅保存 `structural_zero_not_measured_zero`，`measured_window_charge_fC=null`，同时继续核验原生 ONE 体积与 XYZ 范围。A1 缺 G/任一矩/任一帧立即拒绝。

## 原始文件引用与几何证据

Tcl 仅通过冻结 `source-directory.txt` 中的绝对目录与登记的简单文件名读取原始 TDR。全组开始/结束及每帧读取前/释放后各进行一次真实 SHA256 校验，同时保存设备号、inode、字节数、mtime、ctime、模式和完整父目录身份链。拒绝符号链接、非规范路径、目录或文件替换、哈希漂移、缺帧和重复记录；四次校验必须与本地完整 solver archive 的同一成员一致。操作包若含任何 TDR payload 即拒绝，不删除任何原有数据。共享锁与已完成原作业的不可变约定继续生效。

首个登记帧另提取九个 `DopingConcentration` 原生点，保存为 `geometry-probes.csv`：source=(0.1,0.02)、drain=(0.75,0.02)、bulk=(0.425,0.6)，各取 z=−0.4、0、0.4 µm。要求源漏三点均正、bulk 三点均负，各组 `(max−min)/abs(z=0值) ≤ 1%`。这是固定诊断工程门槛；缺字段或测点拒绝，不能代替工艺参数校准。接触面积与实际三维网格仍由 root 独立核查。

## 成本与验收边界

每个有源帧为 65 个积分和 6 个坐标极值命令，共 71 个数值命令。A0 缺 G 时为 13 个 ONE 积分加 6 个极值，共 19 个；首帧另加九次掺杂 probe。逐帧释放 plot 后释放 dataset；脚本核对实际删除对象名，避免长任务保留全部场对象。

准备输出的字节计数用于唯一调度者的存储预检与后处理预算，不保证按二维吞吐线性推算三维耗时。原始求解 TDR 永不修改或复制，原生脚本直接只读加载已验证的绝对路径。后处理新增 TDR payload 占用为零，四轮哈希读取量为原始 TDR 总字节数的四倍，不能忽略其机时成本。具体公式见 `postprocess-cost-contract.json`。本地完整 solver archive 和远端原始求解目录全部保留，优化仅消除重复后处理 payload。

场审计不宣称匹配 A0 电路验收、网格收敛、器件校准或核次级耦合通过。root 需结合三维器件状态、独立端电流及匹配 A0，决定 A1 是否整体放行。

## 本地验证

`python -B experiments/dram-see-v4/source-field-audit-3d-r1/test_audit_fields.py`

覆盖真实 builder 合同兼容及完整输入绑定、理想三维解析样例、A0 缺字段/实测零区别、总量正确但错误 z 平铺、z 偏移、错误时间与振幅、缺帧/重复帧/失败步、超过时间步上限、缺 ZG、非有限数、重复沉积、错误体积/第三维范围、坏 tar、未知退出码及重复准备请求；新增四阶段哈希/身份链、替换路径与 inode、目录链接、已重新打包的伪造哈希、意外 TDR payload、无 payload receipt 全链路、九点掺杂与 1% 门槛。所有样例明确为合成测试，不提升成原生结果。
