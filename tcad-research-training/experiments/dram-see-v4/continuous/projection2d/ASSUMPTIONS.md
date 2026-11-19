# 二维保守投影：实施前固定的数学与边界

依据：r14-2d/refine-logs/EXPERIMENT_PLAN.md 第3.2、B3、采样设计；原 nuclear-closure-r1/source_kernel.py；continuous/proton/couple.py、source_reference.py、source_bundle.py；真实 nc-r1-h-000 的 steps/tracks/events/birth-links/metadata。这里只新增投影数学和数据适配，不调度任何原生工具。

1. 原 Geant4 输出是有起止位置、起止时间和能量账的逐步沉积，并非已经求得的连续体 G3。现有明确连续重建为：每个正 Si 电子沉积电荷 Q，均匀参数 u∈[0,1]，r(u)=r0+u(r1-r0)、t(u)=t0+u(t1-t0)，卷积归一化 exp(-|r-r(u)|²/w²)/(π^(3/2)w³) 和时间 Normal(t(u),sigma)。w=0.03 μm、sigma=2 ps；3.6 eV/pair。沿程位置与时间使用同一u。零弦长保留为此既定核的点极限，不另增路径或体积。此为既有源模型的数学重放，不是原生 G3 测量。

2. 有效条带 physical y∈[-0.01,0.01] μm，W=0.02 μm=2e-6 cm。响应域为实际二维硅截面的均匀挤出。BCAT截面为有限x/z盒减矩形/圆底外沟槽；GateVoid在外沟槽内，因此仍属非Si。现有BCAT输运几何在这一active条带内与截面一致，STI只在条带外；必须通过实际输入几何比较，不能把旧planar输运冒称BCAT。仅声明材料对应，不声称真实三维电学等价。

3. 对核先解析积分y，再对u积分：G2=(Q_C/e)*1e12/W_um * integral gx_um^-1 * gz_um^-1 * P(y在条带|u) * T_s^-1 du，单位cm^-3 s^-1。与等价厘米公式G2=(1/W_cm)∫G3dy相同。仅在响应Si截面和声明时间窗内输出G2。保留x/z/原t的相关性；不把y直接删除，不使用SDevice 2D的1 μm参考厚度替代原G3。

4. 源账按互斥顺序分解：条带外；条带内但x/z有限盒外；条带盒内非Si；响应Si内但时间窗外；接受的响应Si与时间窗。每个分量独立积分，未归一化；总和与原Si源Q对账，数值残差单列。原非Si材料的沉积保留MeV账，不能套用Si的3.6 eV/pair把氧化物能损改称Si电荷。原Si核的非Si空间尾量另列，不与原非Si沉积混淆。

5. 输入窗为冻结电学/源合同给出的实际时间范围，不能以预计BE时钟代替接受步。原沉积中心或端点在窗外会显式标为需完整时序处理；Gaussian窗外尾量始终保留，不裁掉晚次级，不把保留在窗内的微小尾量当作晚源已完整表示。此模块不产生BE验收通过标记。

6. 输入与输出按原文件SHA绑定；完整选中event的所有step、track、parent、birth-link、原坐标和physical y必须保留。原批次所有event ID及完成状态保留在分母。数学重放只使用事先固定的历史 nc-r1-h-000/event0，不读取响应、不搜索事件、不打开最终留出。该旧planar模型显式坐标置换：old x→physical x，old y(深度)→physical z，old z(宽度)→physical y；不得平移成BCAT。

7. 数值积分使用已固定独立参考的erfc稳定区间和正权自适应Simpson，按核在各域边界的过渡分段；圆底用角变量。归一化绝对/相对设置1e-11/1e-8，四分之一复算；电荷复算/闭合沿用max(1e-6 fC,0.1%输入SiQ)。该门限只作离线算术判据；不代替原5%源场、2 nm保留坐标、0.04 ps时间质心等真实资格。

8. 二维原生坐标为X→physical x、Y→physical z，省略physical y。原生面积积分G单位为cm^-3 s^-1 μm²，乘1e-8*W_cm得到pairs/s；电荷再乘e*dt。原生XG/ZG单位cm^-3 s^-1 μm³，要表示C·cm矩再乘额外1e-4；如报告fC·μm矩，则保持该额外坐标的μm单位。端口电流的AreaFactor和电路电容均不在本模块重复缩放。

9. 不输出未经证明的2D HeavyIon/PMI原生片段。交付可求值的G2和保守积分、不可覆盖的投影source/contract/ledger/manifest及重算入口。真实BCAT事件、对应二维材料合同、原生源表示与场积分仍为接线前置。原v1/v2源摘要及13量合同不得自动当作本二维语义。
