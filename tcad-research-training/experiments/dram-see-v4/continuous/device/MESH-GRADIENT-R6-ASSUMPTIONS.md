# 三维梯度网格 r6：实现前声明

`dram-see-v4-gradient-mesh-r6` 是独立数值候选，未取得真实 mesh、DC、A0、粒子场或 h/2 资格。仅替换 r5 的13个掺杂窗口并调整三个源柱核心的横向步长。旧 r1–r5 实现、定义、请求、冻结 D3 r8 及所有失败证据保持原字节；原六步串行链、物理/求解器、几何、源核、148项测量及全部容差不变。真实触发是原 r8 的 kernel OOM137 且没有完整网格；不按节点或内存目标倒推参数。

掺杂采用 `local_runtime/dram-see-v4/continuous/data/doping-mesh-error-analysis-r3/candidate-SN87-coarsening-only.json` 原144107字节，SHA256 `3e6a7e34522a3be0c000874c92f1d7dda87ab174b8686193100245a135449cf1`，完整嵌入新定义。报告 SHA256 `0b0561e1c9b9fb3189e87937734f789894489b61b0a567cf82bc33f7d51c3eec`，handoff SHA256 `97bab9eec1a778a92098489eddb200e841f621eeafe5aa25e393df9c78063a98`。99个放置包括75个 `NEW_HESSIAN_BOUNDED_COARSENING`、23个 `INHERITED_ACTUAL_R5_NO_NEW_CERTIFICATION`、1个 `CoreYSupport` 保持原有效 y 约束；不合并证据类型，不采用另存的164窗或0.5nm细化建议。

13个旧掺杂窗口全部移除；新窗口保持原物理覆盖与 Silicon 掩膜，每个方向的有效 max/min 均不比原 r5 更细。使用机器表提供的十进制 µm 值，保留原 nm、单位、逐区证据和继承标识。名义尺寸不证明实际 tetra 投影跨度/完整支撑域；Hessian 是 binary64 数学分析，不是有向舍入区间证明。23个继承区没有新精度认证。SN 仅支持87nm；SN82/92拒绝。gate70/80/90仍由实际几何派生，不能改变最终留出标签。

源柱只改 `AlphaTrackNearCore/BulkCore/EndCore` 的横向 max 5→10nm、min 2.5→5nm；原2w边界、纵向 max 5/20/5nm、纵向 min 2.5/10/2.5nm、外4w三窗及所有叠加规则不变。源 w=50nm、位置、符号、单位、尾部和归一不变，不截尾、不拉伸 LUT、不把50nm alpha核当作30nm质子核。

源依据是 `local_runtime/dram-see-v4/continuous/proton/alpha-source-mesh-spacing-analysis-r1/candidate-recommendation.json`，SHA256 `0131e202d37c48d8e70569052d11222506570ed19a3e00518156eb7f1ff04bfa`；报告 SHA256 `b1bfdeb36fefbb5eabe3f51023fdb37e08201c5f56bd9130c16e0820fe7a5789`，handoff SHA256 `90620c3da6884a5dce5ad2536c66f1743f0c1773322f3089a93013fef9ae9ac0`。条件空间总电荷界0.2544455426878fC已含 outside4w/All40nm 尾项0.0001569205112fC和纵向 LUT 项0.0020134647576fC。仅当前 gate80/SN87/5MeV法向源适用；要求实际正重心单元、真实材料/端面分域及窗内/跨界单元 xy 跨度≤10nm。17个ROI、2nm质心与矩、时间/电学 h2、PDE响应仍未验证；gate70/90输入生成不扩展该证书，质子任意次级及斜射也未证明。

r5分段侧面、圆底/顶部保护、接触、STI、远界面、默认 boxmethod/权重/接口、Delaunizer全部保持。`maxPoints` 请求2147483647与已观察 SDE literal `2.14748e+09`（2147480000，差−3647）分别记录，既不称精确一致，也不称无穷或物理验收。

main/h2 固定全部物理边界，所有新旧 max/min/interface first_step 同比减半，整数算法参数不缩放。A0必须继承真实成功 D3 的原 policy 和同一实际网格；离线继承检查不伪造 producer 成功。本次只交实现、必要聚焦检查和 prepare 命令，实际 ID、输入冻结、审核和唯一原生提交由主代理负责。
