# S2 CAD、掺杂、接触与网格审查说明

本文件对应 `geometry.py`，输入为 r13 的 `model-contract.proposed.json`，补全决策见
`cad-assumptions.md` 与主实施假设表。状态是**离线可审查输入，未运行 SDE、snmesh 或
SDevice，未通过原生资格**。临时金属不进入器件求解，也不代表 Geant4 的金属材料映射。

## API 与坐标

```python
render_sde(model, dimension=3, mesh_scale=1.0) -> str
describe_geometry(model, dimension=3) -> dict
validate_geometry(model) -> dict
material_at(model, x, y, z, dimension=3) -> str
is_silicon(model, x, y, z, dimension=3) -> bool
donor_concentration(model, x, y, z, dimension=3) -> float
```

后 3 个 API 的坐标单位均为 µm，使用物理坐标 `(x,y,z_depth)`；二维时忽略物理 y，
只取中心截面。`material_at` 是名义解析 mask，返回 `Outside`、`Silicon`、`SiO2`
或 `GateVoid`，不是实际 TDR 材料测量。`donor_concentration` 的单位为 cm⁻³，只在 Si
返回浓度。渲染器只接受 S2（gate top=80 nm），拒绝非有限坐标、无氧化层、越界接触和
非正网格系数。输入合同以 nm 表示，进入 CAD 时转换为 µm。

3D 保持 `(x,y,z_depth)`；2D 将 `(x,z_depth)` 映射为 SDE `(x,y)`，SDE 的第三坐标为 0。
二维是 y=0 的中心截面，因此没有 STI 实体；设备 deck 的 `AreaFactor=0.02` 由主线实现。
这不等于三维复制，也不用于强行匹配原文绝对电流。

## 硅、STI、圆底与金属空腔

| 项目 | 实际构造，nm | 依据边界 |
|---|---|---|
| 初始 Si | x=[−1000,1000]，y=[−250,250]，z=[0,1000] | r13 工程域 |
| 两侧 STI | 全 x；y=[−60,−10]、[10,60]；z=[0,200] | 主 A002 |
| 外槽 SiO2 | x=[−12,12]、z=[0,142] 矩形，与中心 `(0,142)`、r=12 的圆并集；3D 沿 y=[−60,60] | r13；z=0…80 为封顶氧化物属于 CAD002 |
| 临时金属 | x=[−8,8]、z=[80,142] 矩形，与同心 r=8 圆并集；3D 沿 y=[−56,56] | r13 + 主 A002/CAD003 的 4 nm 端盖 |
| 底部 | 金属最深150；氧化物最深154 | r13 的 recess 解释 |
| 保留材料 | `Silicon`、`SiO2`；移除全部 `Metal` 体积 | 原生 DATEX 解析仍待验 |

圆底使用同版本手册支持的圆/圆柱和 Boolean union，不用矩形或多边形近似。使用 ABA
的顺序为 Si → STI → 外槽矩形/圆并集 → 金属矩形/圆并集。每次后插入物替代重叠部分，
STI 与外槽交集仅记一次；金属的完整边界设为 gate，然后移除金属。圆弧交会处由原生
Boolean 几何内核处理，离线代码没有声称它已经执行成功。

外槽与金属不能都伸至 y=±60 nm，否则金属端面直接接触 STI 外侧 Si。当前金属止于±56 nm，
留下4 nm SiO2 端盖；此项已获主代理接受并在主 A002 登记。

设外槽截面积 `Ao=2×0.012×0.142+π×0.012²/2`，金属截面积
`Ag=2×0.008×(0.142−0.080)+π×0.008²/2`，单位 µm²。下表是解析名义测度，非 TDR 测量：

| 测度 | 2D，µm² | 3D，µm³ |
|---|---:|---:|
| 完整域 | 2 | 1 |
| 外槽，含后移除金属 | 0.003634194671058465 | 0.000436103360527016 |
| GateVoid | 0.001092530964914873 | 0.000122363468070466 |
| 保留 Si | 1.996365805328942 | 0.959927316106579 |
| 保留 SiO2，含 STI | 0.002541663706143592 | 0.039950320425351 |

