# S2 原生几何测量生产者：离线候选

本目录补齐既有首4角色的几何测量实现候选。原S2包、F5–F7源码与29项验收、capture/r3及release-candidate-r2不改；不是新的执行发布。当前没有真实mesh或原生测量结果。

使用既有本机Python生成到全新目录：

```powershell
& .\local_runtime\vdmos-analysis-venv\Scripts\python.exe -X utf8 -B .\experiments\dram-see-v4\s2-evidence-r1\geometry-producer-r1\producer.py prepare --package .\local_runtime\dram-see-v4\s2-inputs-r1\20261016T050606Z\packages-r2 --output <新的runtime目录>
```

该命令只读取冻结输入并写候选文件，不运行SDE、SVisual、网格器、求解器或网络。已有目录拒绝覆盖。每个D2/D3目录包含measurement-plan.json、原CAD前缀加只读观察器的geometry-with-measurements.scm、measure-geometry.tcl及未批准比较策略；根目录含明确关闭执行的candidate.json和比较器。没有project.json、有效mesh-input.tcldata或原生授权。

## 未来生产链与证据含义

1. 同一次获授权D2/D3构建末尾，SDE观察实际接触边/面、长度/面积、包围盒、接触探针归属和掺杂样点的实际材料。原CAD前缀逐字保留，观察器不建立或修改几何。
2. 原runner内受计费的SVisual步骤读取该实际cell_msh.tdr，记录前后SHA、物理材料/Contact/区域/字段库存，测区域面积或体积、坐标范围、掺杂值和最终mesh接触范围。2D不以面积充长度，不乘AreaFactor。
3. 同一原执行链提供原始sde/mesh/svisual退出文件、观测context与发布/预算/授权绑定；evaluate.py只比较这些既有文件，不调用任何工具。context中的JSON零不能替代原始退出文件。失败记录和所有原始字符串保留，缺失、命令错误、非有限数和负掺杂均拒绝。
4. geometry-validation.json与三类测量CSV及附加证据须在**原solver归档冻结前**形成。现有audit.py从solver归档消费它们；不往已冻结归档追补。若未来改用独立测量operation，必须另发外置证据引用接口。A0只复用同一获验收D3 mesh/几何证据，不重新建mesh或额外探针run。

原runner当前尚未接入这些步骤；本轮只交付未执行实现。原生测量API依据与边界见[API_NOTES.md](API_NOTES.md)。完整SDE/SVisual语法、厂商行为、原档形成和原生正常路径仍未验证。

## 比较与拒绝

比较器分开记录numeric_checks、授权和兼容checks。native入口拒绝synthetic，且缺少精确发布、真实原档身份、原始退出码、获批准策略或授权/预算即不能输出通过项。隔离合成入口用于软件解析测试，固定synthetic=true、native_qualified=false、is_tcad_result=false，不能授予真实资格。

预登记提案：区域面积/体积0.5%或1e-10 um^dimension；CAD接触测度1e-6相对或1e-10 um^(dimension−1)；坐标绝对1e-6 um；掺杂2%或1e8 cm⁻³。它们是待发布比较策略，未批准、不替代或放宽原G1/G2门。有限样点不能证明全域掺杂、拓扑或网格收敛；CAD接触测度也不声称是离散网格表面面积。

## 成本与剩余准入

SDE观察器留在原两次mesh构建中；D2/D3各一次SVisual几何测量是**未来两次原生提取成本**。原首切片“2次字段提取”提案不被默认为已经覆盖它们；新发布必须明确合并方式或总提取调用及预算，不能隐形追加。本轮没有调用、预约或改写旧预算。

仍需原生授权、完整执行输入与精确SHA、采集补丁单独应用/发布、实际资源与owner/共享锁/严格SSH准入。完成候选不等于发布首4，也不等于G1/G2通过。原PMI实际BE未更新、R12未编译/发布保持。

[规格](implement-stage/SPEC.md) · [事前假设](implement-stage/ASSUMPTIONS.md) · [实施与验证记录](implement-stage/BUILD_NOTE.md)

当前runtime由local_runtime/dram-see-v4/s2-geometry-r1/current-preparation.txt定位，最终report.md与root-acceptance.json记录本轮实际验证边界。
