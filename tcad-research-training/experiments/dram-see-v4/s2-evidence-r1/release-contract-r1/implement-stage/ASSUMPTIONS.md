# Assumption Ledger — 首四角色离线发布合同
<!-- ASK mode: never -->

| ID | 未确定项 | 本轮决定 | Class | Source |
|---|---|---|---|---|
| C001 | 用户授予原生行动权限与本次离线交付的关系 | 保存完整本轮授权，action permission 为 true；合同批准、预算计费批准、策略发布、现场准入分别判定。离线包不隐含启动，不把已授予许可写成缺失。 | semantic | user |
| C002 | 原 owner 指哪一层 | 绑定原 supervisor.ownership 和既有 continuation/owner.lock；scheduler=root。当前线程仅为文档编制者；不以线程UUID代替现场锁持有人，不恢复旧r10入口。 | interface | default |
| C003 | 精确 run ID 的分配 | 以本批UTC stamp 加固定四角色名形成唯一预定ID；只检查本机原run目录不存在，不创建目录或预约；远端同名检查留待现场准入。未知作业只查原ID目录。 | interface | default |
| C004 | A0最终输入依赖尚不存在 | 冻结当前可知payload和配置；固定D3 producer ID及原档路径，真实mesh/manifest/tar/验收hash保持null。A0最终执行输入必须等D3原档验收再冻结，不把review manifest冒充执行manifest。 | semantic | default |
| C005 | 新S2预算与旧账关系 | 生成仅review的新budget ID与8个独立预约请求ID：4个角色执行、2个几何提取、2个字段提取。mesh2/SDevice4/几何2/字段2，4CPU小时/8GiB不增加；批准/预约/消耗0，无compile/training分配。请求ID不是实际预约。 | semantic | default |
| C006 | 策略未批准和资源未知 | 比较数值保持原样、批准false；资源既有门保持，首D2允许有依据的reviewed forecast，不循环要求它自己的实际mesh。未知预测/现场证据为null，未批准，不臆定内存/存储/耗时。 | semantic | default |
| C007 | 可执行字段的审查方式 | 生成带精确身份的project/execution-release/geometry-release的.review.json及源码引用清单；所有执行/发布开关false。缺失的authorization_evidence字段按既有bridge补齐引用。实际project.json、执行manifest及release须后续原owner发布。 | interface | default |
| C008 | 证据验证和保护成本 | 复用原29/15/Tcl/9通过记录，只验证本批新合同、关联和拒绝路径。只核对本批直接绑定的少量源文件/清单、原账本和attempt名称，不全包巡检。旧保护验收引用不冒充本轮全量复验。 | interface | user |
| C009 | 应用补丁的时点 | 已获应用许可；本轮review包仍绑定未应用candidate-r2和原runner摘要。等原owner的完整发布/资源准入准备完毕才应用及签发，不生成替代runner。历史候选/失败保留。 | interface | default |
| C010 | 缺项清单的效力 | readiness是离线审查结果且只能阻止执行；不能由编辑布尔值或本生成器批准预算、签发策略、解除门或调用原生。编译/训练一般许可保留但本首四合同不含对应角色/预算。 | semantic | default |
| C011 | A0字段提取的位置 | A0项目仍仅SDevice；每个A0另绑定原operation的一次字段提取label和独立预约请求，提取实际TDR/输入hash依赖该A0原档，不冒充已在项目steps内，也不新增operation实现。 | interface | default |
