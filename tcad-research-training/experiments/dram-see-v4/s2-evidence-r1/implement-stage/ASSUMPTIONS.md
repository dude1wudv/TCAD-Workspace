# F5–F7接口假设账本
<!-- ASK=never; offline preparation explicitly authorized; native authorization remains zero -->

| ID | 未确定项 | 本次选择 | Class | Source |
|---|---|---|---|---|
| E001 | 旧runner缺少实测字段 | 每个fact记录observed/inferred/unavailable及原文件/成员/hash；COLLECTED不补成collection_exit_code=0，set-e不补成逐工具原始退出码，父shell affinity不充作SDevice实测 | semantic | user |
| E002 | 原S2与真实affinity格式不同 | 新适配器接受严格单核整数和既有Threads/Cpus_allowed_list两行格式，分别标出处/观测对象；任何多核或Threads非1均拒绝，旧S2文件和门槛不改 | interface | default |
| E003 | 未来如何补采而不改旧runner | 只生成针对既有runner/operation的未应用最小补丁，不部署副本、不执行补丁；候选加入实际逐工具退出、归档SSH返回、共享锁成功记录及工具进程/proc单核观测。未知/过短进程保持缺失，不猜值，不杀进程或自动重跑 | interface | default |
| E004 | 新原生资格入口 | 新只读适配器复用冻结安全Archive、全帧索引、TDR四阶段hash和数值门；新增观测/发布/几何绑定必须全部有真实证据才可通过字段门，整体native资格始终另需G1、配对与细化，不修改旧函数全局 | semantic | default |
| E005 | 完整解析正常路径测试 | 仅在隔离UNIT_FIXTURE_NOT_NATIVE中构造显式synthetic归档；正常路径测试不产生native receipt或真实资格，公共native入口必须拒绝synthetic。测试调用无外部进程，禁止把旧事件/曲线变成新S2样本 | semantic | user |
| E006 | 真正的几何审计尚无数据 | geometry-contract是名义描述，不能改名当native manifest；实际几何报告须绑定mesh、材料/接触/掺杂测量文件及通过项。缺失则拒绝，不凭nominal hash判通过 | semantic | user |
| E007 | F7预算与资源未知 | 首4角色/2mesh/2字段提取/4CPU小时/8GiB仅提案；所有实际资源null，8/20/4/160GiB门不变。发布候选引用真实SHA但不生成project.json，不预留或转移旧预算 | interface | user |
| E008 | 每次调用身份与测试来源 | runner事实按step-序号-tool记录，首4每角色恰有一次SDevice；collector拒绝多个SDevice以免拿最后一次冒充前次。新执行manifest明确origin=native_pipeline/synthetic=false；单测manifest明确synthetic_fixture/true且有隔离marker，公共原生审计拒绝单测来源 | interface | default |
| E009 | 接口/采集版本与授权绑定 | 执行release必须绑定新evidence/audit源码SHA、实际runner/operation SHA、作用role的原始授权证据SHA；单测用显式synthetic授权，公开native入口仍拒绝。几何校验报告来源与测量文件hash绑定，不声称该收集器替代未来原生几何校验生产者 | interface | default |
| E010 | 同名进程不能单独证明工具身份 | collector必须消费capture的process-observation：严格tool Name、PID/PPid/starttime父子链、安装目录内精确可执行文件名及原始status SHA绑定；仅status或父shell不足。solver还须独立process-admission及其真实退出为0，不能用tool退出替代。缺失列unavailable，错绑拒绝；合成夹具同样显式标记并仅供解析测试 | interface | default |

科学参数、时间/空间/电荷门沿原r13与S2冻结合同。内部文件命名不是科学假设。后续新增接口/含义取舍须先追加本表。same-family假设扫查只作provisional，不声明跨家族审查通过。
