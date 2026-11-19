# TDR 每步源场后备方案（候选，未放行）

2026-10-13。只读调查后记录；未改 r2/r3 deck、合同或调度，未新增求解。r3 实测 legacy/no-window 总量约 1.004164 fC，而两类 Window 的 HI 积分仍全零；Temperature 窗口非空，故补 z 可解决 HI 窗口的假说已被本次结果否定。r3 失败保留。

**原生语法。** 在既有 0.95–1.05 ns 注入 `Transient` 体内，保留 `Coupled` 和原 `Plot { ... HeavyIonGeneration ... }` 字段列表，候选增加：

```text
Plot(FilePrefix="gstep" Time=(Range=(0.95e-9 1.05e-9)) NoOverwrite)
```

本机 SDevice W-2024.09 UG pp193–194 的 `Time=(range=(0 1); range=(0 1) intervals=4; ...)` 例子明确区分：无 `Intervals` 的范围输出其中所有计算时刻；指定 `Intervals` 会强制求解指定时刻。故这里不写等间隔 200/400 点、不改原 `MaxStep=0.5ps/0.25ps`、不用会忽略其他 Plot 的 `MinSpacing`。Table355 pp1788–1789 另列 `IterationStep=1`，本候选无需叠加它。`NoOverwrite` 为逐文件编号；混合模式确切文件名以实际日志为准。范围内至少约 200/400 个正步长区间，失败重试/更小自适应步可增加文件数，不能硬编码数量。

**时间与完整性。** 保存完整 `transient_des.log`、原生 device/circuit PLT 和全部 TDR。生成不可变索引：TDR 文件/hash → `Writing` 行 → 此前成功完成的 BE 步 → 同序 PLT 的精确 `t_prev,t_end`、`dt`。日志打印精度只用于交叉核对，PLT 提供精确时刻；拒绝失败尝试、遗漏步、重复计步、不唯一映射。窗口起点已有状态不是新增正区间，不重复积分。每个区间结束须有一份真实场，末点到 1.05 ns；不能从编号或请求 `Time` 赋“实际时间”。历史 TDR state metadata 未提供直接时间戳，必须如实保留此限制。

**后处理及门槛。** 复用已成功的原生 SVisual `load_file -alldata` → `create_plot -dataset` → 显式 `-plot/-geom`，串行逐文件提取同九 ROI、总硅域、质心及 `0*<HeavyIonGeneration>+1` 的域面积，逐帧校验字段/有限量/状态码与前后 SHA。已有五帧符合 BE 区间平均，但这是实测证据，UG p812 的措辞仍是 instant generation rate；新全序列须独立核验其区间平均波形。量纲为原生面积积分 × 有效厚度 1µm × 1e-12(cm³/µm³) × e；电荷用 ΣG_iΔt_i，时间质心用区间中点。空间质心按各帧实测生成量加权；绝不用理论场、五帧插值或拟合波形补缺帧。原 5%/ROI 0.05/质心 0.01µm/时间 0.5ps 门槛不变。

**边界与代价。** 注入窗全帧只能直接证明该窗积分；若要严格 0–4 ns 总量，保留原生 legacy 总量作独立实测，或在每段 Transient 用各自起止 Range 保存所有接受步（须预冻结额外磁盘开销）。不得以解析尾部替代窗外实测。SVisual 节点场积分不是求解控制体积分；历史 Center/Total=0.783205 与解析 0.842701 差 0.059496，仍超过 0.05，需要真实网格细化检验，不能据后处理成功称空间通过。窗口 Temperature 面积偏差也提示窗口离散选择，不能归因后自动放宽。

现有五 TDR 不能回填全时序；候选需一次新的 A1 求解，计入全局 19 次预算（已用 3）。若继续网格细化，需对应 A1(mesh) 与同网格 A0；基准复用和实施顺序由 root 冻结，当前不执行。旧 runner 归档整个工程，能收集动态编号 TDR，但 `outputs` 只允许简单固定文件名；需由新审计依据日志和 PLT 验证全体动态文件，不能把固定五文件检查当完整性证明。

依据：`local_runtime/dram-see-v1/sdevice_ug.pdf` pp149,193–194,1788–1789；`scripts/tcad.py` 归档及 outputs 校验；`source-interface-r2/diagnostics/inspect_tdr_r3.tcl` 的已验证 API；`local_runtime/dram-see-v4/source-interface-r2/audit-dev/tdr-diagnostic-r3/saved-step-time-shape-diagnostic-erfc.json` 的真实 BE/写出关联。以上路径相对仓库。
