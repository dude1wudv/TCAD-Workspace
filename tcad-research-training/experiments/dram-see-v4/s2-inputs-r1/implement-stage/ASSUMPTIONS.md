# S2 Implementation Assumption Ledger
<!-- ASK mode: never; user explicitly authorized offline preparation, prohibited native computation -->

原r13物理假设不重写。本表先登记影响实现含义/接口的补全，后续每个新取舍必须在依赖代码前增加。

| ID | 尚未确定处 | 本实现选择 | Class | Source |
|---|---|---|---|---|
| A001 | 审查包是否可直接执行 | 只写project.review.json，不写project.json；任何执行须另发布，不将离线检查等同原生资格 | interface | user |
| A002 | 槽/栅在y方向的有限伸展 | 外槽覆盖active及两侧STI，即y=±60nm；金属缩至±56nm以保留4nm端盖SiO2，防止与STI外沿Si直接相接；STI覆盖全x域、y=10…60及−60…−10nm、z=0…200nm；不重建完整saddle侧栅 | semantic | default |
| A003 | 圆槽几何与源mask统一 | 同一显式几何描述产生CAD及Si掩膜；如以多边形逼近圆弧，须声明误差并使独立积分核对实际离散形状；不默默将圆底改成矩形 | semantic | default |
| A004 | 2D与3D坐标/电流 | 3D为(x,y,z_depth)µm；2D为(x,z_depth)µm映射为SDE平面(x,y)，AreaFactor=0.02对应20nm名义挤出宽度；2D只调试，不声称等同3D | semantic | default |
| A005 | 理想金属如何进入器件求解 | CAD临时导体用于标记gate边界后移除导体体积；SDevice接触显式功函数4.6eV，SiO2保留，不把金属当半导体 | semantic | default |
| A006 | Gaussian掺杂种类 | ArsenicActiveConcentration与BoronActiveConcentration；精确ND(x,z)沿用r13公式和5nm平滑混合；只赋给Si | semantic | default |
| A007 | 首4角色的网格复用 | D2/D3各建一次；两个A0必须引用并核验D3同一未来mesh，当前不得虚构mesh哈希或附带重复SDE步骤 | interface | default |
| A008 | 只读源审计与未来原生提取 | 离线期望、合成反例与真实测量分目录/字段；无native receipts不得产生qualified gate；实际BE帧索引沿原日志/PLT/TDR方法 | interface | default |
| A009 | 本轮α适配范围 | 实现S2、5MeV、正z、变LET、Si掩膜及规定w/σ/窗口；其他角度/能量拒绝当前适配器，矩阵仍待后续版本 | semantic | default |
| A010 | 资源门与mesh未知 | 沿用旧8/20/4/160GiB门及单核单线程；离线体积/网格控制不等于实际节点数或资源预测通过，首4包仍标执行阻塞 | interface | user |
| A011 | 并行写入/半小时任务 | 主Agent唯一整合/调度；子代理目录分权不递归。preparation-state=IN_PROGRESS期间心跳不能改正在生成的输入 | interface | default |
| A012 | 实际写入与BL隔离细节 | source=SN、drain=BL；两bit共同SN=0.6V只在平衡初始化固定，首瞬态前Unset；BL于6.1–6.2ns线性预充，8.1ns将rdrive从1kΩ置为1e15Ω；不另加SN泄漏电阻或改初态保证通过 | semantic | default |
| A013 | BTBT模型卡的精确实现 | 使用W-2024.09手册NonlocalPath，单一未命名过程；Apath/Bpath/Dpath/Ppath/Rpath及MaxTunnelLength取已安装卡的第一过程数值，显式写现代键名；其余物理参数插入同版本私有完整卡并冻结SHA，不调参校准 | semantic | default |
| A014 | 原生电流和读出指标 | 保留已审计的CΔV+BE积分i(access,sn)=0约定，新原生还须验证；Qcol_signed=−积分信号减A0的SN端电流；保持扰动用源窗左端到19.9ns，读出为21.9–22ns时间加权均值；不生成持久翻转标签 | semantic | default |
| A015 | 两条DC曲线的起点 | 每条Vds扫描都从同一保存平衡态重载，先到Vg=−0.5V和目标Vd，再扫Vg至1.5V；两种Vd=0.1/1.2V不串接作滞后数据 | semantic | default |
| A016 | 新网格资源预测尚无测量 | 审查包resource-policy保持approved=false和预测null；mesh guard只检查当前远端mesh/空间/内存，要求未来独立发布及正值预测才能放行，不能代替调度前本机20GiB、总160GiB和锁/预算检查；不移植旧410帧预测 | interface | default |
| A017 | G1指标与数值资格分离 | 离线metrics接受严格递增完整有限采样，电流采用右端BE积分，电压采用分段线性插值/时间均值；给出逐步KCL及功能候选门，但单个main角色永远不能宣告G1通过，仍缺h/2、dt/2及原生工程链 | semantic | default |
| A018 | 固定求解控制，独立扫查后补记 | Digits=5、ErrRef(e/h)=1e7 cm⁻³、Iterations=30、Notdamped=100、初始Coupled上限100；DC用ParDiSo，瞬态Blocked/SubMethod=ParDiSo/BE，ExitOnFailure；DC InitialStep=0.001、MinStep=1e−8、settle MaxStep=0.02、scan MaxStep=0.005、Increment=1.3，200输出区间；瞬态MinStep=1e−18 s、InitialStep=min(MaxStep/10,1e−13 s)、Increment=1.3。它们是未原生验证的数值控制，不是可按结果改动的质量门；失败须保留并经单独纠错发布 | numeric | default |
| A019 | A0场审计的输入归档绑定 | A0角色也归档source-contract、alpha-reference和alpha-profile三份审计资料，作为Si材料及配对源期望依据；不包含或激活任何HeavyIon参数/发生器。真实geometry-manifest、原生退出/affinity/锁receipt只能在未来实际执行后形成 | interface | default |

## Reuse and review boundary

现有runner和旧冻结代码不修改；新适配器只实现当前不同几何/源接口，不复制调度体系。同家族假设扫查记录same-family/provisional，确定性检查另报；没有商业工艺校准或原生运行通过的结论。

A018由独立扫查发现初版实现未事前逐项登记，现明确补记其时序；不将事后记录说成事前冻结。实现值及原质量门未改变。
