# r0.4 显式输入协议

这是软件数据协议，不是新的仿真方法或参数依据。结构、材料、粒子源、Geant4→TCAD 映射、读出判据及适用标记须沿用已核对的模型与文献。软件不通过猜测补齐它们。

## Manifest

UTF-8 JSON；表为 JSONL。所有相对路径在当前清单目录内，不能逃逸或别名指向封存文件。

```json
{
  "schema_version": 1,
  "plan_id": "dram-se-ddr5-lpddr5",
  "simulation_revision": "0.4",
  "kind": "native_simulation",
  "data_stage": "model_ready",
  "sample_times_ns": null,
  "conditions_file": "conditions.jsonl",
  "primaries_file": "primaries.jsonl",
  "development": {
    "responses_file": "development.responses.jsonl",
    "controls_file": "development.controls.jsonl",
    "counts_file": "development.counts.jsonl"
  },
  "sealed": {},
  "files_sha256": {}
}
```

上面是结构说明，不是可训练数据。R 必须有预先确定且严格递增的 `sample_times_ns`，时间相对注入时刻。`sealed` 可声明封存文件/目录，提取程序只保留其引用，不读取内容、不复制、不计算封存标签哈希。导出快照生成五张表的实际 `files_sha256`，并保留 `sealed_external` 和提取来源记录。

### 尚无电学响应的输运快照

`data_stage: "transport_only"` 允许接入完整原生输运池。缺省阶段仍沿用原完整数据校验，称为 `model_ready`；名称只代表校验阶段，不保证标签或科研质量足够训练。

- 保留明确的 r0.4、开发/封存分区、器件域、profile、Lg、入射能量、proton、结构类型、全局来源 ID 和 SHA256；每工况实际独立 primary 数必须等于声明的 `primary_count`，每条均显式 `pool_member:true`。
- 电容、源映射、`source_off`、TCAD 选样身份、面积或 bit 信息未知时保留 `null`/缺省。非空值仍检查类型、有限性和物理范围。未选作 TCAD 响应的事件不能因为束流随机而写成 `sampling:"random"`。
- 响应、对照、计数表必须为空，且五表哈希必须完整。没有波形时省略 `sample_times_ns` 或设为 `null`，不能以空数组或虚构时间网格满足提取接口。
- 原始 `transport.ionizing_si_MeV` 与未建立的 `source_features.deposited_energy_MeV` 分开；硅零沉积不能自动变成 `source_off:true`、未翻转或零错误率。
- `prepare` 写入数量、缺项、`R_ready:false`、`F_ready:false` 和快照指纹，不冻结训练 folds。训练 View 与拟合入口拒绝这一阶段；服务器仿真调度不受影响。
- 本批原始入射角以向内法线为基准。模型 features 只采用实际束流三维向量；原角度、法线和源平面放 provenance，避免与模型默认球坐标约定冲突。

`import-r04` 针对当前原生开发归档格式执行适配：先核注册工况，再检查原 runner 记录的正向路径、原 run、输入/归档/提取输出哈希，最后对账完整事件池与冻结选样策略。共享 runner 的路径或 operation schema 含历史 v4 名称不等于旧 v4 物理数据；新输入的 r0.4 身份和哈希必须实际一致。原封存目录不能作为 operation 定位器读取。

人工测试使用 `kind:"synthetic_fixture"`，不允许将旧 v3/v4 生成标识改名后冒充本批数据。

## 五张表

| 表 | 必需身份及用途 |
|---|---|
| conditions | `condition_id,profile_id,cohort,domain,features,categories`；源面积、bit、分母与适用声明 |
| primaries | `primary_id,condition_id,source_primary_id,source_hash,source_features,source_off,pool_member,sampling` |
| responses | `response_id,primary_id,state,bit_id,status,labels,masks,source_hash,run_id`；可有 `supersedes` |
| controls | `control_id,profile_id,cohort,state,source_hash`，真实 RC 对照及适用标记 |
| counts | `count_id,condition_id,state,bit_errors,fluence_cm2,n_bits,count_model,source_primary_ids,source_hash` |

**conditions**

