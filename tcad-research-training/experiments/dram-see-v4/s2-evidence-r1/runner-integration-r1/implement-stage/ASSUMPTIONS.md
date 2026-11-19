# 接线假设与接口决定
<!-- ASK mode: never -->

| ID | 未定项 | 选择 | Class | Source |
|---|---|---|---|---|
| I001 | 集成与冻结边界 | 仅生成新候选和相对原runner/capture-r3的补丁；原始源码、冻结包、验收与失败档保持；不是第二runner | interface | user |
| I002 | 两次几何提取预算 | D2/D3各1次 native_geometry_extractions；A0-b0/b1各1次原字段提取，总4次SVisual。单独S2账本未来授权，旧nuclear余量不可转借；失败/未知预约计费，无自动重试；当前批准/预约/消耗均0 | semantic | default |
| I003 | 原始mesh退出来源 | 候选将sde:build-mesh替换为save-tdr-bnd/get-body-list和write-cmd-file cell.cmd；原runner显式snmesh --threads 1 --max_threads 1 cell，只建1次mesh。资源guard在mesh成功后、SVisual/SDevice前；不以SDE退出代替mesh退出 | semantic | default |
| I004 | 执行顺序 | D2/D3固定sde→snmesh→几何SVisual→SDevice；SDE观测在同一CAD进程末尾，geometry比较在SVisual后、SDevice前、原tar冻结前。失败阻止后续step，仍由原runner收失败原档 | interface | default |
| I005 | 退出名映射 | 保留capture原始step退出文件；规范sde/mesh/svisual-exit-code.txt逐字复制其明确映射。非零保留，缺失拒绝，不从JSON/整体wrapper退出补0。capture admission退出与native退出分开 | semantic | default |
| I006 | context来源 | 原runner冻结的精确run ID、计划/脚本/实际mesh SHA及原始退出文件生成context；非原生合成只能在隔离夹具且所有结果标synthetic，不产生原生资格 | semantic | default |
| I007 | 发布前关闭 | 新接线路径额外检查execution release、geometry release、批准策略、独立几何预算预约及输入绑定，候选均false/null。旧执行路径及原owner/严格SSH/共享锁/单核不变 | interface | default |
| I008 | A0复用 | 两A0只导入已明确验收D3原档中的同一mesh、几何证据及原始生产者context；保留D3 producer_run_id，不冒充A0重测；D3原档/manifest/验收绑定缺失拒绝，A0不调用几何SVisual或重建mesh | semantic | default |
| I009 | 比较与科学资格 | 原evaluate.py及比较策略原样复用；桥接仅追加原始退出/发布来源绑定至同一报告证据清单，不改变数值判断。checks通过不表示G1/G2或完整科学验收 | semantic | default |
| I010 | 实际run身份与资源账 | 集成路径使用未来发布指定、尚未使用的exact run ID，原runner仍创建唯一目录并拒绝重复。原4CPU小时/8GiB首切片提案不增加，几何调用必须包含在该包络且先补实测/预测；当前成本未知不编造 | interface | default |
| I011 | D3来源与A0当前release同名 | 原D3发布/策略/预算/授权/input-manifest按字节复制到geometry-producer-bindings/并纳入几何报告证据hash；A0只复制此命名空间和原观测，保留自己根execution-release；不回写D3原档 | interface | default |
| I012 | 发布清单循环引用 | execution-release绑定input-manifest_sha256与geometry_release_sha256，release本身不入该input-manifest；清单覆盖payload/脚本/资源策略/授权/预算，避免互相hash循环；尚未发布仍拒绝 | interface | default |
| I013 | 几何与角色预约关联 | 几何预约与本角色execution-release使用同一新S2 budget_id及账本快照SHA，几何reservation ID独立，不借旧账postprocess。初始准入同时检查资源策略已批准/启用，真实资源仍由原guard及owner现场核对 | semantic | default |
| I014 | 完整桥接合成验证 | 仅Python内部fixture入口允许隔离标记目录中的合成数据，并强制synthetic与关闭execution；CLI/原生路径拒绝该标记。调用未改动的evaluate合成模式，报告永不产生native资格 | interface | default |

I003 API依据来自已存厂商文档：SDE save边界p760、write-cmd-file p596、get-body-list p402；Mesh p13–14默认cell输入输出及单线程开关。本轮未运行这些API。
