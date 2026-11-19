# 原生零迭代收敛语句的全帧索引修订

原 `qualification-zero` 求解 `20261015T061444Z-v4-nuclear-closure-r1-qualification-zero-fcbd4da7` 正常完成并归档，真实本地 runner/SSH/远端退出为0。完整0–4ns曲线、原957个BE步骤和69个源激活窗TDR均保留。旧后处理在创建任何原生字段操作之前拒绝首帧，错误为 `TDR lacks a successful BE step: gstep_b003_0000_access_des.tdr`。

根因是句式覆盖缺口。旧索引器只识别 `Error smaller than 1` 或 `Rhs smaller than`，原生 W-2024.09 的全部零源步骤使用精确终止句 `Finished, because |RHS| is less than 1.0000e-10.`。首帧对应0.984→0.9841ns的真实接受区间，不是可跳过的块起点快照。诊断及逐帧证据保存在 runtime `field-index-r7/`。

独立 `field_audit_index_r7.py` 的新增 `native_index_frames` 保留原BE语法、原日志行号、打印精度匹配、拒步标志、单一PLT区间、完整写帧清单及唯一接受区间要求，只在成功标志中增加上述精确语句。未知或近似句式不予接受。原始日志不改写，`0000` 不跳过，源窗口全部69个区间都必须进入原生字段审计。后续原生TDR中PMI时间/步长/BE类型、xyz、体积、源积分、分区、波形及电路和数值门均保持。

`acceptance_field_r7.py`、`campaign_field_r7.py`、`continue_fields_r7.py` 只改独立字段/验收模块及新发布文件的绑定；它们不改变求解输入、源模型、求解器、物理门槛或预算。原 `field_audit.py`、验收/调度源码和失败日志全部保留。新入口由 `release-fields-r7.json` 和 runtime `active-entry.json` 放行。

本次恢复复用原已成功TCAD目录和原输入，不增加求解调用。只有字段提取操作将按实际新增后处理成本计账。原TCAD 1/18、输运正常17/107和纠错1/2、不同初级100008、工程5次均保留；后续以原始attempt重算。原生字段尚未完成前，不发布零源科学gate或放行正点源配对。字段gate通过后由同一唯一调度者接续。

本修订仍使用原所有权锁、严格SSH、共享solver锁、单计算线程与单核。不启动旧入口、不重复提交已知或未知作业、不删除失败档或必要帧。识别原生成功句式不替代科学验收，PMI加载/符号/双载流子和完整器件闭环仍须各自通过。
