# R50限定自然语言映射（无求解入口）

本模块只解析原限定中文模板并审计其到冻结R50-main设计的映射。它输出stdout，不写新输入deck、队列、ledger、预测或结果，不读任何运行归档，不调用Geant4、TCAD、SSH、GUI、Git。解析/映射成功不是物理结果，也不是学生已经演示或课程通过。

## 固定版本与适配

- 原解析器`experiments/dram-see-v3/design.py` SHA256 `583d047b33279f56c6abcdb411da50791b584e330d3302917328b754590c47b9`。
- R50设计SHA256 `6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740`；计划SHA256 `c2f08d68394b669b0ab7edb6727523743cd00a93647e132756421d40a8d9db67`。
- 活动首段清单SHA256 `21456da4b28881ae21ad586c683a30aed9395e3c2be85e6c22a8f771349410d2`。运行本模块前后只读核验其29个文件加清单自身，共30个活动来源；不修改任何活动source或原manifest。Demo自身固定清单只包含八个实际实现/解释依赖，另存30来源保护表，不使用目录glob。

以Python AST读取原`CANONICAL_REQUEST`常量及`events`/`parse_request`两个纯函数，沿用原正则、规范化、参数值、单位与错误文本。没有导入原design模块的`common`/`freeze`/Git代码。R50 tag/case使用首段controller和后半finish的具名纯函数；仅提取这些函数，不导入控制器或runner模块。`safe_tag`同样只取原纯函数。

原请求只规定事件矩阵、预算和氧化层范围；**50 Ω不是从这段自然语言推断或获得新授权**。它来自已冻结的R50计划和physical revision，映射显式写入`schema=dram-see-v3-r50-main`、`physical_revision=r50-main-r1`、`physical_revision_probe_only=false`、导通50 Ω/关断1e20 Ω。新请求没有改变物理值或增加预算的能力。

## CLI

使用现有Python，不安装依赖：

```powershell
# 完整64事件、128位响应、匹配依赖与源码哈希预览
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/demo.py preview

# 只看数量、语义边界和两张清单hash
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/demo.py preview --compact

# 同一映射及10个固定拒绝示例的软件审计
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/demo.py audit

# 仅说明预登记主响应的证据查找路径，不声称结果存在、不读raw
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/demo.py locate --event-label l018-alpha-a30-s202610311 --bit 1

# 预期exit2，无输入/队列变化
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/demo.py preview --text "扫描几个尺寸"
```

默认请求就是原模板，也可以完整传入`--text`：

```text
扫描栅长0.18、0.25、0.35、0.45 um；粒子alpha、proton；能量5 MeV；方向0、30度；每工况4个独立事件；每事件配对0/1；累计求解预算24小时；焦点0.25 um氧化层4、5、6 nm。
```

允许的空白、`µm/μm`及中文逗号规范化完全沿用旧解析器；大小写、语序、数值、单位、分号等其他行为也不扩大。没有`run`、`execute`、`freeze`、`dispatch`或shell参数；这些动作由argparse直接拒绝，即使全部前置科学门槛已通过，也不能从此入口执行求解。

stdout可由主代理验收后保存到新的独占课程证据文件；本模块不提供输出文件覆盖选项。退出0仅表示软件解析/映射检查成功；拒绝或来源错误返回2并输出`REJECTED_NO_DISPATCH`。不存在自动降级、猜测参数或重新抽样。

## 映射与统计分母

`preview`逐事件与R50 `design.json.events`严格相等，保留全部label、seed、condition、replicate、几何向量、pilot及split。事件仍32 train/16 holdout/16 extrapolation，共64；每事件0/1，共128。

主响应仅取controller的pilot/train event角色及finish的64 test角色，再按冻结事件顺序列出；保留独立的`main_dispatch_sequence`说明实际主响应顺序，不能把这个预览当运行队列。每行的`planned_case`精确复用控制器recipe，包含同版本parent和匹配control/neutral标签。source路径仍指固定Geant4硅入口事件；这里只说明规划路径，未读文件也不宣称已生成G4。

20个基准/中性/物理参考、2个源隔离、6个预登记细化、14个oxide额外case与原规则boundary只作为排除范围/依赖说明，不计入128。原100 Ω、R50 probe、control/neutral/physical及refinement标签不能用`locate`充当主事件。4/6nm仍是L0.25敏感性扩展，不是另加独立事件或改变主矩阵5nm参数。

24小时仍是原全局86400 s累计预算，含所有历史/验证/失败费用；不获得新的24小时或延長12小时窗口。holdout/extrapolation预览明确`NO_DISPATCH_INTERFACE`；后续真正提交仍须分别通过训练、参考、pilot、数值、实际预测冻结和UTC顺序、共享锁、预算、deadline等原控制器门槛。此工具不检验或绕过这些运行门槛。

规范化清单hash使用UTF-8 JSON、`ensure_ascii=False`、`sort_keys=True`、分隔符`,`/`:`且禁止NaN，数组顺序不变。`events_canonical_sha256`仅绑定64事件；`responses_canonical_sha256`绑定128映射，均排除生成UTC，方便重复比较。它们不是求解输入归档或实测响应hash。

## 拒绝示例

`audit`固定复验以下10类，保留原解析器错误文本：模糊“几个尺寸”、L0.50、48小时、每工况6事件、45°、10 MeV、缺单位、追加“改成100欧姆”、追加“立即求解留出”、跳过预测冻结立即求解外推。前五类与原demo一致；后五类说明范围及不调度边界，没有为新增句式创建语义规则。

参数明确却不同于定稿时返回`Request exceeds or differs from authorized frozen matrix/budget; no inputs or queue generated`；无法匹配模板时返回`Ambiguous or unsupported request: use the documented bounded template with explicit units`。原解析器抛出的其他ValueError也不会转为执行。

## 课程及真实证据入口

课程大纲要求自然语言改参遍历、Geant4到TCAD传递、多参数响应、拟合/外推验证；本模块只补齐“原限定语法→R50固定设计和身份”的可复现软件映射。真正Geant4/TCAD联合链路及课程结果必须由独立原档审计支持，不能用原100 Ω演示或新映射成功代替。

`locate`给出唯一global ledger路径与严格R50主响应键、匹配参考标签及后续delivery审查入口；它没有读取ledger，也不给未确认run ID。主代理/学生实际查看时须保持失败、缺失、临界、数值不确定；运行或未知状态不读raw、不自动重发。原生图另按两个预声明目标及真实目视证据验收。

实际学生执行本演示、2–3人分工、教师审核、资源交接、答辩和最终考核均未由本工具完成。输出一直保留`PENDING_REAL_STUDENT_EVIDENCE`；这是代理实现与软件验证，不虚构人的操作、审批或学习成果。

## 开发验证

私有入口`local_runtime/dram-see-v3/r50-demo-dev/self_check.py`只运行设计映射/错误拒绝及本地CLI，所有产物位于私有目录且注明SOFTWARE TEST ONLY。验证日志、稳定代码/manifest/hash与清单计数保存在同目录handoff。真实课程映射证据由主代理独立验收后另行生成；开发过程不提交求解、不读归档、不写生产数据或修改旧文件。