三维每侧 STI 原体积为0.02 µm³，每侧与外槽交集为0.000181709733552923 µm³。
`Si+SiO2+GateVoid=完整域`。描述器提供各保留区域的测度和几何定义，源审计必须共享该 mask。

## 接触定位与拒绝条件

| SDevice 名称 | 电路含义 | 几何位置，nm | 中心探针，物理 nm |
|---|---|---|---|
| `source` | SN | x=[−72,−32]，y=[−10,10]，z=0 | (−52,0,0) |
| `drain` | BL | x=[32,72]，y=[−10,10]，z=0 | (52,0,0) |
| `gate` | WL | 移除金属后的全部 SiO2/空腔边界 | 顶(0,0,80)，左右(±8,0,111)，底(0,0,150)，3D端盖(0,±56,111) |
| `body` | BODY | z=1000 的完整底面 | (0,0,1000) |

2D 在 source/drain 的两端插入顶点，再通过中心探针取唯一边。3D 用显式矩形 imprint 切出
40×20 nm 面；imprint 必须返回一个面，中心 `find-face-id` 必须返回一个面，而且二者必须
是同一实体。body 探针也必须唯一。金属移除前中心 `find-body-id` 必须唯一，移除后必须为
空；gate 每个解析表面的探针必须找到唯一边/面。找不到、多重命中或 imprint/probe 不符均
调用 `sde:error`，不会任选首项继续。gate 是多个表面组成的同一电极，不是漏判多重接触。

离线检查验证每个 gate 探针向空腔内1e−8 µm是 GateVoid，向外同距离为SiO2；源漏/body向
器件内部为Si。未接触的外边界保持自然绝缘条件。实际表面数量、面积和接触标记仍须由
未来原生结构/网格证据核对。

## 精确混合 Gaussian 掺杂

```text
Npk = 1.45e20 cm^-3; NA = 1e17 cm^-3
aSN = 0.087 / sqrt(log(Npk/NA)) um
aBL = 0.1375 / sqrt(log(Npk/NA)) um
w = (1-tanh(x/0.005))/2
ND = Npk*(w*exp(-(z_depth/aSN)^2)+(1-w)*exp(-(z_depth/aBL)^2))
```

使用 `ArsenicActiveConcentration` 与 `BoronActiveConcentration`。一个 `General` 分析式
直接按设备绝对坐标计算完整二维/三维混合剖面；3D 的深度变量是 z，2D 是 y。不使用两条
默认侧向扩散 Gaussian 来冒充5 nm的tanh混合。donor采用 material EvaluateWindow=`Silicon`，
decay=0，`NoReplace`；背景受主也仅放置于Silicon。SiO2和GateVoid不分配掺杂。

General API 的失败回退参数显式设为−1 cm⁻³，作为非法 sentinel；原生资格必须拒绝负值、
非有限值以及与公式不符的值，不能把回退值当成功。原生节点插值/物种解析与网格上的
实际 ND、NA、净掺杂尚未验证。DN的SN/BL远端结深检查使用x=−100/+100 nm，并不宣称
整个横向平面都有相同结深。

## 网格控制与成本边界

| 窗口 | 范围 | 主网格最大/最小请求 |
|---|---|---|
| `All` | 完整域 | 40/20 nm |
| `Junction` | 全x/y，z=0…160 nm，限Si | 5/2.5 nm |
| `GateOxide` | 外槽包围盒外扩1 nm，z=0…155 nm | 1/0.5 nm |
| `AlphaTrack` | x=[−252,148]，y=[−200,200]，z=0…1000 nm，限Si | 5/2.5 nm |
| `Interfaces` | 所有Si/SiO2界面 | `MaxLenInt=1 nm`，factor=1.5，DoubleSide；最小0.5 nm |

