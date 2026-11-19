# 几何测量生产者取舍
<!-- ASK=never; EFFORT=balanced; ASSURANCE=draft -->

| ID | 未定项 | 代码前选择 | Class | Source |
|---|---|---|---|---|
| G001 | 候选与已验收实现的关系 | 独立geometry-producer-r1目录；原F5–F7/S2源码与冻结包不改，读取其合同；只为D2/D3准备，两A0复用同一D3实际mesh与测量 | interface | user |
| G002 | 名义值与测量来源 | geometry-contract仅作expected；未来SVisual读取实际mesh产出原始记录，Python比较器不得以期望值填缺测；任何缺件/命令错误/非有限/重复项均拒绝 | semantic | user |
| G003 | 几何检查与整体科学资格 | 仅产生有原始证据的材料/接触/掺杂/单位检查，整体native_qualified、G1/G2始终false；有限点采样不是全域拓扑/掺杂或数值收敛证明 | semantic | default |
| G004 | 2D量纲 | 2D物理x,z映射native X,Y，长度um、区域面积um²、接触长度um；3D保持X/Y/Z、体积um³、接触面积um²。不乘AreaFactor=0.02、不将2D面积当3D体积 | semantic | user |
| G005 | 尚无原生数值容差 | 新增比较策略仅为未批准提案，预先冻结后才可执行；不修改既有科学门。native报告不得由未批准策略产生通过；合成测试显式synthetic且不是真实结果 | semantic | default |
| G006 | 原档内接口的位置 | 现有audit从solver归档读取几何报告/三CSV；未来必须在原归档冻结前完成生产与评估，不回写已冻结归档。若用独立operation，另发外置引用接口，本轮不改它 | interface | default |
| G007 | 原生测量调用计费 | SVisual几何测量属于原生提取成本；D2/D3各一次候选调用，不另求解mesh、不额外探针run。原2字段提取提案不被默认为已含这2次，新发布必须明确总成本/预算；本轮调用与预约均0 | semantic | default |
| G008 | 执行边界 | 只生成脚本与计划，不创建project.json、不应用采集补丁、不启动程序/网络。原生路径须明确释放的策略与原始运行证据，synthetic测试入口不能产生native来源报告 | interface | user |
| G009 | 接触测量API与对象 | 不猜list_contacts、不用2D面积当长度。SDE原构建末尾的只读观察器用contact-sets/get-contact-edgelist/facelist及edge:length/face:area、bbox-exact测实际CAD接触，并检查各已登记探针是否属于该contact；SVisual的Contact材料区域枚举/坐标范围再核对最终mesh。CAD面积明确不是网格表面离散面积 | semantic | default |
| G010 | 比较误差提案 | 区域面积/体积相对0.5%、绝对1e-10 um^dimension；CAD接触测度相对1e-6、绝对1e-10 um^(dimension-1)；长度范围绝对1e-6 um；掺杂点相对2%、绝对1e8 cm^-3，非负/有限及负sentinel无条件拒绝。全部是pending-release比较提案，不改既有G1/G2门、不根据未来响应调宽 | semantic | default |
| G011 | 点采样覆盖和单位判定 | 两侧结深上下及混合区、有限宽和深体预登记Si点，另查Si全域donor最小值与acceptor范围；实际区域及Contact库存严格匹配。单位同时靠2D/3D映射、实测域坐标范围和量纲合同，不仅相信CSV标签。有限样点仍不证明全域掺杂/网格收敛 | semantic | default |
| G012 | 原生通过报告的发布条件 | 数值比较结果与policy授权分开；native路径当前policy未批准时四checks全false。仅显式released策略、真实origin/mesh前后指纹/原执行证据和数据均合格时才可为未来原生生成兼容报告。隔离synthetic路径允许数值通过项仅验证消费接口，固定synthetic=true/native_qualified=false；公开native入口拒绝synthetic | interface | default |
| G013 | SVisual坐标probe不支持材料过滤 | probe_field -coord仅获取该坐标场值；plan明确entity_kind=all。另由同次SDE的find-body-id与generic:get记录每个Si样点的唯一body/region/material，要求R.Silicon/Silicon；它不是声称SVisual做了材料过滤，仍须最终mesh库存与区域测度一致 | semantic | default |
| G014 | context中的退出摘要不能独立充作观测 | 同时要求原runner采集的sde/mesh/svisual-exit-code.txt，严格整数0及context内各文件SHA绑定；仅JSON填0拒绝。整体身份/锁/归档真实性仍由现有执行链验证，本候选不重造runner | interface | default |
| G015 | 手册与实测释放返回值有差异 | W-2024.09手册记integer 0，但原69帧成功提取原档实测返回恰一个已删除对象名。沿原已验证提取器逐对象删除并匹配该名称，再查询库存确认消失；不将任意非错误返回当成功 | interface | default |
| G016 | 未登记的CAD实体计数准入 | gate要求2D实体数≥4、3D≥6，作为至少覆盖登记表面的保守下界；source/drain/body恰1。它与面积/长度、bbox、探针附着共同判contacts；更多gate实体仍需所有其他检查通过，不证明拓扑完全等价 | semantic | sweep |
| G017 | 未登记的全域掺杂极值比较 | Si donor最大值须与peak_cm3在G010的2%或1e8容差内，最小值在0附近且非负；Si acceptor min/max同样比较背景值。每个非Si区域两物种min/max按expected=0、绝对1e8 cm^-3比较，允许[0,1e8]，不能称严格零掺杂或精确裁剪；缺字段不补0 | semantic | sweep |

G016/G017由首轮独立扫查指出后补记，不追认事前登记；没有因此改变实现、数值容差或既有科学门。初轮2项未声明语义及复核结果均保存在runtime。测试通过不消除same-family/provisional边界。

具体原生API、采样点与比较容差在相应代码之前继续登记；读取已安装私有手册只用于开发依据，不能当候选已执行证据。ASK=never表示在已授权离线范围内记录默认取舍并推进，不扩大原生授权。
