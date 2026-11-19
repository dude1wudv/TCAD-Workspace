# S2 α 源与全帧场审计适配

状态：**离线实现并完成针对性检查，未执行 SDE/SDevice/SVisual、Geant4、PMI 编译或训练；未获得原生资格。** 首 4 角色仍只有 D2、D3、A0-bit0、A0-bit1。此目录没有求解器启动入口，旧预算与失败原档未改。

## 输入与实现

- `alpha.py::prepare_audit(model, output)`：只向新目录/不存在的文件写入可审查材料，既有文件不覆盖。输出 `source-contract.json`、`alpha-reference.json`、`field-contract.json`、原始 101 节点 `alpha-profile.csv`、未来 `heavyion.physics.inc`/`source.par`、H/Z/split/A0 片段、`heavyion.currentplot.inc`、`heavyion.plot.inc`、`extract_fields.tcl` 与窗口数据。片段没有加入首 4 角色的源配置。
- `source_spec(case, bit, variant)`：显式接受两个 bit。case 为 A0/Aalpha/Z/H/split；main/mesh/time 仅对 A0/Aalpha 完整提供。bool 不被当作 bit，其他能量、角度、尺寸、位置和核参数拒绝。主线 A0 可直接保存 `source_spec('A0', bit, 'main')` 为 `source-spec.json`。
- `source_expected`：使用与 CAD 实现独立的积分代码，扣去实际 STI 和圆底门槽；x/y 为截断 Gaussian 解析积分，z 按 LET 节点和材料界面分段积分，圆底转换到角变量。四组重叠观察窗与三个不交分区独立保存。`cad_binding` 绑定 CAD 描述、Si 体积及 1584 个非界面 mask 点。CAD 是精确圆/圆柱构造，故没有多边形圆弧误差；实际网格误差仍未知。
- `field_audit.py`：独立提供源时钟/全帧索引、CSV 解析与数值门；`audit_native` 是只读原生证据入口。纯函数和离线 fixture 始终 `is_tcad_result=false`、`native_qualified=false`，不能产生 native receipt。原生入口没有 receipt 时明确拒绝。

保留旧三维 oracle 的时间质量积分/BE 平均语义，保留旧审计的日志打印精度匹配、原档四阶段 SHA256/目录身份核对、逐帧释放方式。旧源仍是旧几何/人工源；没有修改或把其资格搬到 S2。

## 离线数值

固定条件：S2；5 MeV 到达本地 Si 表面；正 z；(-52,0,0) nm；w=50 nm；sigma=0.2 ps；t0=15 ns；z=0..1 µm；101 个沿程节点。

| 项目 | 独立参考 |
|---|---:|
| 未截横向核的 1 µm 线电荷 | 6.468053411906473 fC |
| 实际 Si 域电荷 | 5.5655251969279975 fC |
| STI/槽等非 Si 排除量 | 0.9025282149685312 fC |
| 外边界尾量 | 9.944045586962602e-12 fC |
| ±8sigma 观察窗外时间尾量 | 6.796871639537014e-15 fC |
| 独立实际 Si 体积 | 0.9599273161065788 µm³ |
| 截断后 xyz 质心 | (-0.05218253358134679, 0, 0.5669214488541812) µm |
| 1 µm 后 α 出口能量 | 4.854552996403458 MeV |

时间尾量由双精度 CDF 计算，极小尾量最后几位受浮点舍入影响。积分容差收紧后的总电荷差在双精度输出中为 0；这不等于物理不确定性或积分误差严格为零。没有将任何丢失量重新加回 Si，没有把出口能量当成本域漏记源量。

## 原生审计准入与边界

`audit_native(solver, extraction, package)` 只处理 **3D 瞬态**；不把 DC 的稳态数据冒充源窗口帧。以下原生协议需要后续发布时由唯一主调度器填写和保存，本轮没有这些事实或 receipt：

