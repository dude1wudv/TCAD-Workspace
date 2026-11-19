# 原生源场审计 r1

当前先验证提取器，不是器件/源项通过声明。旧 r2/r3 失败不变。提取器只操作复制到独立后处理目录的真实 TDR，不保存或改写 TDR，不调用求解器。

`extract_fields.tcl` 默认读取旧 r2 A1 的五个 `gfield_0_access_des.tdr` 至 `gfield_4_access_des.tdr`。可提供 `tdr-files.txt`，每行一个不含目录的真实 TDR 文件名，替代默认清单；不能用编号推算时间。所有输出文件独占创建，重复运行必须新目录。

```text
svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl
```

适配器须分别记录真实 SVisual、wrapper/SSH、归档退出码；全部为0且 stdout 含 `FIELD_AUDIT_COMPLETED mandatory_errors=0`、`diagnostic-status.txt` 错误数0、完成文件数等于输入数，才算原生提取完成。异常 sentinel、缺文件、缺字段均失败；不能单看退出0。

输出 `field-measurements.csv` 保存原始 `G`、`XG`、`YG`、`ONE` 积分和命令错误；九ROI及不带Window的整个硅域各一项。`XG/G`、`YG/G` 是后续计算的实测生成量质心。零G时质心未定义，绝不填理论坐标。`ONE` 为真实网格表达式 `0*<HeavyIonGeneration>+1`，独立检查窗口面积；另保存X/Y硅域极值验证坐标单位。原始字段/材料名保存在 `field-inventory.csv`，TDR状态元数据另存，但不虚构直接时间戳。

坐标表达式证据：本机 SVisual W-2024.09 UG p237 `create_field` 和 p426 明确支持 `<field-name>` 运算；已完成旧 r2 原生 `list_fields` 输出有且仅有 `X`、`Y`、`HeavyIonGeneration`。因此使用 `<X>*<HeavyIonGeneration>`、`<Y>*<HeavyIonGeneration>`，不生成解析源或理论质心。实际乘积字段仍需本次原生运行验证。

源场积分单位为 µm²·cm⁻³·s⁻¹，乘积矩为 µm³·cm⁻³·s⁻¹；比值质心为µm。有效厚度1µm，转体积因子1e-12 cm³/µm³，乘元电荷和BE实际区间得到电荷。全帧审计将使用成功BE步/写出日志与PLT精确时间一一对应；只积分实测帧，保留legacy窗内、窗外实测电荷，暂不由五帧重建全波形。空间门槛仍是ROI0.05、质心0.01µm、时间0.5ps及总量5%；原生节点场积分与求解控制体积分不保证等价。

## 审计接口

`audit_fields.py` 只读原 solver archive 和 root 收集的 operation。`--extraction` 接受 operation 根目录或其 `collected`；真实 `field-extraction-record.json` 在 operation 根。记录绑定 operation JSON/tar、真实四个退出码、原 solver manifest/tar、原生输出、提取脚本和 TDR 前后SHA；本审计重新计算这些文件hash。

```text
python -B experiments/dram-see-v4/source-field-audit-r1/audit_fields.py snapshots <原solver-run> --extraction <operation根> --output local_runtime/dram-see-v4/source-field-audit-r1/audit-dev/<新名称>
python -B experiments/dram-see-v4/source-field-audit-r1/audit_fields.py full <真实r4-A1-mesh-run> --extraction <全gstep-operation根> --output local_runtime/dram-see-v4/source-field-audit-r1/audit-dev/<新名称>
python -B experiments/dram-see-v4/source-field-audit-r1/test_audit_fields.py
```

退出0仅代表所选模式的检查通过；失败exit1并保留错误与可用数值。输出 `audit.json` 的schema为`source-field-audit-r1`，`frames.csv` 逐帧记录真实BE区间、日志行、实测G/质心/面积。`snapshots` 验证稀疏帧来源与提取，只能得到 `NATIVE_SNAPSHOT_EXTRACTION_VERIFIED_NO_FULL_SOURCE_CLAIM`，`field_measurements_passed=false`。`full` 要求原档内全部动态gstep与接受步一一对应（起点状态排除重复积分），固定r4 A1/bit1/mesh输入和原门槛全部通过，才令`field_measurements_passed=true`。两种模式始终`overall_source_interface_passed=false`及`scientific_calibration_passed=false`，匹配A0和跨网格对照由root总审计独立完成；这些字段禁止被解释为旧r2/r3已通过。

