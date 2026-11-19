# 当前执行检查点（2026-10-13）

## 当前终态：细网格诊断通过，扩展矩阵尚未完成

五次SDevice均已COLLECTED、runner/SSH退出0，没有活动求解。全局5/19次，不得按修订重置；覆盖四个原角色，15个未尝试角色与14次余量不相容。原粗网格A1空间失败保留。后续先明确主网格和角色/次数分配，建议首项为合格细网格上的bit1 A4。当前r4合同仅A0/A1 mesh，不自动将其余角色换网格。详见report.md、remaining-checks.md；这些状态覆盖下面所有历史运行中说明。

r4 A1 run `20261013T135733Z-v4-source-interface-r4-a1-b1-mesh-b66a8e0d`于14:49:32 UTC归档，solver3075.54s。完整205帧（204接受区间+1边界）后处理`r4-a1-mesh-tdr-diagnostic-r2`于15:27:51 UTC结束，SVisual/SSH/remote/collection全0、原TDR前后SHA一致。首轮后处理内存累积，root精确核对后SIGTERM，实际SVisual15；bounded-r1五帧误判API对象名返回，实际SVisual2。失败均保留。新bounded_r2五帧成功且220个数值与旧提取完全相同，之后才做全205帧。

最终field audit：`local_runtime/dram-see-v4/source-field-audit-r1/audit-dev/r4-a1-full-bounded-r1/audit.json`，九门通过。auditor SHA `e19273aaae335597593f9fbfa69f1f5facaaf3966151b44aad8c0dfe4c4371f2`、contract `33c36c2e2ae31f6d3eabe46ae82cbde83172f99ca8e81936be86f55cb0595151`、新Tcl `d540b0b425bd785abba341e868114f7207ef2def60b6f7a3f19a9ab334f54356`已冻结。不要改这些文件使已归档审计失效；未来修订另存版本。

root源审计：`local_runtime/dram-see-v4/source-interface-r4/audits/r4-a1-b1-mesh-r1/audit.json`通过。匹配比较：`local_runtime/dram-see-v4/source-interface-r4/comparisons/a1-base-to-mesh-r1/comparison.json`通过。TDR生成1.004156993fC，Center误差0.013989156；legacy粗细Q相对差6.81598e-6，SN扰动差0.469468mV、BL0.043218mV。main_grid_accepted及numerical_convergence_validated仍false，不把单组工程比较写成校准或完整收敛。结果图已目视检查：`stage2/figures-mesh-r1/mesh-diagnostic.png`。

核见证212事件/9个合格事件，三份3D账本和Shin原图证据已完成；Park目标原图未取得。真实3D入口拒绝未定义降维，训练/正式160/新尺寸批量/空间谱/3D器件响应均未启动。旧心跳未恢复，无Git提交推送/安装/外发。validation_worker配额不可用，root接管验证，没有换模型绕过。

## 以下为保留的历史检查点

## 历史：第5次r4 A1 mesh运行中（14:02 UTC）

A0已13:56:39 COLLECTED/SSH0，run `20261013T132129Z-v4-source-interface-r4-a0-b1-mesh-5a893127`，archive SHA8e5fc4fe9a9e22bae7a6a25a22e4be676dc68cada94f9ff0df55ab189100b57f。root总审计`runtime/source-interface-r4/audits/r4-a0-b1-mesh-r1/audit.json`通过，HI原生字段全部实测0、数值generated_fC=0（不是缺字段猜零）、完整曲线/守恒通过；solver wallclock2070.42s，meshSHA cc289c060e909b62bc4524a5080c985255fad630de335e0049726c63fb12cc97。`stage2/check_frame_index.py`对真实A0全帧索引通过：205TDR=204接受区间+1窗口起点，0.95–1.05ns完全覆盖，证据runtime/r4/audit-dev/a0-real-frame-index-r1/frame-index.json，仅时间映射、不宣称A0场提取。

