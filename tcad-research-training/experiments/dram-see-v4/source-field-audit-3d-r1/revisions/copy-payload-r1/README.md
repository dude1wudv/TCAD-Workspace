# 三维原生场审计 r1

只服务已冻结的三维人工 A0/A1、bit1、主网格。这里没有求解器调度、SSH、训练、真实事件导入或二维降维入口。完整三维核事件仍属于后续里程碑。

## 接口

`audit_fields.py` 提供：

- `source_provenance(run, project=None)`：只读核验原始 solver manifest、inputs/results tar、串行运行证据、输入合同、完整曲线及注入窗口帧；返回 `(manifest, proof)`，不创建文件。
- `prepare(run, label, project=None)`：由唯一调度者显式调用，在一个尚不存在的 `local_runtime/dram-see-v4/transport-probe/inputs/<label>` 创建原生后处理输入，返回帧数、TDR 字节数及最大帧字节数。不提交作业，不接受覆盖重提。
- `audit(run, extraction, project=None, output=None)`：只读原始 solver/operation 归档。`output` 若给出，必须是本修订 runtime 下的新目录；保存 `audit.json` 与完整 `frames.csv`。失败也保留已取得证据，缺失值写空值而非实测零。

CLI 与同名函数一致。后处理沿用已有 `transport-probe/operation.py` 和共享锁，由 root 调用；成功后继续复用 `stage2/collect_field_audit.py` 生成 `dram-see-v4-native-field-extraction-receipt-r1`。本实现独立重核退出码、归档哈希、执行输入、原始 TDR 前后哈希和 receipt，而不把 receipt 存在当作通过。

## 原生观测与独立期望

SVisual W-2024.09 私有用户指南第 237、309–310、426 页已本地核验：`create_field` 支持三维字段，`integrate_field` 支持三维体积，六参数窗口为 `xmin ymin zmin xmax ymax zmax`。原指南及核验来源 SHA 保留在忽略的 `local_runtime`；详细 API 核验记录为该目录下 `native-api-readcheck.json`。这只证明接口文档支持，真实三维命令执行需待 A0/A1 验证。

每帧提取 `G`、`XG`、`YG`、`ZG`、`ONE`，在完整硅域、旧九分区沿 z 延展的体积、两个 z 半域和中心矩形观测管内积分。中心管为 x=0.395–0.455 µm、z=−0.03–0.03 µm、完整硅域高度；其半宽取注册源宽度 0.03 µm，不将矩形观测管误称圆柱源。

生成量换算只有 `∫G dV[µm³] × 10⁻¹² × e × 10¹⁵`，没有二维有效厚度或 `AreaFactor` 因子。A1 独立闭式期望采用有限 y 径迹和横向 `exp(−r²/w²)/(πw²)`，时间高斯的标准差为 `s_hi=2 ps`。分区电荷、xyz 一阶矩、时间中心及 BE 区间平均波形分别验收，不拟合振幅、不重归一裁剪量。

所有注入窗 `gstep` 原始帧必须逐一关联已接受 BE 步、原始 Writing 记录与完整精确 PLT 时间，窗口步长不大于 0.5 ps。不根据文件序号推断时间，不稀疏插值。窗口起点状态仅保留为边界证据，不重复积分。TDR 内部时间戳未直接解码的边界持续明确标记。

A0 若存在 G，核查其所有空间积分及矩为实测零；若字段不存在，仅保存 `structural_zero_not_measured_zero`，`measured_window_charge_fC=null`，同时继续核验原生 ONE 体积与 XYZ 范围。A1 缺 G/任一矩/任一帧立即拒绝。

## 成本与验收边界

每个有源帧为 65 个积分和 6 个坐标极值命令，共 71 个数值命令。A0 缺 G 时为 13 个 ONE 积分加 6 个极值，共 19 个。逐帧释放 plot 后释放 dataset；脚本核对实际删除对象名，避免长任务保留全部场对象。

准备输出的字节计数用于唯一调度者的存储预检与后处理预算，不保证按二维吞吐线性推算三维耗时。原始求解 TDR 永不修改；脚本只读取后处理目录中的副本。

场审计不宣称匹配 A0 电路验收、网格收敛、器件校准或核次级耦合通过。root 需结合三维器件状态、独立端电流及匹配 A0，决定 A1 是否整体放行。

## 本地验证

`python -B experiments/dram-see-v4/source-field-audit-3d-r1/test_audit_fields.py`

覆盖真实 builder 合同兼容及完整输入绑定、理想三维解析样例、A0 缺字段/实测零区别、总量正确但错误 z 平铺、z 偏移、错误时间与振幅、缺帧/重复帧/失败步、超过时间步上限、缺 ZG、非有限数、重复沉积、错误体积/第三维范围、坏 tar、未知退出码及重复准备请求。所有样例明确为合成测试，不提升成原生结果。
