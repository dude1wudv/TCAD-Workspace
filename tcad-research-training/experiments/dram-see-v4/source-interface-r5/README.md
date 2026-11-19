# r5：完整二维人工源接口输入

本目录只准备输入和解析源量；真实求解、原生场提取及运行计数由 root 调度。旧 r2/r3/r4 文件和失败记录保持冻结。当前模型仍是未校准的 0.25 µm 二维平面单元，不能据此声称三维耦合、位翻转概率或器件校准完成。

## 已登记的实现选择

- 用户已批准 main/time/fine 三组数值条件：`(mesh_scale, pulse_max_step_s)` 分别为 `(0.5, 5e-13)`、`(0.5, 2.5e-13)`、`(0.25, 5e-13)`。它们共用原几何、掺杂、电路及读出时序。`variant` 是显示标签；实际参数独立保存。
- 离线检查发现，冻结 v1 的 `build()` 入口限制 `mesh >= 0.4`，因此 r50 的 `_geometry()` 不能直接生成已批准的 fine=0.25。root 批准 r5 局部适配：只读提取同一冻结 v1 源码中的唯一 `geometry` f-string，校验源码 SHA、AST 结构与依赖白名单后渲染；不修改旧入口或复制另一套几何公式。仅允许 0.5 和 0.25；main 必须逐字等于两份已登记 r4 geometry。fine 必须仅把九项网格长度数值减半，不改变几何、掺杂或网格增长比。
- 物理 source-spec 保留 r2 已登记的人工事件与显式 xyz。时间 oracle 使用 r3 修正的 `sigma=s_hi=2 ps`，没有调用旧 r2 时间公式。
- 旧九个 `CurrentPlot` 窗口继续作为诊断；它们曾返回零，不能独自使源项验收通过。SourceLeft/SourceRight 新增到离线源量及独立原生 TDR 测量，附加门槛仅用于 A5/A6/A7。
- 保留五个原 `gfield` 固定时刻输出，并在注入窗使用 `Plot(FilePrefix="gstep" Time=(Range=(0.95e-9 1.05e-9)) NoOverwrite)`；不加 Intervals、不强制新时间点。固定 project outputs 不用通配符，完整动态帧由原 runner 的全工程 tar 保存；动态帧完整性另行审计。
- A3 规定总量 1 fC，但在硅域中只有约 0.5 fC，不做裁剪后重归一化。A6 左右源中心分别为 1 ns 和 1.01 ns；各 ROI 按各轨迹空间权重计算时间中心。A8 的每段只拥有一次对应电荷和区间，LET 按各段电荷/长度计算；分段网格端点的实际差异需真实比较。
- 历史调用 5 次；本轮最多 21 次，含 17 个 primary 角色和 4 次 reserve，累计上限 26。A0/A1 bit1 main 仅生成离线复用参考，不是新的 primary 请求；若重算必须由 root 使用 reserve。任何未知退出状态不自动重提。

## 接口和命令

生成器提供共享合同约定的 `contract/code_hashes/source_spec/offline_proof/render_deck/check_role/build/check_project`，另提供纯 `render_geometry(variant)`、`expected_common(bit,variant,geometry_sha256)`、`physical_deck(case,bit,variant)`、`strip_observers(deck,case,bit,variant)`，供独立审计核对。

```powershell
python -B experiments/dram-see-v4/source-interface-r5/build_interface.py plan
python -B experiments/dram-see-v4/source-interface-r5/build_interface.py build local_runtime/dram-see-v4/source-interface-r5/inputs/v4-source-interface-r5-a4-b1-main --case A4 --bit 1 --variant main
python -B experiments/dram-see-v4/source-interface-r5/build_interface.py check local_runtime/dram-see-v4/source-interface-r5/inputs/v4-source-interface-r5-a4-b1-main
python -B -m unittest discover -s experiments/dram-see-v4/source-interface-r5 -p test_interface.py -v
```

每次输出目录必须是新目录，已有目录、越界目录、未知角色、非有限/缺失/冲突字段或哈希变化均拒绝。`OFFLINE_INPUT_CHECK_PASSED` 只说明冻结输入及解析台账一致，不是求解或科学验收。A0 不请求未定义的 Coordinates；缺失 HI 字段只能提供结构无源证据，不能伪造实测零场。

## 离线量与复用边界

`offline_proof(spec).rois[roi]` 保留 `q_fC`、逐源 `tracks`（source_name/fraction/q_fC/x_moment_fC_um/y_moment_fC_um/quadrature_error_fC），另保存逐源 time/s_hi 及加权 `time_centroid_s`。A0 的质心和时间中心为 null。11 个窗口全部先验计算；旧九个容差和 5% 总量、2% 细化、1 mV 或 5% 扰动等门槛不变。

contract 的 `reuse_roles` 绑定两份原 r4 run、project、输入与归档哈希、通过审计和原比较；A1 还绑定已通过全帧场审计。原 `mesh` 仅通过明确规则映射为新 `main`，不能笼统忽略版本、实际网格、电路或源项差异。新 fine 比较为 0.5→0.25，各自需要同条件 A0；历史 1.0→0.5 比较不能代替它。

## 离线验证记录

26 项 focused tests 已通过，退出码 0；日志为 `local_runtime/dram-see-v4/source-interface-r5/build-dev/tests-final.txt`。测试实际构建并检查了全部 17 个 primary 和 2 个复用参考的临时输入；覆盖 AST/源码变更及越界网格拒绝、两份 r4 物理字节一致、fine 九项网格长度变化、注入时间步单独变化、A3 半域量、A6 双时间中心、A8 分段归一化、旧九 ROI 保持、源字段/重复输出/重算哈希后篡改拒绝。首轮测试自身错误及修复说明保留在同目录 `tests-first-attempt.txt`，没有修改物理值或放松容差。

稳定交付仅构建 A4/1/main 首个候选和 A0/A1/1/main 两份离线复用参考；其他实际求解输入由 root 按冻结顺序构建。没有调用 solver、SSH、原生 Visual、编译、安装、训练或 Git 提交；真实语法、实际网格、场量及响应须由后续独立审计验收。