当前唯一原作业：`r4-a1-b1-mesh-r1`，run `20261013T135733Z-v4-source-interface-r4-a1-b1-mesh-b66a8e0d`，13:57:32.689701UTC启动；launcher_pid284628、runner_pid299072。全局5/19已用，A1项目已root check通过，manifest e84e4cf5004625480e3975ca656876cd62eabbc7fc8b6bdc119e0cc3aacfe741。**不要重提**，读其execution/manifest并等待完整COLLECTED。预计耗时较长，A0单线程已用34.5min；不改线程/时序或启动别的求解/后处理。

下文“下一步操作”1已完成，A1已提交。等待A1后继续原生全部gstep后处理→full field audit→root audit_mesh_diagnostic→compare_mesh_diagnostic。冻结field模块已实测5帧+真实A0全区间索引通过。root比较器的2%分母已固定为粗基准，与旧r2完全相同；4个比较反例tests通过，root整体审计7反例tests通过。

root新增/修改：README已指向stage2当前执行报告，旧版在previous-documents；report已更新A0成功/A1运行中；collect_evidence.py包含field-audit结果和read_only_progress_probe失败；prepare_field_audit.py/collect_field_audit.py的大归档sha已改流式以免内存峰值；read_live_source.py修复了raw字符串awk转义，后续read-only全部exit0。

本轮原19角色共有15个仍未运行（已实际尝试的角色为base A0/A1及mesh A0/A1），实际调用5次因为base A1观测修订重复一次；失败按预算算。不能为完成矩阵把版本预算重置，也不能未经重新冻结就把mesh .5自动推广到所有角色。先拿到真实fine结果和与基准对比；原base空间失败仍保留，依赖多源步骤目前暂停。最后要清楚报告这项未完成范围。

## 历史检查点：A0运行状态已被上文取代

## 最新：r4 A0 mesh运行中（13:42 UTC）

总调用4/19。当前唯一作业`r4-a0-b1-mesh-r1`，真实run `20261013T132129Z-v4-source-interface-r4-a0-b1-mesh-5a893127`，13:21:28启动；execution在r4 runtime/launches对应目录。launcher_pid262316、runner_pid262064；远端sdevice45965、CPU0。13:42还在2.857ns预充电，已生成205个gstep TDR约561331653bytes。细网格比旧基准慢，**不得重提或改线程/时间步**。先读原execution/manifest核查。只读probe记录在runtime/stage2-live；progress-02因awk换行转义exit1，原solver未失败；read_live_source.py已改raw字符串，progress-03/04 exit0。VM MemTotal约15.5GiB、available约12.5GiB，可先复用已成功Tcl，未启bounded-memory替代。

r3第3次A1已13:06:38正常COLLECTED、SSH0，正式audit `r3/audits/r3-a1-b1-base-r1`失败仅native_spatial_temporal_source：legacy=plain=1.004163880394135fC，BE波形相对误差.00416388；2D+3DWindow HI全0，但Temperature Total≈1.0200366µm²非零，z缺失假说不成立。原失败保留；冻结r3 A0复用门槛通过。真实曲线图已绘制并root目视复核，最终图stage2/figures-r3-a1-r2/source-measurement.png（旧第一图也保留）。

为诊断原空间误差，root提前执行用户原计划中的A0/A1 bit1 mesh=0.5，只这两个角色，不自动改主网格或扩多源。pipeline_gap已冻结source-interface-r4 builder/contract（14tests通过），候选两个均在runtime/r4/inputs/v4-source-interface-r4-a[01]-b1-mesh。物理只mesh .5，source/par/circuit/deck去observer完全同r2 mesh参考；MaxStep仍.5ps；增加`Plot(FilePrefix="gstep" Time=(Range=(0.95e-9 1.05e-9)) NoOverwrite)`，不加Intervals，不改变原5固定gfield点。r4 code_hashes引用r3诊断设计文件，**别再修改那些冻结依赖**。builder SHA bd7897419e57d5b74e90885fa1ddacd5e714d473dd26e272ec98da26e3fd09ce；contract f58abfde8f0c5ce405f3288668df9bfc1849716513d0f8886f79b69a7294c85c。source_control已认r2/r3/r4且全局19计数，8反例tests通过。

