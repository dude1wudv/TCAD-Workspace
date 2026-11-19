# 几何候选实施记录

| Rung | 交付 | 唯一检查命令 | Tier | 状态 |
|---|---|---|---|---|
| F0 | 冻结输入→关闭执行的双维候选计划 | producer.py prepare --package <packages-r2> --output <runtime>/spine | MUST | 退出0；原骨架保留 |
| F1 | 有依据的原生测量脚本与比较器 | 新几何生产者离线套件 | MUST | 15项退出0；双维Tcl mock通过 |
| F2 | 缺失/篡改/来源拒绝与原消费合同兼容 | 同一新套件完整运行 | MUST | 与F1同次套件验证，未重复计数 |

## Run record

2026-10-16：用户明确授权唯一heartbeat重建及本离线候选；任务dram-see-v4已ACTIVE/30分钟并绑定当前会话。当前本机编辑占用已登记。原29项不重跑。

最终候选在`local_runtime/dram-see-v4/s2-geometry-r1/20261016T135638Z/candidate-r1`，9文件加candidate.json；清单SHA `fec305990fc65b6fe3835dc2086ecb55b1a359645b5927f6f7aa48f59b5d5ec0`。生成命令为既有Python `-X utf8 -B producer.py prepare --package <冻结packages-r2> --output <runtime>/candidate-r1`，退出0，原始输出`prepare-candidate-r1.log`。

独立验证：`local_runtime/vdmos-analysis-venv/Scripts/python.exe -X utf8 -B -m unittest discover -s experiments/dram-see-v4/s2-evidence-r1/geometry-producer-r1/tests -p test_geometry_producer.py -v`，最终15项/exit 0；初次3项因测试夹具重用目录报FileExistsError，worker只修获准测试，原日志保留。原29项通过记录复用。

本机Tcl 8.6.12隔离mock执行双维SVisual候选，2/2完成、零mandatory errors；exec被mock拒绝启动任何外部进程。初次harness的Python参数错误和修正后日志均留在`validation/`。SDE Scheme及真正厂商API未执行、不宣称语法通过。

实现期审阅纠正了手册integer 0与实际删除对象名的返回差异，沿旧原档实测方式处理，见G015。same-family扫查初轮2项未声明语义，后补G016/G017，未改业务逻辑；复核未声明项0、stale 0，仅provisional。初轮记录保留，不追认事前登记。

完整记录`validation/validation-summary.md`、`assumption-review-r1.json`、`assumption-review-r2.json`、`protected-final.json`。42份既有保护对象与28份attempt未变；冻结100文件包的已有验收复用。本轮仅新源候选的必要检查，无Git提交（用户明确禁止），无原生/SSH/编译/提取/训练或预算预约。

## Deferred

实际SVisual/mesh测量、原生语法与数值有效性、策略审批、采集补丁应用、执行输入/预算/发布、完整G1/G2均不在本轮。

## Blockers

原PMI实际BE未更新、R12未编译/发布保持。无新增原生授权。
