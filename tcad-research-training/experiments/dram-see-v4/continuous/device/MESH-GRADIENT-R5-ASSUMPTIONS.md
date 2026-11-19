# 三维梯度网格 r5：实现前声明

`dram-see-v4-gradient-mesh-r5` 是新数值候选，尚无原生网格、DC、电学或粒子源精度资格。仅替换 r4 的四个全深掺杂窗口和六个全高平直侧面/直边窗口；旧 r1–r4 实现、定义、请求、冻结输入及失败原档保持原字节。原六步单核串行链、物理模型、源、求解器、148 项测量位置及全部判据不变。

真实触发是 D3 r7 的 snmesh 137 / kernel OOM；原 SDE 退出0，但没有完整 `cell_msh.tdr`。归档 SHA256 `95c53b779c5cba3a88aa9b27a37901af71c21a06d008acdd6896b286b3f61cd3`。此处不以节点、内存或时间目标倒推网格，也不将内存中的质量报告当成功网格。

**掺杂分区。** 采用 `local_runtime/dram-see-v4/continuous/data/doping-mesh-error-analysis-r1/candidate-partitions.json` 的13个矩形，原字节 SHA256 `04b2a4d3782456dcbaeb82537aae1473642c71078f47bb06079ce877dab776dc`。定义文件嵌入这份原 UTF-8 文本及哈希，使重建不依赖运行时可变的分析目录。物理输入限定 SN87 nm、BL137.5 nm、donor peak 1.45e20 cm^-3、acceptor 1e17 cm^-3、tanh blend 5 nm；SN82/92 明确拒绝，不沿用未覆盖的分区。

四个旧窗口 `ActiveDopingCore/Left/Right/BlendFullWidth` 必须移除，避免旧1nm约束覆盖新候选。新矩形完整覆盖各原窗口，继续只作用于实际 Silicon。浅层/侧翼边界来自 aSN/√2、aSN、2aSN、√2aBL、4aBL，混合侧翼界限来自−8倍原blend；深尾粗区保留5nm保护带。没有围绕探针单点加窗、改公式、改容差或截断掺杂。

完整 Hessian 含 xz 交叉项的数学分析是选区依据，不能保证名义 MaxElementSize 等于实际 tetra 的投影跨度。深尾绝对门推理还要求实际插值单元留在已界定区域。原1nm区只是保留历史基线，不因保留而获得新精度证明；最终仍以原2%/1e8 cm^-3等各项门及实际mesh审计判断。

**平直几何分区。** 只读依据是 `local_runtime/dram-see-v4/continuous/device/mesh-r7-directional-residual-review-r1/REPORT.md`，SHA256 `32ab79405511f39cd31691112e2b3fc85f1567fc671424b6ccc89cd78d00886a`。原 `GateSideNormalX{1,2}` 的 x/y 范围保持，在平直 z 中段用 max `[1,5,5] nm`；原 `TrenchSTISideCorners{1..4}` 的 x/y 范围保持，在平直交线中段用 `[1,1,5] nm`。其余 z 带保留原 `[1,5,1]` / `[1,1,1]`。

令 t 为实际侧氧化层厚度、g 为实际栅顶、zc 为实际圆底中心：两个可调整区为 `[t/2,g−2t]` 与 `[g+t/2,zc−t]`。保护区为外表面 `[0,t/2]`、栅顶 `[g−2t,g+t/2]`、圆底衔接 `[zc−t,zc+t/4]`。当前 gate80/t4/zc142 nm 对应 z2–72、82–138 nm；gate70/90 从同公式派生。沿用旧几何比例，不采用留出响应选择参数，不改任何 split 标签。

平面/直线挤出几何只支持“切向曲率为零”，不能等价为电势/漏电/BTBT收敛。顶部、圆底、有限 y 端面、三面交点及源漏接触的原细窗口均保留，Silicon 另叠加13个掺杂矩形。实际掺杂与几何约束可能仍支配部分区域，不能用体积比例推算节点或峰值收益。

**保持项与 h/2。** r4 的 All/Junction、原4w源柱/2w核心、STI各方向规则、两接触、远界面与 Delaunizer 完整保持。`maxPoints` 请求2147483647以及历史 SDE literal `2.14748e+09` / 数值2147480000分别记录，不能称精确一致或无穷。默认 boxmethod、权重和接口语义不变。

main/h2 采用同一物理分区边界；全部新旧 max/min/interface spacing 同比减半，min 始终为相应 max/2，算法整数参数不减半。A0 只能继承真实成功 D3 的同一实际 mesh 和原policy，输入函数验证不允许伪造D3成功。

本次先交实现、聚焦检查及可准备命令，不自动冻结 run ID 或运行包。后续必须保留真实退出、完整网格/权重/材料/接触、148项审计、DC与两bit写读、KCL、源场和h2结果，才可判断精度；不得用离线数学或输入通过替代原生资格。