mentor_evidence已完成source-field-audit-r1：Tcl提取原生G、ONE、XG、YG在9ROI与全硅域积分；root用原adapter运行了只读`r2-a1-tdr-diagnostic-r4`，5旧TDR全部成功、前后SHA一致，receipt位于operation根`field-extraction-record.json`。实测5帧x≈.425000001、y≈.606914059、Center/G≈.78320354038、LR≈.999999939；Center abs error .0594972526>原.05，明确旧网格空间失败。原生抽样审计技术pass不等全源pass。最终旧五帧audit在runtime/source-field-audit-r1/audit-dev/old-five-final-audit；overall_source_interface_passed=false。

field模块已冻结：audit_fields.py SHA2d5717a007c88de6506cba4425c05dc10397acb336df88ef98b53636f909ce3d；extract_fields.tcl SHAb0c565290ce27f0ae8913cc9443827fd184555d35a6dbd213d7aa958f233e463；field_contract SHA807e07d988f63e52b12714b176b82ef7fc3854a81ee691e67bbc2ba9a2a7bcf8；7反例tests通过。真实full尚未运行。

### 下一步准确操作

1. A0收集后运行root `stage2/audit_mesh_diagnostic.py RUN --project R4_A0_PROJECT --output local_runtime/dram-see-v4/source-interface-r4/audits/r4-a0-b1-mesh-r1`。新总审计7反例tests通过；零源缺字段只给结构证明，不造数值0；检查真实代码/物理/曲线/守恒。若A0通过才用原root source_control提交A1 mesh作为第5次，标签r4-a1-b1-mesh-r1（尚未提交）。
2. A1完整归档后：`stage2/prepare_field_audit.py RUN_ID experiments/dram-see-v4/source-field-audit-r1/extract_fields.tcl r4-a1-mesh-tdr-diagnostic-r1 --family gstep`，它严格从原tar枚举全部动态帧，复制原remote文件，不推测时刻。之后旧`operation.py LABEL INPUT --timeout 600`串行后处理，不增SDevice次数。完成后`stage2/collect_field_audit.py LABEL`生成receipt。所有before/after哈希、SVisual/SSH/remote/collection真实0才通过。
3. `source-field-audit-r1/audit_fields.py full RUN --extraction OP_ROOT_OR_COLLECTED --output local_runtime/dram-see-v4/source-field-audit-r1/audit-dev/UNIQUE`。成功BE日志→Writing→完整PLT精确区间一一对应；全帧9gate才field_measurements_passed=true；overall_source_interface_passed仍false（等待root匹配控制）。5帧snapshots模式不能满足这个gate。
4. `stage2/audit_mesh_diagnostic.py A1_RUN --project A1_PROJECT --field-audit FULL_AUDIT_JSON --output .../r4/audits/r4-a1-b1-mesh-r1`。root代码还未在真实r4上验证，7负例tests过。
5. `stage2/compare_mesh_diagnostic.py --signal FINE_A1 --control FINE_A0 --coarse-signal R3_A1 --coarse-control R2_A0 --field-audit FULL_JSON --signal-project FINE_A1_PROJECT --control-project FINE_A0_PROJECT --output .../r4/comparisons/a1-base-to-mesh-r1`。4负例tests过；2%分母严格原粗网格，ΔV复用旧r2同A0配对阈值。只允许粗A1已知Window失败且legacy总量/波形有效用于独立数值对比，绝不升级粗网格源通过；main_grid_accepted/numerical_convergence_validated始终false。真实比较未跑。

stage2/report.md已更新为执行中并请求app预览（工具返回queued），mentor-response/route-status已写。root README仍旧状态，收尾需要更新入口。剩余多源等按原失败门槛暂停，不直接更换主网格。所有失败/原代码/档案保留。最终还需新evidence索引、86保护SHA、live idle/lock free、文档链接/图QA及最终汇报。agents目前均已完成交回；validation_worker不可用，root接管，不能换模型绕quota。

## 历史检查点：以下r3运行状态已被上文取代

## 最新状态：r3 A1正在运行（13:06 UTC）

目前总调用3/19。第3次为`r3-a1-b1-base-r1`，真实run ID `20261013T125700Z-v4-source-interface-r3-a1-b1-base-2f1ef557`，启动12:56:59 UTC。原execution.json在`local_runtime/dram-see-v4/source-interface-r3/launches/r3-a1-b1-base-r1/`。Windows launcher_pid261000、runner_pid257852；远端sdevice PID41779、CPU affinity0，NumberOfThreads1；OS有3个线程，包含辅助线程，不能写成OS总线程仅1。13:04只读日志已到2.872ns读出阶段；13:06尚RUNNING。**不得重提。**

