# 原生材料账本稳定索引 r5

`transport_audit_indexed_r5.py` 是冻结 `transport_audit_r3.py` 的独立完整副本，`AUDIT_REVISION` 为 `indexed-r5-stable-material-ledger`。旧 r3、其原审计结果及失败证据保持原样；本文件不修改调度、请求、运行输入、物理表或科学容差。是否启用 r5 由根控制器的独立绑定与 release 决定。

## 唯一行为变化

原 `_material_ledger` 对每一条材料账本行重新遍历全部 steps；事件总量核对又逐事件扫描整个 ledger。r5 在原有账本唯一性/完整性检查之后，构建三种列表索引：

- `(event_id, pre_material)` → 原 steps 子序列；
- `(event_id, track_id, pre_material)` → 原 steps 子序列；
- `event_id` → `scope == event` 的原 ledger 子序列。

仅替换相应两个原筛选表达式（其中步骤选择包含 event/track 两种分支）。所有 zero rows、缺失/重复键、步数、能量 triplet、`close` 容差、`math.fsum`、事件闭合、particle/process 清单、核种身份及 miss 专项检查均保留。其他 30 个函数/class 的 AST 与 r3 完全相同。逆向还原索引代码、两个原筛选表达式及 revision 后，与原 r3 全文字节完全相等。

## 原生列表顺序证明

对原输入序列 S 的任一前缀，索引在遍历到元素 s 时，仅把原对象引用追加到键等于 key(s) 的列表末尾。归纳可得：每个索引列表恰好等于该前缀按原谓词筛选所得的子序列，元素身份、相对顺序和重复出现次数均一致。遍历结束后，该结论就是原 list comprehension 的完整结果。

事件材料键等价于旧 `event_id` 与 `pre_material` 两条件；track 材料键再加原 `track_id` 条件。`event_ledger` 先保留原 `scope == event` 条件再按 event 分组，证明相同。不存在匹配项时 `.get(key, [])` 仍为空列表。

因此 `math.fsum` 看到的是同一顺序的同一浮点值，不以增量 `+=` 替代，也没有排序、截断、取整、抽样或按沉积能过滤。所有 `require`、`close`、`_check_energy_triplet` 和 `math.fsum` 调用的 AST 与 r3 对应调用完全一致。

## 复杂度与代价

设 S 为步骤数、L 为材料账本行数、E 为事件数。被替换的筛选部分由 `Θ(S×L + E×L)` 降为构建索引及查找的 `O(S+L)`。源步骤列表顺序和数值求和仍完整遍历；索引额外保存约 2S 个步骤引用以及 event ledger 引用和字典键。

按材料汇总的少量扫描、原 archive/逐文件哈希、CSV 解析、完整机制审计及粒子/过程清单匹配均未优化。不能据此宣称整个审计函数的普适线性复杂度，或给出核次级多重性的耗时上界。

## 原档完整报告比较

比较脚本只在 `local_runtime/dram-see-v4/nuclear-closure-r1/audit-index-r5/dev/` 保存开发证据。对 P0 六份记录及 N1 `nc-r1-h-000`，每份依次调用原 r3 和 r5 的 `audit_init/audit_events(..., output=None)`；真实 `transport/audits-r3` 目录不写入。

比较对象是两个审计函数新返回的**完整报告**，只允许顶层 `audit_revision` 和 `audit_code_sha256` 不同。原 record、真实 archive、保存的 r3 审计文件和两份实现的哈希在读取中保持一致。新报告保存在独立 `dev/attempt2/`，不覆盖原结果。

第一次验证脚本还额外比较了 fresh r3 报告与根控制器保存的报告，因后者另有 `prior_material_r2_audit` / `recovery_scope` 包装元数据而停止；同次 fresh r3/r5 比较已通过。该开发脚本、两个输出及失败说明保留在 dev。随后仅去掉这个超出任务范围的额外断言，保留完整 fresh r3/r5 比较和原保存文件不可变检查；生产 r5 无需为此修改。

## 计时解释与未做项

最终实测计时和逐项报告引用见 `dev/attempt2/comparison.json`。每个案例仅一次固定顺序运行（先 r3 后 r5），服务器负载与文件缓存未控制；这是此主机、此原档的比较，不是随机化性能基准或普适时间上界。两种版本都重新执行完整原始证据检查。

七份原档的两个版本均通过全部 10 项检查；每对完整报告仅 revision/code hash 不同，原保存结果哈希不变。对 N1 的 1000 个初级、1118 条 tracks、64869 条 steps，本次总审计 wall time 为 r3 **65.036 s**、r5 **9.452 s**，CPU time 为 **62.953 s**、**7.359 s**。本次 wall time 比约 6.88；P0 的小案例有快有慢，不由这项测量推断所有输入都会同倍提速。开发比较命令最终退出 0。

本代理只做本地原档比较和静态差异证明，没有 SSH、原生输运、TCAD、重新采样或新增求解。孤立反例由独立 validation worker 负责，不能把本次无自然核见证的 N1 数据比较写成新核物理有效性证据。
