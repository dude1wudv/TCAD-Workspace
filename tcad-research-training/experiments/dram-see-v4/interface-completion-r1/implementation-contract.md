# 完整二维验收：本轮实现契约

依据用户批准的下一轮计划执行。root唯一调度，子代理不得SSH、求解或递归派发；旧物理实现、合同、审计和原档冻结。新物理输入位于source-interface-r5，新通用场提取/审计位于source-field-audit-r2，本目录由root负责协调、资源、报告和调用入口升级。

## 已选实现接口（先于依赖代码登记）

- 数值profile使用`main/time/fine`三个显示标签，分别是(mesh_scale,pulse_max_step_s)=(0.5,5e-13)/(0.5,2.5e-13)/(0.25,5e-13)。`variant`仍保存profile标签以兼容现有读取，但物理条件独立存储；不把旧r4的mesh改名写回原档。
- 新builder提供`contract()`、`code_hashes()`、`source_spec(case)`、`offline_proof(spec)`、`render_deck(case,bit,variant)`、`check_role(case,bit,variant)`、`build(output,case,bit=1,variant='main')`、`check_project(project)`。CLI保持build/check/plan及--case/--bit/--variant。返回check结果含case_id/stored_bit/variant/manifest_sha256。
- 继承r2已登记各人工source-spec的物理数值及显式xyz；修正后的时间oracle继承r3（sigma=s_hi），不调用r2错误时间公式。source-spec可保留原schema/物理event ID作为兼容引用；新run/schema说明真实修订。
- 新parameters.schema为dram-see-v4-source-interface-r5；保留已有matching_contract与其SHA字段，并显式独立保存case、bit、mesh、pulse step。新source contract含17个roles、两项复用角色及累计26/本轮21/primary17/reserve4预算。A0/A1 bit1 main只允许构建离线复用参考；若重算须走reserve，不能冒占primary。
- source_contract中的11个ROI始终完整登记，前9个与r4一致；新增SourceLeft=[0.295,0,0.355,1.2]和SourceRight=[0.495,0,0.555,1.2]。新增窗口的验收适用于A5/A6/A7；其他案例仍可输出但不增加未批准的新门槛。old 9 ROI与所有数值门槛不变。
- 场提取采用每帧释放、严格核对删除对象名的原生修订；保留原field-measurements/inventory/metadata/status格式和原生exit sentinel，使root继续生成同schema的field-extraction-record.json。每个实际接受步必须对应原始Writing与精确PLT，起点帧不重复积分。
- 新场审计提供`audit(run,extraction,mode='full',output=None)`与原CLI形状，输出schema=source-field-audit-r2。必须输出passed/field_measurements_passed/audit_sha256/field_contract_sha256/run_id/archive_sha256/manifest_sha256/audit_tolerances/checks/errors，保存frames.csv。支持新r5有源角色；零源不伪造质心或未测字段。旧r4 A1的已通过报告由独立bridge核验，不要求重做已有全帧后处理。
- 新综合审计放在source-interface-r5/audit_interface.py，API `load(run,project=None,field_audit=None)`返回summary/parameters/source/curves；`write(output,bundle)`保存报告/完整曲线。CLI audit与compare子命令。compare接收a/b/ca/cb四个bundle并按mode=equivalent/segment/refinement比较；CLI可通过显式evidence registry给每个run的project/field-audit/role。没有匹配A0不得给控制相对扰动通过结论。
- 复用桥只接受登记的r4 A0/A1及对应通过的原审计/比较。canonical物理匹配仅允许已登记variant标签别名；数值、几何内容及actual mesh、电路、初态、单位、时序和物理源均逐项核验，不笼统忽略版本差异。

## 冻结调用序列

1 A4/1/main; 2 A5/1/main; 3 A0/1/fine;
4 A6/1/main; 5 A7/1/main; 6 A2/1/main; 7 A3/1/main; 8 A8S2/1/main; 9 A8S4/1/main;
10 A0/0/main; 11 A1/0/main; 12 A4/0/main;
13 A0/1/time; 14 A1/1/time; 15 A6/1/time;
16 A1/1/fine; 17 A5/1/fine.

失败只暂停依赖。多轨迹需bit1 A4通过；A6/A7及A5细化需A5通过；各bit/数值条件需匹配A0。A4与A1、A7与A5用equivalent；A8与A1用segment；time/fine与各自main信号用refinement，各自减去同条件A0。A3按预计算域内约0.5fC，不能按总1fC验收。

## 权属与边界

- pipeline_gap独占source-interface-r5/build_interface.py、source_contract.json、README.md、test_interface.py及其runtime构建/测试目录。
- mentor_evidence独占source-field-audit-r2全部文件及对应runtime开发/测试目录。
- device_literature独占source-interface-r5/audit_interface.py、reuse_bridge.py、test_audit_interface.py、audit-README.md及对应runtime audit-dev目录。
- root独占本目录、stage2/source_control.py及其升级快照/新调度测试、原生提取适配/回收、资源检查与清理工具和实际launch/operations。

真实求解前各模块须完成离线反例检查并冻结哈希。所有旧文件只读。验证worker不可用时由root接管，不能换模型绕额度。执行记录一旦创建即保守计一次调用；未知退出状态不重提。后处理不计TCAD次数，但保留成本和失败。
