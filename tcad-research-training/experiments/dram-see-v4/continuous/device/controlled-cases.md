# 受控输入入口

`prepare_case.py` 每次只准备一个输入目录，不提交原生作业。原 `prepare.py` 的 A0 命令转接同一当前生成器；DC 旧入口和已冻结 r8 / D3 r1、r2 输入保留。原 runner、owner、共享锁及主代理调度不变。

查看结构化尺寸变更，不写项目、不运行工具：

```powershell
python experiments/dram-see-v4/continuous/device/prepare_case.py --request experiments/dram-see-v4/continuous/device/request-d3-main.json --depth-change-text "将栅顶深度改为70 nm" --preview
```

同一请求去掉 `--preview` 并给出新的 `--run-id` 才生成新的项目。`--depth-change-text` 只识别单项明确修改：栅顶深度 70/80/90 nm，或 `将SN结深改为82 nm` 中的 82/87/92 nm；未知字段、其它尺寸、代码、命令和复合指令拒绝。

尺寸以 `gate-top-depth-70nm`、`gate-top-depth-80nm`、`gate-top-depth-90nm` 标识，保留文献集合映射 S1/S2/S3。有源宽度始终 20 nm，金属最深点 150 nm，对应垂直跨度 80/70/60 nm；这不是有源宽度或有效沟道长度。SN 结深字段 `sn_junction_depth_nm` 只接受整数 82/87/92，省略时为 87。新增 `parameter_id` 同时写明 gate 与 SN，例如 `gate-top-depth-80nm__sn-junction-depth-82nm`；原 `size_id` 仍只表示栅顶深度。

DC 和无源 A0 支持这些参数组合。SN 实际进入模型 doping、SDE General 初始化及几何合同中的 Gaussian 宽度 `a_sn_um=(sn_nm/1000)/sqrt(log(peak/acceptor))`。原探针位置（包括固定 87 nm 共用探针）、材料判据和全部容差不变；浓度期望按所选 `a_sn_um` 重算。`controlled-parameters.json` 明确 nm/µm/cm⁻³ 单位，绑定 model、geometry、SDE、measurement-plan 原字节；A0 则绑定真实 D3 网格及其模型/几何，不能把87 nm的D3标成82/92 nm。

新非默认参数 A0 使用明确无源的 generic CONTROL 合同，不复用 S2 α 独立参考；默认80/87 A0保留原接口。固定 α/proton v1 的活动源仍限定 gate80/SN87，未支持条件明确拒绝。α v2 使用独立的 r2 请求和原源包，见 [alpha-v2-inputs.md](alpha-v2-inputs.md)，不能只替换 v1 摘要文件。S3 保留最终留出保护；其它参数不自行分配 split，须在运行/响应前显式登记。全部原最终条件（包括插值组）仍由 data 审核保护，改 SN 或 seed 不能把它们改成训练样本。

真实 D3 完成并收集后，A0 请求的形状如下；`d3_source_run` 必须填原始已收集目录，不能填准备目录或合成目录：

```json
{
  "schema": "dram-see-v4-controlled-device-request-r1",
  "kind": "transient",
  "gate_top_depth_nm": 80,
  "sn_junction_depth_nm": 87,
  "dimension": 3,
  "variant": "main",
  "stored_bit": 0,
  "source_case": "A0",
  "d3_source_run": "ABSOLUTE_PATH_TO_ORIGINAL_COLLECTED_D3_RUN"
}
```

生成命令为 `python experiments/dram-see-v4/continuous/device/prepare_case.py --request REQUEST.json --run-id NEW_RUN_ID`。bit1 只把 `stored_bit` 改为 1。α信号在相应请求中用 `source_case: "Aalpha"`，并添加 `matched_a0_project` 指向同 bit/variant 的已冻结 A0 输入。Z、H、split 为原源幅度/分段控制；H 是同一 5 MeV 表的半幅控制，不能称为 2.5 MeV α。A0/Aalpha 支持 main、mesh、time；Z/H/split 只支持 main。mesh 需要独立的真实 h/2 D3 producer，time 使用同 main 网格并将全时间表步长减半。

新信号请求还必须给 `source_features_file` 和 `registered_data_input`。前者指向 proton/source_features.py 由五个纯输入生成的原 `source-features.json`：model.proposed.json、geometry-contract.json、alpha-profile.csv，以及当前 case 的 HeavyIon/source.par 文件。后者指向 data 的 `bind-input` 或 `bind-qualification` 输出。`diagnostic/qualification` 是运行前输入登记，可在没有 TCAD 结果、训练资格或训练设计时完成；不会用后验科学验收阻挡首次源运行。A0 和 D3 不需要这些信号字段。

冻结时通过固定 `source_feature_versions.py` 分发器调用上游源重算器 `verify(packet, input_files=actual_inputs)`，再调用数据端 `verify_registered_input` 重建原登记。实际源片段、模型、几何、bit 和 physics manifest 必须对应，不能靠 `verified=true` 或手填 13 个数值通过。源数学、登记逻辑分别由 proton 和 data 模块负责，device 不重复实现。

项目复制原 `source-features.json`、`source-feature-contract.json`、`data-input.json` 字节，另保存来源绑定、固定分发器/所选版本验证器/登记代码快照及注册表、依赖清单。新 binding schema 为 r2，各自 SHA 分开记录；旧 r1 输入保留。输入清单同时冻结它们。同事件两 bit 共用同一摘要原字节；bit 只进入各自数据登记和角色输入。摘要不包含 TCAD G、BE 时钟、Qcol、DeltaV 等求解输出。Z 的零源语义由原源片段及重算证明。旧冻结包不补写；参数或源包改变时产生新的摘要和输入。原 α v1 分支只支持已声明的 S2 源；v2 和质子分别通过独立接线进入，不能仅更换摘要文件。质子见 [proton-inputs.md](proton-inputs.md)。

匹配 A0 输入只证明输入身份。实际两 bit 写入、保持、预充、读出和 KCL 必须由原始结果审核，不能由生成成功代替。

每份瞬态复制原 D3 的 geometry-contract/model 和 physics.par、physics-manifest.json、Silicon.par、Oxide.par 原字节。信号实际参数文件是 `run-parameters.par = physics.par bytes + LF + 当前源 source.par bytes`；`parameter-binding.json` 绑定求解器实际 `Parameter=` 文件与所有组成 SHA。源附加参数只允许声明的 HeavyIon 块。A0 直接使用 physics.par，结构上无源，缺少源场不记录为实测零。

3D DC 用 `Method=ILS(set=1)`，混合模式用 `Method=Blocked SubMethod=ILS(set=1)`，显式计算线程为 1 并记录线性求解信息。原 Digits/ErrRef/迭代及失败退出判据不变。依据是 W-2024.09 默认 3D 算法及实际 2D ParDiSo 内存观察；没有新增点数、时间、内存额度。操作系统辅助线程总数仍需如实记录，不能以计算线程设置冒充全程 OS Threads=1。

新增检查仅覆盖迁移接口和已知风险：18 个 bit/case/variant 载荷的参数/匹配一致性，70/80/90 几何期望及 h/2 传播，原测量容差与已实测修复保留，自然语言白名单及隐藏参数覆盖拒绝。原 S2 独立源积分参考复用，不重复计算已通过的旧数学套件。检查和合成载荷不构成真实 D3、A0、α资格。现阶段本项目 ILS、3D接触面、两bit和α仍需原生结果证明。