r3代码/合同已由mentor_evidence冻结并交回root，唯一候选只改CurrentPlot，不改物理/mesh/s_hi。采用合法Temperature命令（UGp273），legacy Integrate(Semiconductor)、具名无Window、2DWindow诊断、3D角点9ROI并列；3D角点是预声明验收通路，其他路径不能救失败。9离线tests+build/check exit0。contract SHA d865e7d25ab79fb9bc3e78721e3f47f248bac68959b3e03e3e81555101094d1f；builder98c327b3230a7402694a7b2ce7db6376509cd6638b916e16ed2cc60404c79bd5；auditor479199fdb1d9e100a39847456038d4e8a808652496433688a648eabd863e0396。r3时间oracle正确σ=s；BE区间矩形电荷与中点时间矩；旧梯形仅诊断。r2 A0严格旧审计+matching合同+实际mesh哈希复用。

完成后准确命令：`python -B experiments/dram-see-v4/source-interface-r3/audit_interface.py local_runtime/runs/20261013T125700Z-v4-source-interface-r3-a1-b1-base-2f1ef557 --control local_runtime/runs/20261013T114619Z-v4-source-interface-r2-a0-b1-base-e305bf26 --project local_runtime/dram-see-v4/source-interface-r3/inputs/v4-source-interface-r3-a1-b1-base --output local_runtime/dram-see-v4/source-interface-r3/audits/r3-a1-b1-base-r1`。审计失败也保存曲线及全部可算指标。不要先修改r3使档案校验失效。

root source_control.py已升级跨r2/r3全局计数19、同修订同角色禁止重复、未知本地/远端状态拒绝；8个dispatch负例测试通过。旧wrapper在stage2/revisions。新read_live_source.py只读原run日志及进程，证据在runtime/stage2-live；不启动求解。新collect_evidence.py已生成evidence-checkpoint-r1（86保护SHA通过、2次当时源调用、6失败记录），收尾再生成新目录，不覆盖。

新plot_source_measurement.py可用r3审计目录、旧r2A0审计目录、独占输出目录绘制真实曲线；尚未运行/目视验收。stage2/report.md、mentor-response.md、route-status.md已写为执行中草稿，需要最终实际状态更新。核见证简报`mechanism-witness/results/campaign-r1/report.md`由pipeline_gap完成且root审阅，23证据链接检查通过。source-ledger README和interpretation-note已补离线时间核不等价原生TCAD的说明，旧manifest不改。

## 较早记录（下列“2次”“待实施r3”为历史检查点）

主代理root唯一调度，全部真实求解串行单线程。不得凭本文件重新提交；先读coordination.json与原operation/execution.json核对实际进程。旧v3、报告和旧v4探针未修改；保护清单86项在本轮中途复核全一致。无Git提交推送、安装、心跳或外发消息。

核见证：212个预定初级事件全部完成并通过记录审计，H9个合格事件，E无核见证。程序CPP编译版本始终不变；audit经历r1→r4语义修正，失败和每版快照均保存。init/pilot/fixed gate见mechanism-witness/results/。动态重离子只有受限GenericIon继承过程证据，缺逐核素原生库存；不能删掉该限制。总5878轨迹、5666birth links。首例fixed H s1 event3、primary step31，后代Si电离36.76421607279538 MeV，全事件Si电离40.41779593491412 MeV。汇总、完整事件表、关系图、出生能量图见mechanism-witness/results/campaign-r1/；图已根代理目视检查（不同核素颜色仍可改进）。

源账本：旧format-h5-a0-r1/e0、miss-h-e5-a0-r1/e0与核见证e3已分别在local_runtime/dram-see-v4/source-ledger/生成。前两份r1 exporter快照在source-ledger/revisions/；核例export_revision2含birth-links和代码快照。离线3D Gaussian只是裁剪诊断核，不是已验证TCAD三维径向模型；三个账本均tcad_ready=false，完整xyz不删除、不把厚靶缩放到DRAM。

