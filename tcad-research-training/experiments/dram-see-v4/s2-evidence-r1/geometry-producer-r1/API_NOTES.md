# 原生观察脚本候选的 API 依据与边界

`native_scripts.py` 只提供 `render_sde(plan)`、`render_svisual(plan)`，返回源文本，不启动程序。两者均未在原生解释器运行；文档支持不等于语法验证、测量完成或科学验收。原冻结 deck 由主生产者复制后追加观察器，本文不授权原生构建、求解、提取或训练。

本实现对应 `implement-stage/ASSUMPTIONS.md` 的 G004、G009、G011、G013。名义几何、expected 与 tolerance 不会写进原始数值列；它们由独立比较器使用。

## 已安装文档

只读使用本机 W-2024.09 手册，未复制商业文档正文到版本控制：

- `local_runtime/dram-see-v4/three-dimensional-pilot-r1/references/sde_ug-installed-private.pdf`，下表的 SDE 页码也是 PDF 页码。
- `local_runtime/vdmos-tid-training/references/svisual_ug-installed-private.pdf`，下表的 Visual 页码也是 PDF 页码。
- `local_runtime/dram-see-v1/svisual-api.html`，Python API 索引用于交叉核对；生成器实际写 Tcl API。
- 已有摘录 `local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/cad/sde-666-680-private.txt` 行 280-320 同时记载两个接触实体查询入口。

| 用途 | 使用的文档接口 | 依据 |
|---|---|---|
| 实际接触集合 | `(sdegeo:contact-sets)` | SDE p620 |
| 2D 接触实体与长度 | `(sdegeo:get-contact-edgelist name)`、`(edge:length edge)` | SDE p673、361 |
| 3D 接触实体与面积 | `(sdegeo:get-contact-facelist name)`、`(face:area face)` | SDE p674、386 |
| 实体精确包围盒 | `(bbox-exact entity-list)` 返回 `(min-pt . max-pt)` | SDE p350 |
| 坐标分量 | `position:x`、`position:y`、`position:z` | SDE p440-441 |
| 接触点匹配 | `find-edge-id position body`、`find-face-id position`，前者过滤到 `(get-body-list)` | SDE p393-394、402 |
| 样点实体归属 | `(find-body-id position)` | SDE p391 |
| 实际区域/材料属性 | `(generic:get body "region")`、`"material"`；p400 示例列出这两个属性 | SDE p399-400 |
| 固定路径的文件保护、完成标记 | `system:command` 返回状态，失败用 `sde:error` 报错 | SDE p323 |
| 读取原网格与建图 | `load_file path -alldata -name name`、`create_plot -dataset ds -name name` | Visual p331、239 |
| 原生库存 | `list_materials -dataset ds`、`list_regions -dataset ds [-material name]`、`list_fields -dataset ds` | Visual p322、325、319 |
| 接触库存 | `list_regions -dataset ds -material Contact`；接触是材料及其区域 | Visual p136、322、325 |
| 真实场积分 | `integrate_field -dataset ds -field field [-regions list|-materials list]` | Visual p309-310 |
| 场极值及坐标 | `calculate_field_value -dataset ds -field field -min|-max [-regions list|-materials list]` | Visual p227-228 |
| 坐标场值 | `probe_field -plot plot -field field -coord point` | Visual p339 |
| 内存常数字段 | `create_field -dataset ds -name ONE -function {0*<X>+1}`；公式通过 `<field>` 引用原有场 | Visual p237、426 |
| 释放本观察器拥有的对象 | `remove_plots list`、`remove_datasets list` | Visual p347、343 |

## 输出与失败行为

SDE 观察器读取已经构建好的实际 CAD 对象，逐接触导出实体数、实际边长之和或面积之和及包围盒。接触探针记录全局匹配数和唯一匹配实体是否属于指定接触。材料探针记录 `find-body-id` 的实际匹配数；只有恰好一个 body 时才读取其区域与材料属性，否则写空名称，由比较器拒绝。以上不改变几何、接触或掺杂。