二维使用这些窗口的中心截面。`AlphaTrack` 是四倍w的网格包围盒；它不裁掉Gaussian源尾，
也不把包围盒外的源电荷重新归一化。`mesh_scale=0.5` 同时减半最大、最小和接口首步尺寸，
不改变几何或掺杂；每个网格角色须另由主线发布。A0不重复建网格，复用D3未来实际mesh。

本实现没有为省成本放宽1/5/40 nm要求。全STI界面和有限宽模型可能产生较高节点数；上述
请求不是实际节点/内存/磁盘上界。真实成本仍未知，原8/20/4/160 GiB资源门保持，首批角色
执行仍关闭。末尾仅保留现有串行路径：

```scheme
(sde:build-mesh "snmesh" "" "cell")
(define resource-guard-status (system:command "/usr/bin/python3 mesh_resource_guard.py"))
(if (not (equal? resource-guard-status 0))
    (sde:error "Mesh resource guard blocked SDevice; see mesh-resource-report.json"))
```

`mesh_resource_guard.py`由主代理随审查包提供；没有该文件不得发布执行。唯一runner仍负责
共享锁、单核affinity、单线程和串行。该Scheme字符串的存在不构成执行授权。

## 同版本命令依据

只读本地已存的 **W-2024.09** 手册，未安装软件、未联网取得商业手册、未将其全文复制入库。
原始PDF与必要局部摘录均留在 `local_runtime/`。关键页码是PDF页码与书页码一致的页：

| API/语义 | 本地手册页 |
|---|---|
| ABA、新物体覆盖与Boolean union | SDE pp.142–143、613 |
| `create-circle`、`create-cylinder` | SDE p.621、pp.625–626 |
| `set-contact ... "remove"`、默认imprint | SDE pp.232–233 |
| 矩形imprint及返回face-list | SDE p.235、p.679 |
| `insert-vertex`与接触分段示例 | SDE p.604、p.680 |
| `find-edge-id`、`find-face-id`唯一性所需返回类型 | SDE pp.393–394 |
| `define-analytical-profile`的General型 | SDE p.552；Smesh pp.24–25 |
| General绝对坐标、tanh/exp/log/sqrt、失败默认值 | Smesh pp.24–25 |
| 分析剖面material限制 | SDE pp.553–554；Smesh pp.37–39 |
| 常量材料掺杂 | SDE p.557 |
| `MaxLenInt`、`DoubleSide`、窗口/材料交集、网格尺寸 | SDE pp.570–574 |

`sde:build-mesh`和同阶段资源guard调用沿用仓库
`source-interface-3d-r1/build_interface.py`已存在路径。这些依据证明命令形式可查，并不证明
本新几何已由原生解释器解析或生成网格。

## 已做离线检查与证据

运行命令（工作目录为仓库根）：

```powershell
python local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/cad/check_cad_offline.py
```

最终退出码0。该独立检查解析**生成出的Scheme文本**的图元，按ABA材料优先顺序与共享mask
核对：2D/3D各16000点，均0差异；由解析出的圆/矩形参数独立积分并核对材料分区和STI交集，
最大相对差约2.9e−14；两维各58个Si样点对生成出的General表达式独立求值，最大相对差约
3.8e−15；检查接触范围、四个接触定义、唯一build-mesh、无残留金属目标、半尺度只改网格，
并拒绝7类非法输入。模块内另有48项解析约束检查。

第一次独立公式检查退出1：数学等价的 `(1+tanh)/2` 与合同字面的 `1-w` 在极小尾部有
浮点消减差异。已改为逐字的 `1-w` 算术，再通过原1e−12相对检查；没有放宽容差或改掺杂。
失败说明保留为 `cad/offline-check-attempt-1.txt`。

证据同目录下包含 `cad-offline-validation.json`、`cad-independent-review.json`、
`geometry-d2/3.scm`、`geometry-d2/3.json`、独立脚本及私有局部手册摘录。
这些仅是解析/生成/数学验证，不是原生syntax、Boolean拓扑、实际contact/doping、网格资源、
无粒子DC/写读或源场资格通过。
