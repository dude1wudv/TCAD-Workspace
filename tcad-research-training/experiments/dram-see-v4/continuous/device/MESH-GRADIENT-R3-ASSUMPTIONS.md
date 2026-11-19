# 三维梯度网格 r3：实现前声明

版本 `dram-see-v4-gradient-mesh-r3` 是未经原生精度验证的新数值候选。原 r1/r2 定义、实现、假设和全部冻结输入/失败归档保持原字节。新策略仅替换 r2 的 `GateOxide` 与 `InterfacesActive`；原掺杂 x/z 分辨率、全 y 混合带、源柱、两接触和远界面均保留。物理几何、模型、源核、求解器、148 条测量及全部容差不改变。

**真实依据**

D3r5 原 snmesh/remote 退出 137，kernel 明确 OOM kill 原 PID 59794，anon-rss=15,295,480 kB。归档 SHA256 为 `e9dafa1f0b40ed73d628eb0d9f045d229f3da8b31ab1369009d8326822c5b795`，SDE=0、SSH/collection=0、collection_verified=true，DC 未开始。原命令 SHA256 为 `141b299903514cc37900db603b3a5b6858a370f75e5589145e30c946a5394cbc`；其中唯一显式 1/1/1 nm 体积规则是整个栅氧化物包围盒，包含厚顶盖。局部 `MaxLenInt` 为标量 1 nm，没有独立规定法向和切向尺寸。

原日志还报告 12,192 个 non-Delaunay elements、1,226 个 non-Delaunay boundary faces；最差边界面在远 STI，超出本次局部窗口。因此本候选不能被称为全部质量异常的修复。原报告与精确候选：`local_runtime/dram-see-v4/continuous/device/mesh-r5-density-analysis-r1/REPORT.md` 和 `analysis.json`。该分析的前 11 个族被采用，后三个接触拆分备选不采用。

**几何派生的数值分区**

所有数值使用 µm。以下为当前 S2 的 nm 展示值；实现从实际 `outer_trench`、`gate_void`、`sti` 和 `nominal_oxide_um` 派生，不把 gate=80 固定进窗口。支持既有 gate=70/80/90 nm、SN=82/87/92 nm；SN 仍进入原掺杂模型及测量期望，不因网格策略修改。

记侧氧化层厚度为 t（当前 4 nm），padding=t/4（1 nm），真实交角半宽=t/2（2 nm）。栅顶窗口随真实 gate.top 移动；其余边界随各自物理对象移动。STI 窗口分别与 `R.Silicon`、`R.STI.minus`、`R.STI.plus` 相交，排除 `R.Trench`，不沿不存在的平面穿过沟槽。

| 窗口族 | S2 实际物理窗口，nm | 最大 x/y/z，nm |
|---|---|---|
| GateEnvelope | x±13，y±61，z0–155 | 5/5/5 |
| GateSideNormalX | x[-13,-7]/[7,13]，y±61，z0–143 | 1/5/1 |
| GateBottomCurveXZ | x±13，y±61，z138–155 | 1/5/1 |
| GateTopNormalZ | x±9，y±57，z72–82，即 gate.top−2t 至 gate.top+t/2 | 5/5/1 |
| GateEndNormalY | x±13，y[-61,-55]/[55,61]，z72–155 | 5/1/5 |
| STISideNormalYCore | x±100，四个真实 STI y 面各±t，z0–204 | 5/1/5 |
| STISideNormalYTransition | x±100，四个真实 STI y 面各±3t，z0–212 | 5/2.5/5 |
| STIBottomNormalZCore | x±100，真实 STI y 区间各扩 t，底面 z±t | 5/5/1 |
| STIBottomNormalZTransition | x±100，真实 STI y 区间各扩 2t，底面 z±3t | 5/5/2.5 |
| TrenchSTISideCorners | 真实沟槽 x 面、内侧 STI y 面交线各±t/2，z0–143 | 1/1/1 |
| TrenchSTICurvedCorners | x±13，内侧 STI y 面各±t/2，z138–155 | 1/1/1 |

厚氧化物均匀切向区域采用较粗步长是新数值假设，尚无 3D 场证明误差足够小。4 nm 氧化层法向、圆底 x-z 曲率、有限 y 端部和真实交角保留细化。不是按探针位置贴补，也不按目标节点数/内存倒推。h/2 保持同一物理分区，全部新旧 max/min/interface 步长同比减半；最小尺寸仍为相应最大尺寸的一半。所有旧 model.numerics 保持原 S2 基线，实际变更由独立 mesh-policy 合同和原始输入清单说明。

**原生 Delaunizer 的有限整数参数**

原 r5 报告 `Exceeded the maximum number of vertices (500000 vertices)`，随后说明最终网格可能不满足 Delaunay。SMesh W-2024.09 UG p53 定义 `Delaunizer.maxPoints`，默认 500000，在 ridges recovered 后检查。SDE 同版 UG p791 给出 `sdesnmesh:delaunizer` 的直接设置接口；p572 给出 refinement window/region 的交集语法。

仅 r3 显式设置 `(sdesnmesh:delaunizer "maxPoints" 2147483647)`，在原 `sdedr:write-cmd-file` 之前生效。2147483647 是正 32 位整型上界，用于避免默认 500000 提前截断质量细化；它仍是有限原生算法参数，不是项目资源预算、预测额度或无穷，也不是物理验收标准。此参数不随 h/2 减半。保留默认 `boxmethod`、Delaunay tolerance、sliver、smoothing 和所有其他算法设置；不使用未文档化的 0/-1、不改 OS/VM 资源。实际 SDE 输出与运行行为仍须首个新原生作业验证。

厂商文档本地证据位于 `local_runtime/dram-see-v4/continuous/device/mesh-r5-density-analysis-r1/manual-sde-delaunizer-api-pdf-p0791-private.txt`、`manual-sde-region-window-api-pdf-p0572-private.txt`、`manual-smesh-maxpoints-pdf-p0053-private.txt`；交付记录保留原字节 SHA。原 PDF 在 `local_runtime/dram-see-v4/three-dimensional-pilot-r1/references/`。

**未验证边界**

共形边界、默认平滑和质量恢复仍可能传播细化或增加节点。更高 maxPoints 也可能增加实际资源使用，不承诺节点数、内存、退出或精度成功。继续要求真实退出、完整最终网格质量、原几何/掺杂测量、DC、两 bit 写读、KCL、源场/双载流子/实际 BE 时钟和同策略 h/2；A0/信号只能继承实际成功 D3 的原网格与 policy，输入生成不等于原生资格。