SDE 输出为 `sde-contact-measurements.csv`、`sde-contact-probes.csv`、`sde-material-probes.csv`。固定路径的存在性检查连同符号链接检查拒绝旧文件；标准 Scheme 输出端口依赖现有唯一写入者和共享锁，不另建调度锁。三个 CSV 全部关闭后，才以 shell noclobber 独占创建 `sde-geometry-status.txt`，内容精确为一行 `S2_SDE_GEOMETRY_OBSERVATION_COMPLETED`。中途失败保留部分证据；没有完成标记不能消费为完整观察。

SVisual 运行时只把 `mesh-input.tcldata` 当作三个元素的 Tcl 列表读取：`path expected_sha producer_run_id`。不使用 `source` 或 `eval`，不执行其内容，不以计划中的占位网格替代输入。prepare 不产生有效输入描述符。未来原 runner 必须在已授权、已发布的原归档冻结前提供真实输入与 context。

SVisual 用 `sha256sum -- path` 在读取前和释放后分别观测 `BEFORE`、`AFTER` 指纹，保存在 `mesh-identity.csv`。这要求未来环境已有 `sha256sum`；缺失或指纹不符会记录错误，不安装、不切换校验实现。输出库存区分物理材料和合法的 `Contact` 材料，具体集合由比较器核对。

`material-measurements.csv`（包含 units 分类）、`contact-measurements.csv`、`doping-measurements.csv` 的字段均为 `id,raw_value,command_status`。原生返回值完整保留，包括极值 API 返回的数值和坐标列表；失败保留错误原文并标记 `ERROR`。不填期望数值、不补零。CSV 由 Tcl `CREAT EXCL` 创建，所有输出均拒绝覆盖。

SVisual 记录本观察器新建的 plot/dataset，与开始时已有对象区分；正常和命令失败路径均尝试释放。释放命令失败、对象仍存在、文件关闭失败都会使 `geometry-status.json` 中 `completed=false`。这个状态只表明观察脚本是否完成，不产生 geometry-validation 通过报告，不代表 native 资格。

释放返回值按G015采用已完成原生运行的实际证据：`transport-probe/operations/nc-r1-fields-qualification-zero-trace-r10/collected/field-measurements.csv`第74–75行返回恰一个被删除对象名，原退出0、69/69帧完成；虽然手册p343/347记integer 0，本候选沿原提取器逐对象匹配删除名称并检查库存消失。最初候选的仅接受0假定已在本轮首次原生前审阅中纠正，未据手册去重跑旧原生。

## 不得据此扩大解释的事项

- 2D 物理 `x,z` 映射为 native `X,Y`，native `Z=0`；3D 保持 `X,Y,Z`。这是本冻结 CAD 合同的坐标约定，不是 Visual 自动将物理 z 改名为 Y 的保证。`probe_field` 文档要求 2D 第三个坐标为零或省略。
- 坐标字段 `X/Y/Z` 与掺杂场名必须出现在实际场库存中；手册不保证每个 TDR 含有这些字段。缺失即失败，不创造坐标或改用名义范围。`ONE` 仅在内存由实际 `X` 场构造，不写回网格，原场库存不把它冒充为原生输入字段。
- 2D 区域积分是面积，3D 区域积分是体积；不乘 `AreaFactor`。Visual p160-161 列出的积分支持单元没有线单元，因此二维接触长度只由 SDE 的真实边长得到。3D 接触测量来自 CAD face，不等于最终网格离散接触面的独立测量。
- `face:area` 文档对不能解析求面积的几何记载固定精度 0.001；本候选没有证明其原生数值误差或改变比较容差。任何不满足已发布策略的实际数值都必须失败。
- 坐标式 `probe_field` 没有受文档支持的材料过滤；`-region` 用于 `-point vertexID`，不能与坐标式探针混称材料归属。生成器要求 probe 的 `entity_kind=all`。同次 SDE 材料探针提供 CAD 归属，最终 mesh 库存与区域测度提供另一步核对，仍不构成每个 mesh 样点材料的独立查询。
- 本机文档未提供 `list_contacts`、`get_mesh_data`、`get_field_data`、`export_mesh` 或 `export_dataset` 的可用依据；生成器不调用它们。`get_region_prop` 只有显示属性，`export_variables` 是曲线变量接口。
- 有限接触点、材料样点、坐标极值和积分不是全域拓扑或掺杂证明，也不是收敛验证。原生语法、真实返回值、字段可用性、资源释放以及测量精度都仍待对应授权下的实际验证。当前调用、预算消耗和资源预约均为零。
