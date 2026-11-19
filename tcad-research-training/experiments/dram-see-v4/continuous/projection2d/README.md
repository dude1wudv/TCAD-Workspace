# 20 nm 保守投影输入链

该目录只提供本地数学源与重算接口，不包含runner、原生调度或采集。`kernel.py`处理既有质子相关端点Gaussian连续重建；Geant4原输出仍是逐步沉积，不能称作原生G3场。当前真实示例使用固定旧planar请求 `nc-r1-h-000/event0`，不会被当作r14 BCAT源或训练样本。

在仓库根目录重算已保存示例：

```powershell
python -B experiments/dram-see-v4/continuous/projection2d/project.py verify --package local_runtime/dram-see-v4/continuous/control-transition-r14-2d/projection-implementation/historical-event0-projection-r2
```

如需重放同一已固定事件到一个新目录，使用：

```powershell
python -B experiments/dram-see-v4/continuous/projection2d/project.py historical --output local_runtime/dram-see-v4/continuous/control-transition-r14-2d/projection-implementation/<新目录> --window 1.4984e-8 1.5016e-8 --epoch 1.5e-8
```

此窗仅为该数学重放声明的15ns±16ps窗口，不是伪造的实际接受BE窗，也不代表新二维电路时序已经冻结。输出必须是新目录，原文件不覆盖。

原生BCAT事件适配的命令为 `project.py bcat --source-bundle <原完整事件bundle目录> --model <实际D2模型> --geometry <实际D2几何合同> --dimensional-contract <实际宽度合同> --window <起点s> <终点s> --output <新目录>`。目前缺少真实BCAT事件，因此这条完整路径尚未取得真实事件验证。它要求原 `continuous-proton-source-bundle-v1` 完整审计、原source payload重算及训练域身份；不会读取最终留出的事件内容来调优，也不会把缺失包解释为空源。新G4几何/源版本尚须显式适配，不能用近似同名JSON绕过版本检查。

Python接口可用精确文件loader读取，避免旧模块名冲突：

- `kernel.ResponseMask(spec)`：有限二维Si材料域。`contains(x_um,z_um)`和`cut(z_um)`只做几何判断，其他粒子可复用；BCAT输入格式见下文。
- `kernel.generation2d(terms,mask,x_um,z_um,time_s,window)`：数学G2，单位cm^-3 s^-1。仅适用于w=0.03μm、sigma=2ps的现有质子3D各向同性端点卷积，不能用来代替α的横向核/有限端面。
- `kernel.step_integrals(term,mask,window,origin_um,epoch_s)`和`integrate(terms,response,window,origin_um,epoch_s,refined=False)`：逐步及全事件接受量、绝对/相对一阶矩和互斥损失账。
- `adapter.bcat_bundle(path)`：只读核对原完整事件，保留所有step和祖先；不执行原operation。`adapter.historical_event0(epoch_s)`仅开放已经固定的旧请求event0。
- `project.bcat_response(model_path,geometry_path,dimensional_path,transport_geometry)`：绑定真实输入文件，检查20nm合同、D2与G4中央条带材料一致及model/geometry一致。输入检查通过仍不是原生源资格。
- `project.verify(package)`：重读原档、重构源、重积分，逐字节比较source/contract/ledger；manifest也不得伪造native标志。

`response` 的BCAT规格为：

```json
{"kind":"bcat_center_section","bounds_xz_um":[-1,0,1,1],"outer_trench":{"radius_um":0.012,"center_z_um":0.142,"top_um":0}}
```

term保留 `uid,p0_um,p1_um,t0_s,t1_s,charge_fC,width_um,sigma_s`。p0/p1始终为physical xyz三坐标；零长度不改造。输出源包另存完整原step字符串、event/track/parent/step身份、原birth link和祖先链、物理y起止点、全部材料能量、原request所有event分母及未投影原因。

输出文件为 `projection-source.json`、`projection-contract.json`、`projection-ledger.json`、`projection-kernel-contract.json`、`replay-request.json` 和 `input-output-manifest.json`。输入原档、二进制、请求、geometry、archive均按各adapter能够真实取得的原字段/hash绑定。历史示例使用旧轴置换 `[0,2,1]`，physical x=old x、y=old z、z=old y；没有平移成BCAT。历史示例不伪造实际D2绑定，该字段明确为null。

保守账是原正Si沉积对应的连续核电荷，依次分为条带外、条带内x/z盒外、条带盒内非Si、响应Si内窗外及接受电荷。原非Si沉积保留MeV，不套Si对产生能换算；原Si云的非Si尾量另列。晚源不删，`raw_deposition_outside_window_uids`与合同中的时序不可表示状态明确保留。没有损失重归一，也没有按大响应挑事件。

原生坐标X→physical x、Y→physical z。原生G面积积分单位为cm^-3 s^-1 μm²，乘 `1e-8*2e-6` 得pairs/s；再乘 `e*dt` 得C。XG/ZG保留绝对物理x/z坐标，转换C·cm矩时还需乘1e-4；报告fC·μm矩则保留坐标μm。独立摘要另记相对r0的一阶矩，不改变原生矩原点。不重复AreaFactor，不缩放20/200fF显式电容。

固定历史示例保留63条step，其中17条正Si核源；原请求1000事件仍在分母。原Si源0.13084379022282724fC，条带外0.08339359742417855fC，条带内盒外0.0031773322624039316fC，接受0.0442728605362447fC。电荷分项闭合残差1.0842e-17fC，四分之一容差复算最大电荷差8.4512e-12fC。不存在实际二维场或电学响应。

新增5项本地检查通过；随后仅补测相关段的独立G3闭式密度+y积分、实际BCAT输入一致性和伪native manifest拒绝，共3项定向检查通过。所有日志与首版代码快照在专用证据目录；最终CLI构建和完整重算均exit0。未重跑旧测试套件。

仍缺真实BCAT完整事件、r14新输运/响应版本登记、能够表示此G2的原生源接口及实际源场/接受BE验证。原生HeavyIon或PMI片段没有生成；`native_source_qualified=false`、`pmi_r12_fixed=false`。两bit电学、TCAD源时步/网格收敛、质心与波形判据不由本数学结果替代。α应使用其独立ASTAR横向源投影；只可复用本目录的通用几何/积分原函数。
