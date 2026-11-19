# 三维梯度网格 r4：实现前声明

`dram-see-v4-gradient-mesh-r4` 是独立、未取得原生精度资格的数值候选。r1/r2/r3 实现、定义、假设、冻结输入及全部失败原档保留原字节。本次只改变原 α 源柱的横向离散，不改变其物理源、范围、纵向分区、器件模型或验收标准。

**真实异常与已有证据**

D3r6 为 `FAILED_COLLECTED`：SDE=0、snmesh/remote=137，kernel 明确 OOM kill 原 PID 64918，anon-rss=15,399,680 kB；归档 1013760 bytes，SHA256 `3a5b0ad1525f58d4848a3adb620c17f5da1bdc5c8c07ee34bf31d02878b09db1`。日志终止于 Assign regions，DC 未开始。此前 faces 阶段有 3,715,097 vertices、22,198,553 elements；non-Delaunay 元素/边界面/ridge 均为 0，无默认 500000 告警，slivers remaining=31。这是实际阶段质量改善，不是完成 mesh 或 r3 合格证明。

原保留窗口分析位于 `local_runtime/dram-see-v4/continuous/device/mesh-r6-retained-density-analysis-r1/REPORT.md`。原 4w 源柱 Si 体积约 0.1519273161 µm³，2w 核心约 0.0359273161 µm³；原源柱还将 0.002 µm³ 的远 y Blend Si 带约束到 y=5 nm。体积是解析覆盖证据，不是节点归因或资源预测。原真实 D2 掺杂误差继续支持保留 x/z=1 nm；不按目标节点数、内存或失败预算选参数。

**唯一离散变化**

源轴与 w 从当前实际模型及其原 `AlphaTrack` 4w 几何核对、派生，不硬编码另一中心。当前 S2 原轴为 (−52,0) nm、α 横向 w=50 nm。

| 分区 | S2 横向物理范围 | 最大 x/y，nm | 原 z 区间与 z 最大尺寸 |
|---|---|---|---|
| 原完整 4w 背景 | x[−252,148]，y[−200,200] nm | 10/10 | Near: 0–250/5 nm；Bulk: 250–980/20 nm；End: 980–1000/5 nm |
| 新增同轴 2w 核心 | x[−152,48]，y[−100,100] nm | 5/5 | 与对应原深度段相同 |

两者均与 Silicon 相交；重叠处保留更细核心。原 4w 范围不缩小，源在完整物理域内照常评估；无尾截断、源电荷拟合或重归一。全部其它 r3 窗口、界面、原接触、ActiveDoping/Blend、All/Junction 原样保留。main/h2 使用同一物理分区；全部新旧 max/min/interface spacing 同比减半，min=对应 max/2。有限 Delaunizer 整数参数不是空间步长，不随 h2 缩放。

自由平面 Gaussian 的 ±2w 方框含 erf(2)²≈99.0666% 的横向质量，可支持连续核心/外层的候选选择，但不等于有限 Si 份额或 ROI/电学误差界。外层尾量继续按原判据审核，不因小而丢弃。

这是当前正入射 α 柱的离散候选。固定质子核是 w=30 nm 的三维 Gaussian 段卷积，零弦长也保留该点核；其约 2.5 nm LET 采样不是物理核宽。原固定 α 柱、Bulk z20 nm 与 All40 nm 均未证明覆盖任意质子次级或斜射源。未来必须用真实完整源包、原全 Si/ROI 场、双载流子、实际时钟与 h/2 判断；本次不引入事件裁剪、源核变化或伪造通用覆盖资格。最终留出结果不用于选此网格。

**Delaunizer 请求与真实序列化观察分开保留**

继续原 SDE 调用 `(sdesnmesh:delaunizer "maxPoints" 2147483647)`，其它参数保持默认 boxmethod 与原质量设置。2147483647 是有限正整数上界，不是项目资源预算、无穷或精度标准。

r6 的实际 `cell.cmd`（SHA256 `50dcaab38f02ba9abad9f5e233b606cf09e92a9c2973fbabb81026fc3ffce346`）输出 `maxPoints=2.14748e+09`，字面量精确数值为 2147480000，比请求少 3647，精确一致为 false。原断言失败和原档保留。r4 仅将此作为明确的先前运行观察记录，不改旧输出、请求或误标为当前运行实测；新运行的真实序列化仍须核对。不引入未文档化 0/-1，不改 OS/VM 或 constrained 模式。

物理四文件、模型/源核、DC 求解器、全部 148 条测量位置/期望/容差均保持。新 A0/信号只可继承实际成功 producer 的原 mesh 和 policy；本次输入准备不生成成功证据。后续仍要求最终原生退出/网格质量、DC、两 bit 写读/KCL、源场/时钟/响应以及全尺寸 h/2；不承诺节点数、内存、精度或执行成功。