全帧输出分别保留legacy的0–4ns、窗内、窗外电荷，TDR窗内量以及明确标识的“TDR窗内+实测legacy窗外”混合诊断。时刻中心使用区间中点，原生G波形对正确BE区间平均oracle检查；oracle仅用于误差评价，缺帧/缺坐标场不补值。实际五帧原生验证已完成，输出位于`local_runtime/dram-see-v4/source-field-audit-r1/audit-dev/old-five-first-audit/`；Center空间误差约0.059497，仍失败。

初版7项离线测试包括完整/缺失接受步、失败BE、重复写出、文件名不能定义时间、CSV缺失/重复/错误/非有限量、真实矩质心偏移、Center已知反例、时间偏移、窗外非零观测及未知退出码。当时全帧真实数据尚待r4求解完成，没有用合成测试宣称研究结果；后续实际状态见本文件末尾。

## 内存释放修订（audit revision 2）

原 `extract_fields.tcl` 保持原字节。全帧首轮后处理因持续累积plot/dataset被root明确终止；原TCAD归档未动。新增 `extract_fields_bounded.tcl` 仅在每帧末尾按UG p347 `remove_plots [list $plot]`、p343 `remove_datasets [list $data]`释放；字段/材料失败分支也清理已创建对象。每次释放记录命令与返回值；命令失败或非零返回增加mandatory错误，结束exit2，不能吞错。原44个数值测量外新增两条清理记录，原生积分/坐标表达式、ROI和全部物理门槛未变。

`field_contract.json` 与审计器常量共同声明两个精确SHA白名单，按实际执行hash选择对应仓库源码并验证。root适配器可把任一注册脚本复制成执行目录的`extract_fields.tcl`；receipt格式不变。bounded额外要求每帧两条清理成功证据且顺序正确，report记录 `extractor_source_file` 和 `native_memory_cleanup_verified`。使用新脚本前，先独立原生旧五帧验证，再执行全帧；不新增TCAD求解。

修订前审计器、契约、测试、README、原脚本、五帧报告/CSV/stdout及receipt完整快照在 `local_runtime/dram-see-v4/source-field-audit-r1/audit-dev/bounded-revision-r1/before/`，`snapshot-manifest.json` 保存原SHA。新增三项离线检查覆盖仅清理差异、清理顺序/异常/非零、白名单及缺失/重复清理证据；Tcl测试明确使用本地API桩，不代表原生执行。

## 删除对象返回语义修订（audit revision 3）

真实操作 `r2-a1-tdr-diagnostic-r5` 中，bounded-r1完成全部五帧数值提取，但十条清理检查失败、SVisual退出2。原生 `extract_fields.log` 显示 `remove_plots` 返回被删plot名，`remove_datasets` 返回被删dataset名；这与本机UG pp347/343写的`Returns Integer`和例子0不一致。该失败及bounded-r1文件保留，不能重新标成通过。

新增 `extract_fields_bounded_r2.tcl` 保持全部数值命令与顺序，仅修正清理成功定义：实际返回必须是单元素Tcl列表，且对象名与当前已加载的plot/dataset严格相等。空值、0、错名、多名及命令异常均失败。CSV在`native_field`列记录被请求删除的对象，保留原始返回值；status声明`cleanup_success=exact_deleted_object_name`。审计器把它与同一帧原生inventory中的plot/geometry名字再次比较，不凭文件编号猜对象名。

三份脚本各自有固定SHA与独立成功语义；旧bounded-r1仍要求其原先的0返回，新成功定义不追溯套用旧失败记录。`audit_revision=3`只改变注册的清理语义，全部物理阈值不变。修订前六文件和失败操作的完整文本证据快照在`audit-dev/bounded-revision-r2/before/`（原失败tar保留并记hash）。12项离线测试通过，覆盖正确对象名、0/错名/空/多名/异常返回、inventory不匹配，以及旧r1对名称返回继续失败。

root已用新脚本完成原生五帧操作`r2-a1-tdr-diagnostic-r6`，四个实际退出码均0，严格审计位于`audit-dev/old-five-bounded-r2/audit.json`。220项原始数值记录与旧成功提取完全一致，另有10项清理返回核验；等价性证据随operation保存。该五帧成功只验证提取器，不改变粗网格Center失败。完整205帧后处理使用独立操作`r4-a1-mesh-tdr-diagnostic-r2`；最终验收以[阶段报告](../stage2/report.md)为准。

完整205帧提取现已完成，四个退出码均0、mandatory错误0，410项清理检查通过。全帧审计`audit-dev/r4-a1-full-bounded-r1/audit.json`的九项检查通过；204个实际BE区间加1个边界帧，没有补造帧。TDR窗内电荷1.004156993 fC，Center占比0.828711637、绝对误差0.013989156，通过原门槛。root另外完成匹配A0和粗细响应比较，见阶段报告。此结果仍不升级旧粗网格失败，不表示三维器件验证或器件校准完成。