- `cohort`：`development/new_combination/high_energy/device_extrapolation`。
- 同一快照只有一个 `domain`；`categories.particle` 当前为 `proton`，`structure_family` 为有物理含义的结构类别。ID 不进网络。
- 必需物理字段：`gate_length_nm,incident_energy_MeV,capacitance_fF`。这是当前 r0.4 结构化仿真适配范围；商业器件未知几何不能用虚拟值补上。
- 可用器件字段：`device_length_nm,device_width_nm,fin_width_nm,oxide_thickness_nm,junction_depth_nm,acceptor_scale,donor_scale,acceptor_cm3,donor_cm3,bias_voltage_V,temperature_K`。
- 方向用 `theta_deg/phi_deg` 或单位 `direction_x/y/z`；同时出现时须一致。两者都未给出时当前接口按法向入射编码，导出真实清单时应显式给方向。
- 当前冻结边界：开发/新组合 E≤120 MeV、Lg 11.2–15.4 nm；高能 120<E≤200 MeV；器件外推 15.4<Lg≤16.8 nm 且 E≤120 MeV。矩阵数量是计划目标，不是已有样本数。
- `source_area_cm2,n_bits,primary_count,source_distribution:"uniform",area_normalization_validated` 供 A 使用。单 bit 默认坐标为原点；多 bit 必须有 `bits:[{bit_id,x_nm,y_nm,z_nm},...]`。二维有效厚度未核验时不能声明真实面积截面。
- `protocol_id` 应与响应及匹配对照一致。类别中不要混进样本编号。

**primaries**

- `source_primary_id` 是全局输运来源加事件身份；同一个 seed 不是可靠身份。跨条件复用事件时可有不同 `primary_id`，但来源身份必须相同。
- `sampling` 为 `random/enriched`，描述 TCAD 选样。`pool_member` 说明是否属于完整原生输运池；两者不能混为一谈。
- `source_features`：`generated_charge_fC,source_duration_ns` 必需；可有 `deposited_energy_MeV,hit_x_nm,hit_y_nm,hit_z_nm,secondary_count,spread_x_nm,spread_y_nm,spread_z_nm`。
- 入射动能与沉积能量不同，不能互换。`source_off` 指完整映射源关闭，不是某个评分区没有沉积。
- 全池必须显式保留零源事件；R 的 TCAD 样本可以只是子集，A 的运输分母必须完整。

**responses**

- `state` 只能为 0/1。`status` 为 `valid/unresolved/failed`，不是模型的第三物理类别。
- `labels.delta_voltage_V` 与冻结时间网格等长；`port_charge_fC,margin_V,upset` 为标量。缺失用 `null` 或省略。
- `masks` 按头开关。失败全屏蔽；未决连续头只有明确的有效掩码才可用；未决不进入二值监督。
- `upset` 为真实定义下的 0/1，并须有 `upset_definition_id`。软件不推导读出判据。
- `mechanism_validated:true` 表示该节点、源近似及窗口已被审阅为适用。没有这个声明的响应不会用于 RC 收集增益标定。
- 重试必须用 `supersedes` 指向旧 `response_id`，并保持 primary/state/bit 一致。禁止冲突修复分支或多个活动版本。

**controls**

`time_ns,voltage_V,reference_voltage_V,capacitance_fF,mechanism_validated` 定义可识别的 RC 松弛。没有可识别松弛就不估计 tau；没有有效辐照响应就不估计收集 gain。`source_control_id` 用于对照复用的全局身份，未提供时采用 `control_id`。

对照必须明确属于开发域。验证折对照仅用于该折评价和配对标签，不参与训练半侧的机理拟合；器件封存对照不能放入开发表。

**counts**

`bit_errors` 为非负整数，零计数保留。暴露为 `fluence_cm2 × n_bits`，须有已审阅的逐状态 `count_model:"poisson"` 口径。相关多 bit 或过度离散数据不能为了适配接口强行标成 Poisson。

`source_primary_ids` 是独立原生曝光来源清单，不能引用封存 primary；已知源必须属于当前条件。未登记在完整运输表内的独立原生曝光仍须有可追溯来源，复用来源会参与分组。混合图样的总计数目前不能拆成两个状态标签。

## 原始波形提取

intake 的响应行可以附加 `trace/control_trace`。每个 spec 必需：

```text
path, sha256, format("csv"/"dfise"),
time_column, voltage_column, time_unit("s"/"ns"), voltage_unit("V"/"mV")
```

提取端口电荷时另需 `current_column,current_unit("A"/"uA")`；响应需 `port_current_sign`（±1）、`charge_window_ns:[start,end]`。`injection_time_ns` 给出源注入时刻。

`matching_control:{profile_id,state,protocol_id}` 必须与条件/响应相符。信号和对照分别插值到冻结网格；差电流在两条原始网格的联合节点上积分。不能通过截断超出覆盖的窗口或丢掉重复时间点悄悄修好数据。

字段、单位、覆盖或单条原始文件哈希失败，只使相关响应保留为 `failed`、关闭掩码并记录原因；跨封存读取或身份混乱会拒绝该输入清单。根清单若声明文件哈希，须与每份 trace 的哈希同时相符。

提取器不运行旧项目 `analyze.py`，不打开服务器原任务目录，也不写回原始文件。