1. 完整 solver `manifest.json/inputs.tar/results.tar`、`native-source-receipt.json`；完整 extractor `operation.json/results.tar/field-extraction-record.json`。两个 receipt 分别使用 schema `s2-native-source-receipt-r1` / `s2-native-field-receipt-r1`，绑定原始 manifest/archive hash、真实 SSH/远端/归档/native 退出码、工具版本、bit/case/数值变体、CPU affinity、线程/核数及共享锁原始证据。只写一个宣称通过的 JSON 不足以通过。
2. 原始 solver 归档内须有发布单 `execution-release.json`、预算引用、`geometry-manifest.json`、实际网格及绑定 hash、完整 `source-spec.json` 和审查材料；激活的源 include/参数片段必须与对应 case 的冻结文件一致。A0 必须没有激活的 HeavyIon 源。
3. 原始源窗 `source_window*.tdr` 全集合与提取输入 `tdr-files.txt/tdr-sha256.txt/source-directory.txt/source-case.txt` 严格对应；SVisual 只读原路径，不复制或修改 TDR。原档 GROUP_BEFORE/FRAME_BEFORE/FRAME_AFTER/GROUP_AFTER hash、lstat 文件和目录链身份必须一致。
4. 全 0..25 ns 原始 BE 接受日志必须与精确 PLT 接受时间一一对应；源窗每个接受端点及初始边界帧均保存。拒步保留。不能用文件序号、期望网格或插值生成时间。重复分段初态行仅在 G 相同的同时间情况下明确合并。原生 TDR state 元数据在旧证据中没有可靠物理时间，故一直保留 `direct_TDR_timestamp_verified=false`，时间由原始 Writing/PLT/hash 绑定。
5. 每帧 `ONE/G/XG/YG/ZG` 对实际 Si、全部分区和观察窗比较；原生 Total 窗与无窗 Si 双核对，时间函数使用实际 BE 区间平均。全量/波形/分区 5%、份额绝对差0.05、空间2nm、时间0.04ps、完整帧要求均沿用 r13，没有放宽。
6. A0/Z 缺 G 记 `structural_zero_not_measured_zero`、实测 Q 为 null；存在则所有窗口的 G/矩严格为零。源字段通过仍不是独立端电流 KCL、匹配 A0、网格/时间收敛或商业模型校准通过。KCL/电学指标由主线单独实现，不能从相同 CΔV 自证。

Native receipt 协议的真实运行采集、完整 native archive happy path、新模型 SVisual API/语法、源首节点/有限终点/split 端点以及 BE 字段语义尚未进行原生验证；执行前必须纳入对应发布与预算。不能把 parser 存在说成运行资格已通过。

## 本轮检查与保留记录

本轮工作目录下 `local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/alpha/` 保存全部本任务产物。

- `prepare-r1-failure.txt`：首次准备因 CAD y=0.060000000000000005 与独立 .06 的直接浮点等号拒绝；改为仅 1e-15 µm 的数值表达一致性比较，科学门不改。原失败保留。
- 离线检查首次运行因脚本根目录 `parents[6]` 多上溯一级而退出1；随后纠正为 `parents[5]`。此是测试路径错误，没有求解或 native 数据。失败说明见 `offline-attempts.txt`。
- `offline-check.py r2`：退出0，35项针对性检查；原始 ASTAR 表积分、Si 体积/分区、CAD mask、BE 质量一致性、bit0/1 的 Aalpha/H/split 和 A0/Z 缺字段语义，以及漏BE/漏TDR/漏G、错误分区/Total/质心、外包盒代Si、不支持输入、重复G矛盾、缺receipt及伪receipt缺原档的反例。报告 `offline-check-r2.json`，日志 `offline-check-attempt3.log`。
- 合成 fixtures 明确位于 `UNIT_FIXTURE_*_NOT_NATIVE*`，仅测试拒绝路径/数值函数；没有 TDR、真实运行曲线、资格报告或原生执行。
- 最终审查材料由 `prepare_audit` 新生成到 `review-r3`；主线整合包应再次生成并冻结自己最终代码/输入 hash，不能把中途 review-r2 的代码 hash 当作最终版本。

新增原生/提取/编译/训练调用均为0；无 SSH、安装、Git 网络、对外消息、旧预算或失败原档改动。
