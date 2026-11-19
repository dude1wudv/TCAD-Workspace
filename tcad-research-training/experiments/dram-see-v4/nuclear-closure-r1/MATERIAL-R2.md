# 合同 SiO₂ 材料实现修订 r2

原请求 `nc-r1-init-h` 在原生初始化时失败；原始 operation、归档、退出码和请求均保留。SSH/remote/collection 退出码为 2/2/0。原生 `status.json` 的 events/tracks/steps 均为 0，`beam_on_called=false`；`geometry-built.csv` 仅写入 World 和通过重叠检查的 Si，Si 实际密度为 2.3299999999999996 g/cm³。错误为 `Shared contract and native NIST material density differ`。SiO₂ 未完成构造验收，失败原档本身没有记录其实际密度；默认 NIST 数值由新诊断探针直接打印。

原实现：`matched-transport-r1/transport_matched.cc`，SHA256 `0e510e397b5dd2ec03bcd14cb70d99dc33b59b469646d2920b0f4137a9161c27`。新静态完整副本为 `transport_material_r2.cc`。除材料构造 helper、几何中的材料查找和材料来源元数据三处以外，新副本逐字还原为原实现；测试也对非授权物理参数变化给出反例。

## 材料规则

冻结几何继续要求 `G4_SILICON_DIOXIDE` 名称、2.2 g/cm³、自然 Si/O 原子数比 1:2。新 helper 使用 `FindOrBuildElement("Si", true)`、`FindOrBuildElement("O", true)` 得到自然同位素元素，显式创建唯一 `G4Material` 并按整数原子数 `AddElement(1/2)`。不把 2.2 描述为默认 NIST 密度。`G4_Si` 和 World 的 NIST 路径保持原样；所有几何、100 MeV 质子、种子、QGSP_BIC/Opt4、cuts、最大步长、原始输运记录、核见证和验收阈值均保持。

旧源码显式材料构造次序是 World → Si → SiO₂，没有在目标查找之前额外构造 NIST SiO₂。新 helper 在任何创建之前查询全局材料表：遇到不是本 helper 所有的同名对象立即失败；自己的对象可重复引用，但必须唯一且原子组成仍为 Si:O=1:2。不会删除、重命名、覆盖或再次注册旧 NIST 同名材料。外层密度差检查仍为原来的 1e-9 g/cm³，不能用放宽阈值接受默认值。

`metadata.json` 追加 `material_implementation`，明确描述合同密度来源、自然元素来源、原子比和唯一注册策略。它是实现政策，不代替初始化后的 `materials.csv` / `elements.csv` / `geometry-built.csv` 原生观察。

## 诊断探针及根控制器入口

`material_probe.cc` 与生产源包含逐字相同的材料 helper，依赖同一生成 `geometry.hh` 和已有 Geant4 10.7.3。探针没有 RunManager、物理表初始化、粒子枪或 BeamOn。

根控制器在既有串行工程 operation 内编译，参数沿用现有 Geant4 配置：

```bash
g++ -O2 $("$G4ROOT/bin/geant4-config" --cflags) material_probe.cc -o material_probe $("$G4ROOT/bin/geant4-config" --libs)
./material_probe nist > material-nist.txt 2>&1
./material_probe contract > material-contract.txt 2>&1
./material_probe collision > material-collision.txt 2>&1
```

三个命令必须是独立进程。`nist` 只构造并打印默认材料；`contract` 只使用合同氧化物并再次调用 helper 证明对象复用；`collision` 先登记默认 NIST SiO₂，要求合同 helper 明确拒绝，再打印原材料证明同名注册数仍为 1。不能在同一进程把默认 NIST 和自定义氧化物都注册成同名材料。

每种材料打印实际密度、注册数量、元素数、平均激发能 I（eV）、温度（K）、压力（Pa）、原生状态枚举、Si/O 原子密度比例和质量分数，并逐项输出自然同位素与丰度。来源标签区别 `default_NIST_definition` 和 `explicit_shared_contract_density`。

根控制器已执行并归档 [nc-r1-material-probe-r2](../../../local_runtime/dram-see-v4/transport-probe/operations/nc-r1-material-probe-r2/operation.json)，operation 的 SSH/remote/collection 退出码为 0/0/0，三个独立进程均有完成标志。真实 `collected/nist.txt` 与 `collected/contract.txt` 的默认/合同氧化物密度分别为 2.3199999999999998 和 2.2000000000000002 g/cm³；两者 I 均为 139.19999999999999 eV，T 为 293.14999999999998 K、P 为 101325 Pa、state=1。Si/O 质量分数及逐同位素自然丰度完全相同，原子比为 1:2（浮点打印的 O 比例分别为 2 和 1.9999999999999996）。`collision.txt` 证明外来同名对象被拒绝，原默认材料仍唯一且属性未变。

因此本修订保留未显式设置 I 的 helper；不猜测常数，也不添加电磁材料参数覆盖。该证据证明这里实际观察的 I/T/P/state/元素组成一致，不声称所有密度相关派生输运参数保持不变。上述原档和源码 SHA256 由测试运行时计算并与 operation 收据/归档逐项核验，不手填复制探针哈希。

该材料诊断是工程编译/诊断操作，0 TCAD 调用、0 初级事件；下一次真实 H 修复请求按授权记纠错 1/2，不能重写原失败为成功。

## 验证与边界

本地只读测试命令：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v4/nuclear-closure-r1/test_material_r2.py -v
```

本次实际执行 9 项测试，全部通过，进程退出 0；包含新增真实 probe 归档核对。早先未绑定 probe 原档的 8 项静态测试也曾通过，不能把该早期结果当作原生材料证据。

测试检查原源码和失败归档哈希、零事件失败事实、精确受限文本差异、probe/helper 同一性、合同密度与原子组成、重复注册前置拒绝、来源声明和 C++ 词法括号完整性，并读取真实 probe 归档证明源码绑定、所列非密度参数相同及碰撞后原材料未变。测试不伪称 C++ AST 或本机原生编译。Geant4 API 已只读核对本地原始 `geant4-10.7.3-centos7.tar.gz` 中的 G4Material/G4NistManager/G4Element/G4IonisParamMat 头文件。

本代理未运行远端、编译器、输运或 TCAD，未修改旧合同、旧源码、失败原档或根调度文件。根控制器已取得诊断探针的原生编译和运行证据；完整生产 C++ 编译、H 初始化与科学验收仍由根控制器另行取证。