二维目前只用了19次上限中的2次：

1. A0 bit1 base：run 20261013T114619Z-v4-source-interface-r2-a0-b1-base-e305bf26，runner0、结构/曲线/采样通过；无HI字段，generated_fC=null、只证明source-free deck，未冒称测量数值0。
2. A1 bit1 base：run 20261013T115652Z-v4-source-interface-r2-a1-b1-base-9aee36a9，runner0，但空间生成验收失败。初次auditor不认识实际IntegrG_前缀；修复字段读取后再审仍失败：9 ROI、2质心原始曲线全0。正式失败分别audits/r2-a1-b1-base-r1/与r2-a1-b1-base-r1-fields-r2/。

A4工程已生成，尚未求解。后续二维求解暂停依赖，不能用电压扰动或理论波形代替实际源测量，也不能放宽原阈值。mentor_evidence正在只读查Window/HeavyIon输出/TDR语义，仅可写diagnostics及开发runtime，不改冻结builder/contract。root可用原SVisual对已有TDR作串行后处理，不消耗新SDevice事件/求解，但必须保留后处理命令/退出码和原档hash。

新root入口：stage2/witness_control.py准备/收集/门槛（复用旧operation.py）；source_control.py只调用原scripts/tcad.py，并保存唯一执行目录和最多19次预算。不得自动重试；未知作业先只读核对。核见证已结束，不能再提已成功requests。

文献：Shin官方5页PDF原图核查完成，Fig8/11同剂量，Fig12同Vth且保持时间任意单位（不能绝对时间校准）；Park原图受访问限制仍未取得。见device-evidence-r2/README.md。无新尺寸/训练放行。

剩余工作：定位并修复二维测量链，按剩余预算和冻结门槛推进可放行检查；记录不能完成的依赖，不篡改失败。整理最终当前批注回应表、源检查结果/失败索引、报告/保护校验/活动进程终态；README指向新报告；保留所有原交付稿。

## 后处理检查点补充

- root通过旧operation.py运行了三个只读SVisual后处理attempt：`r2-a1-tdr-diagnostic-r1/r2/r3`。r1缺plot/geom上下文，115命令错误；r2源场测量可用但纯标量不能create_field，5错误；r3用`0*<HeavyIonGeneration>+1`，SVisual/SSH/remote/collection全部0、mandatory0，输入TDR前后sha保持。均没有新SDevice求解。新准备器stage2/prepare_tdr_diagnostic.py有--revision/--script；旧尝试和脚本完整保存。
- r3原生TDR measurement：gfield1硅域无Window和Total窗口积分均1.23728339439e27，硅面积1.02000006914 µm²，HI峰值3.86200632751e28 at(.425000011921,.315078139305,0)。左右窗口各约一半，Center/Total约.783，与连续解析erf(1)=.8427相差约.0595，超过先冻结.05；不能忽视空间离散风险。
- TDR内部state元数据仅state_0/index1/空current，不提供直接时间戳。日志Writing与前一已完成BE步和PLT精确时刻对应，五个保存时刻确为请求时刻。数据和日志哈希均留档。
- 实际查看UG p813 Eq810像素，时间核应是σ=s_hi=2ps（分母√2*s），r2合同与oracle误写成2*s；物理deck s_hi=2ps一直未变。五个TDR积分相对峰值完全吻合每个实际BE步上的正确高斯平均值，最大相对残差3.5e-12，没有拟合σ或t0。此为时间输出语义证据，不是源总量或空间门槛通过。证据在audit-dev/tdr-diagnostic-r3/saved-step-time-shape-diagnostic-erfc.json。
- mentor_evidence当前任务：给出最小SDevice测量修复方案，核查2D Window是否补z=0成零厚区域，以及2D器件能否显式三维Window；待根代理确认再实施新r3副本。建议同时输出已验证legacy IntegrSemiconductor、generic无Window、原2DWindow控制及显式z范围ROI，物理参数不改，原r2冻结。原时核oracle修正要另起版本且保留旧失败。
- 核见证最终图颜色修订在campaign-r1/figures-r2/，已root目视复核；第一稿图和生成器快照保留。
