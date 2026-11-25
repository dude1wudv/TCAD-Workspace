export const docsContent = {
  zh: {
    hero: {
      eyebrow: 'TECHNICAL DOCUMENTATION',
      title: 'DRAM 单粒子效应研究全栈技术文档',
      lead: '系统阐述本课题在辐射粒子输运、半导体器件物理建模、C++ 自定义 PMI 扩展、物理约束预测网络、服务器 Agent 自治调度及双频只读遥测展示上的完整技术实现与工程防伪契约。',
      searchLabel: '检索技术文档（按 / 聚焦）',
      searchPlaceholder: '输入关键词，如 PMI、QGSP_BIC、Horvitz-Thompson、shared pool…',
      clearSearch: '清除搜索',
      resetFilters: '重置筛选',
      matchPrefix: '匹配章节',
      emptyTitle: '未找到匹配的技术章节',
      emptyDesc: '请尝试更换关键词或点击重置筛选查看全部六大技术章节。',
      tocTitle: '章节目录',
      cheatTitle: '核心规范速查',
      cheatItems: [
        { k: '四级严格口径', v: 'COLLECTED ≠ solved ≠ accepted ≠ statistics_eligible' },
        { k: '三层空间不相加', v: '服务器剩余 · VM文件可增长 · 虚拟机分配/剩余' },
        { k: 'r0.6 正式状态', v: '396 正式槽位实时推进 · 58 HR/HP 封存' },
        { k: '预测模型状态', v: '172 离线测试通过 · 待 r0.6 合格标签训练' }
      ],
      backTop: '返回顶部',
      openToc: '目录与速查'
    },
    domains: [
      { id: 'all', label: '全部技术域' },
      { id: 'transport', label: 'Geant4 输运' },
      { id: 'tcad', label: 'TCAD & C++ PMI' },
      { id: 'ai', label: 'R→A→F 预测网络' },
      { id: 'agent', label: 'server-codex-v2' },
      { id: 'web', label: '遥测与前端' }
    ],
    predictorTabs: [
      {
        id: 'R',
        tab: '阶段 R · 事件响应网络',
        badge: '机理骨架 + 64-64 SiLU 残差',
        formula: 'ΔV_pred = f_RC(LET, L_hit, C_sn, V_init) + MLP_64x64_SiLU(x_event)',
        desc: '以可校准的低阶 RC 电荷收集机理模型作为物理基线，叠加 64-64 隐层 SiLU 残差 MLP 捕捉非线性边界效应；联合输出存储节点电荷增量 ΔQ、电压降 ΔV、差分读出裕量 ΔM 与单粒子翻转概率 p_seu。',
        specs: ['损失函数：Huber（连续电荷/电压）+ BCE（翻转分类）+ 残差 L2 正则', '输入特征：器件几何倍乘参数、粒子种类/能角、入射坐标与局部沉积峰值', '防过拟合：残差项受物理正则约束，外推至未见沟道长度仍保持物理单调性']
      },
      {
        id: 'A',
        tab: '阶段 A · 无偏统计聚合器',
        badge: 'Horvitz-Thompson 分层估计',
        formula: 'σ_hat = (1 / N_total) * Σ [ A_cell * p_seu(i) / π_i ]',
        desc: '将事件级响应模型 R 的输出与分层抽样纳入概率 π_i、敏感区面积 A_cell 及零沉积事件分母严格结合，产出具备理论无偏性与置信区间界定的翻转截面（σ）与软错误率（SER）估计。',
        specs: ['分母刚性：强制包含 Geant4 零沉积事件（如 r0.4 的 54,037/60,000），杜绝只算正沉积导致的高估', '分层加权：支持对高能核反应或中心击中层执行重点抽样并用纳入概率还原', '外部快照契约：须齐全抽样帧、权重与 accepted 证据方可授予 statistics_eligible']
      },
      {
        id: 'F',
        tab: '阶段 F · 仿真前宏观头',
        badge: '32-32 SiLU · 双 Softplus',
        formula: 'σ_macro(d, r) = Softplus(Head_F(φ_device, φ_rad)) ≥ 0',
        desc: '仅接收仿真前的器件参数与辐照工况参数，通过 32-32 SiLU 网络与双非负 Softplus 输出头直接预测宏观翻转截面与错误率区间，实现无需全量瞬态求解的毫秒级快速评估。',
        specs: ['损失函数：原生计数采用 Poisson 对数似然 + 代理标签采用 asinh-Huber 鲁棒损失', '防泄漏划分：由 splits.py 按 profile、复用 primary 与对照来源构建连通分量做 3 折分组 CV', '当前边界：离线测试 172/172 通过；因 r0.6 正式标签尚未生成，R_ready=false, F_ready=false']
      }
    ],
    chapters: [
      {
        id: 'overview',
        domain: 'all',
        num: '01',
        badge: '技术全景',
        title: '全栈技术全景与数据/控制流图谱',
        summary: '围绕“物理真实性、工程可复现、公网零敏感暴露”三大目标，课题集成了高能物理输运、商业 TCAD 数值求解、PyTorch 物理约束网络与 systemd 沙箱自治控制面。',
        stackTable: [
          { layer: '粒子物理输运', tech: 'Geant4 10.7.3 (C++ / QGSP_BIC + EM Opt4)', role: '初级粒子与厚硅核非弹性次级径迹及零沉积统计', status: '已验证 (60k+)' },
          { layer: '半导体器件求解', tech: 'Synopsys Sentaurus W-2024.09 + GCC 10.2 PMI', role: '2D/3D 混合模式 WHR 瞬态求解与原子有界日志扩展', status: '已验证 / P0 诊断中' },
          { layer: '物理约束 AI', tech: 'uv + Python 3.11+ + PyTorch >=2.6 (CPU)', role: 'R → A → F 三阶段响应/截面预测与连通分量分组 CV', status: '172 离线测试通过' },
          { layer: '服务器自治编排', tech: 'server-codex-v2 (Python + systemd + Sol/Astra)', role: '17-vCPU 异步共享池调度、门禁对账与两步式冷备', status: '已上线托管' },
          { layer: '只读遥测与门户', tech: 'SQLite + Caddy + Vite 7.3.8 + @material/web 2.5.0', role: '双频脱敏投影、防篡改存储与亮/暗 M3 展示站', status: '已上线运行' }
        ],
        bullets: [
          '所有模块间采用冻结 JSON/CSV 契约与 SHA256SUMS 指纹衔接，避免隐式全局状态耦合。',
          '公网层（tcad.xjtu.shop / status.xjtu.shop）与计算层（隔离 CentOS 7.9 虚拟机）完全解耦，前端只消费脱敏白名单数据。'
        ]
      },
      {
        id: 'geant4',
        domain: 'transport',
        num: '02',
        badge: '粒子物理层',
        title: 'Geant4 高能粒子与 protonInelastic 核反应输运',
        summary: '自编 C++ 输运程序（geant4_transport / transport_witness）在保留全部初级粒子零沉积事件的同时，完整记录 100 MeV 质子在厚硅中的核非弹性次级血缘。',
        stackTable: [
          { layer: '物理列表', tech: 'QGSP_BIC + G4EmStandardPhysics_option4', role: '兼具精确低能电离与中高能强子核非弹性反应截面的标准组合', status: 'v4 / r0.4 实证' },
          { layer: '配套核数据库', tech: 'G4EMLOW7.13 · G4ENSDFSTATE2.3 · PhotonEvaporation5.7 · G4PARTICLEXS3.1.1', role: '保证低能电子散射、核退激 γ 与截面插值一致', status: '环境锁定' },
          { layer: '血缘追踪机制', tech: 'Mother Step ID → Daughter Track ID 映射表', role: '重建核反应点产生的 p / n / α / Li7 / γ / O15 及 γ→e⁻ 级联', status: '9 例见证闭合' },
          { layer: '时空网格映射', tech: '离散化载体生成率表 (Δt, x, y, z) + 电荷积分审计', role: '将离散粒子能量沉积转化为 TCAD 连续载流子注入源', status: '误差 0.416% (<5%)' }
        ],
        bullets: [
          '在 v4 机制见证中，212 个 100 MeV 质子事件产生 5,878 条轨迹、46,631 步，精确捕获 9 个合格 protonInelastic 核反应见证（单次硅沉积最高达 36.764 MeV）。',
          '在 r0.4 中，6 个能角工况（1–120 MeV, 0°–60°）输出 60,000 个初级质子，其中 5,963 例正沉积与 54,037 例零沉积全部保留，确保翻转截面分母严格无偏。',
          'v4 2D 细网格 205 帧（0.95–1.05 ns）动态源审计实测：A1 原生总生成 1.004157 fC，积分误差 0.416%，质心偏移仅 0.0022 μm。'
        ]
      },
      {
        id: 'tcad-pmi',
        domain: 'tcad',
        num: '03',
        badge: '器件仿真层',
        title: 'Sentaurus TCAD 2D/3D 器件建模与 C++ 原子有界日志 PMI',
        summary: '器件体系由早期平面 1T1C、90 nm BCAT 演进至 r0.6 LPDDR5 14 nm Saddle-Fin（Lg=14 nm, Wfin=8 nm, Tox=6 nm, Hjc=82 nm），并通过自研 C++ PMI 攻克多线程数值注入难题。',
        stackTable: [
          { layer: '建模与网格', tech: 'Sentaurus SDE + snmesh', role: '支持 13 套 r0.6 器件倍乘几何（含 24,429 顶点 3D 结构）参数化生成', status: 'D0–D2 已验证' },
          { layer: '物理与混合模式', tech: 'Fermi / OldSlotboom / Masetti / SRH + Auger + 混合模式外电路', role: '0–35 ns 完整“写入—保持—辐照—差分读出”瞬态耦合求解', status: '全链路实测' },
          { layer: '自定义 C++ PMI', tech: 'GCC 10.2.0 编译全局原子有界日志 .so', role: '解决局部 PMI 跨步不刷新写零及 24k+ 顶点日志爆炸/竞争', status: 'r0.6 O2 编译通过' },
          { layer: '收敛数值调优', tech: '局部时间窗 LineSearchDamping=0.25', role: '定位 [30.200, 30.925] ns CNorm 电子拒步，开区间拒步从 114/421 降至 8/57', status: 'D1 实测提效' }
        ],
        bullets: [
          'v4 原生诊断证实标准局部 PMI Compute_r 仅在初始化回调（49,130 次），在 957 个向后欧拉（BE）步间不刷新导致主动写入零源；r0.6 改用全局共享源缓存彻底修复该缺陷。',
          '针对 24,429 个网格顶点在多线程并行下产生的千万行级 I/O 争用，新 PMI 使用 std::atomic<std::uint64_t> 实施无锁计数与有界日志截断。',
          '3D DC 基准实测：24,429 顶点结构在 2×4 核并行下平均耗时 110.59 s，显著快于 4×2 核的 153.58 s，同时严格保持单核/多核电流差分析口径。'
        ]
      },
      {
        id: 'predictor',
        domain: 'ai',
        num: '04',
        badge: '物理约束 AI',
        title: 'R → A → F 物理约束预测网络与防泄漏评估体系',
        summary: '拒绝黑盒端到端暴力拟合，将单粒子效应评估拆解为可解释的三阶段数学结构，并通过图连通分量严格阻断训练与评估之间的数据泄漏。',
        hasPredictorTabs: true,
        stackTable: [
          { layer: '基线模型已交付', tech: 'v3 物理特征岭回归 (r50-main 128 算例)', role: 'Holdout ΔM MAE 0.527/0.550 mV，外推 L=0.45 μm MAE 0.405/0.388 mV', status: '已冻结交付' },
          { layer: '神经网络架构', tech: 'PyTorch >=2.6 (CPU) · R(64-64) → A(HT) → F(32-32)', role: '兼顾单事件电荷响应可解释性与仿真前宏观截面快速推理', status: '172 离线测试通过' },
          { layer: '防泄漏划分器', tech: 'splits.py 连通分量图分组 (3 折交叉拟合)', role: '按 profile、复用 primary 与对照关联自动聚簇，确保测试集零重叠', status: '离线验证通过' }
        ],
        bullets: [
          '严格科学纪律：虽然预测包代码与 172 项单元测试全部通过，但因 r0.4 缺少配对 TCAD 响应标签且 r0.6 正式矩阵尚在 P0 阶段，目前 R_ready=false, F_ready=false。',
          '只有当 r0.6 产出一批满足 accepted 与 statistics_eligible 的真实数据后，才会启动正式超参搜索与“物理机理+残差 vs 纯 MLP”消融实验。'
        ]
      },
      {
        id: 'agent-autonomy',
        domain: 'agent',
        num: '05',
        badge: '服务器自治',
        title: 'server-codex-v2 事件驱动调度、防伪账本与两步冷备',
        summary: '从早期的串行脚本演进为托管在 Rocky Linux 9 systemd 沙箱中的异步事件驱动自治系统，实现多槽位安全并发、顾问异步会诊与无损空间回收。',
        stackTable: [
          { layer: '事件控制面', tech: 'controller.py + runtime.py (systemd ProtectSystem=strict)', role: '仅由计划、队列或观测变化唤醒；日志追加不唤醒；300–3600s 指数退避', status: '243 回归通过' },
          { layer: '异步共享池', tech: 'scheduler_{engine,collector,probe,admission,planner,pool}', role: '唯一串行归档 + 5s 有界探针 + 三层准入 + TCAD/Geant4 排空切换状态机', status: '已上线接管' },
          { layer: '防伪与对账', tech: 'PID/start_ticks/boot_id + SHA256SUMS + intent_reconciliation', role: '禁止 PID 复用误认；未启动意图凭完整回执闭合为 failed_unlaunched，绝不盲投', status: '全链生效' },
          { layer: '两步冷备回收', tech: 'results.essential.tar.gz + results.raw.tar.gz', role: '4 份多核算例实测节余服务器 12.794 GiB、虚拟机 20.942 GiB，流式免解压读取', status: '已验证节省' }
        ],
        bullets: [
          'Sol 主研究模型遇疑难故障时异步调用服务器管理核只读顾问 Astra（75.5s 实测联通），期间主引擎照常推进归档与补槽。',
          '所有技能规范（sentaurus-vm-runner 等）严格控制在 50 行以内，固化“断线先查后收、严禁误签许可、严禁重复全目录哈希”等铁律。'
        ]
      },
      {
        id: 'web-telemetry',
        domain: 'web',
        num: '06',
        badge: '遥测与前端',
        title: '双频只读遥测脱敏、SQLite 防篡改与 M3 前端架构',
        summary: '面向公开透明与绝对安全隔离而设计的展示与监控体系：所有数据经过正则防火墙与 SQLite 只读触发器投影后，由零外链的 Google M3 Web Components 渲染。',
        stackTable: [
          { layer: '双频观测器', tech: 'systemd timers: 15s /live.json + 60s /status.json', role: '仅读取 progress.json 或日志末尾 128 KiB，支持 180s 过期判定与损坏回退', status: '生产运行中' },
          { layer: '防篡改存储', tech: 'SQLite user_version=1 + 只读投影 + 防覆盖触发器', role: '记录 Codex 问题与进展短语，阻止历史记录被静默覆写', status: '122 项测试覆盖' },
          { layer: '脱敏与封存网关', tech: 'PUBLIC_REDACTION 正则 + ANON-* 匿名映射', role: '拦截私有路径/run_id/PID，彻底剥离 HR/HP 58 例与封存输运池明细', status: 'CI/部署强检' },
          { layer: '前端与研究台', tech: 'Vite 7.3.8 + @material/web 2.5.0 + 离线研究台词表解析器', role: '零外链 CDN 字体、自适应亮/暗主题与双语切换；离线研究台支持断网中文解析', status: '当前升级交付' }
        ],
        bullets: [
          'status.xjtu.shop 的服务健康度与 2h/24h 遥测曲线与本门户共享同一份脱敏 JSON 契约，不开启任何向 CentOS 7.9 虚拟机的反向代理。',
          '受邀研究台 /desk/ 当前提供目录与输入校验接口，/api/v1/predict-r 与 predict-f 明确返回 503 model_pending，直至模型正式就绪。'
        ]
      }
    ]
  },
  en: {
    hero: {
      eyebrow: 'TECHNICAL DOCUMENTATION',
      title: 'Full-Stack Technology Documentation',
      lead: 'Comprehensive engineering reference covering high-energy nuclear transport, Sentaurus TCAD + atomic C++ PMI extensions, the R→A→F physics-constrained predictor, server-codex-v2 autonomy, and read-only telemetry projection.',
      searchLabel: 'Search docs (press / to focus)',
      searchPlaceholder: 'Filter by keyword: PMI, QGSP_BIC, Horvitz-Thompson, shared pool…',
      clearSearch: 'Clear search',
      resetFilters: 'Reset filters',
      matchPrefix: 'Matching chapters',
      emptyTitle: 'No matching documentation sections',
      emptyDesc: 'Try another keyword or reset filters to browse all six technology chapters.',
      tocTitle: 'Chapters',
      cheatTitle: 'Canonical Rules',
      cheatItems: [
        { k: '4-Tier Ledger', v: 'COLLECTED ≠ solved ≠ accepted ≠ statistics_eligible' },
        { k: '3-Layer Non-Additive', v: 'Server free · VM disk growth · VM allocated/free' },
        { k: 'r0.6 Formal Status', v: '396 formal slots live · 58 HR/HP sealed' },
        { k: 'Predictor Status', v: '172 offline tests pass · awaits r0.6 accepted labels' }
      ],
      backTop: 'Back to top',
      openToc: 'Contents & Specs'
    },
    domains: [
      { id: 'all', label: 'All Domains' },
      { id: 'transport', label: 'Geant4 Transport' },
      { id: 'tcad', label: 'TCAD & C++ PMI' },
      { id: 'ai', label: 'R→A→F Predictor' },
      { id: 'agent', label: 'server-codex-v2' },
      { id: 'web', label: 'Telemetry & M3 UI' }
    ],
    predictorTabs: [
      {
        id: 'R',
        tab: 'Stage R · Event Response',
        badge: 'RC Mechanism + 64-64 SiLU',
        formula: 'ΔV_pred = f_RC(LET, L_hit, C_sn, V_init) + MLP_64x64_SiLU(x_event)',
        desc: 'Combines a calibratable low-order RC charge-collection skeleton with a 64-64 SiLU residual MLP, predicting collected charge ΔQ, voltage drop ΔV, readout margin ΔM, and upset probability p_seu.',
        specs: ['Losses: Huber (continuous ΔQ/ΔV/ΔM) + BCE (upset) + residual regularization', 'Inputs: geometry multipliers, particle energy/angle, strike site, peak deposition', 'Extrapolation: mechanism backbone anchors physical monotonicity across channel lengths']
      },
      {
        id: 'A',
        tab: 'Stage A · Statistical Aggregator',
        badge: 'Horvitz-Thompson Estimator',
        formula: 'σ_hat = (1 / N_total) * Σ [ A_cell * p_seu(i) / π_i ]',
        desc: 'Integrates event-level predictions from R with stratified inclusion probabilities π_i, sensitive area A_cell, and zero-deposition counts to yield unbiased cross-sections and error rates.',
        specs: ['Zero-deposition denominator: strictly retains Geant4 non-depositing primaries (e.g., 54,037/60,000 in r0.4)', 'Stratification: supports importance sampling across high-LET nuclear events without bias', 'Contract: requires external qualified snapshot + accepted labels before granting statistics_eligible']
      },
      {
        id: 'F',
        tab: 'Stage F · Macroscopic Head',
        badge: '32-32 SiLU · Dual Softplus',
        formula: 'σ_macro(d, r) = Softplus(Head_F(φ_device, φ_rad)) ≥ 0',
        desc: 'Takes only pre-simulation device and radiation descriptors through a 32-32 SiLU network with dual non-negative Softplus outputs for instant macroscopic cross-section estimation.',
        specs: ['Losses: exact Poisson likelihood on raw counts + asinh-Huber on surrogate targets', 'Leak-free CV: splits.py builds connected components across profiles, primaries & controls', 'Current boundary: 172/172 offline tests pass; R_ready=false, F_ready=false pending r0.6 labels']
      }
    ],
    chapters: [
      {
        id: 'overview',
        domain: 'all',
        num: '01',
        badge: 'Architecture',
        title: 'Full-Stack Technology Landscape & Control Flow',
        summary: 'Designed around physical fidelity, reproducibility, and zero public sensitive leakage, integrating particle physics, commercial TCAD solvers, PyTorch surrogates, and a sandboxed autonomous controller.',
        stackTable: [
          { layer: 'Particle Transport', tech: 'Geant4 10.7.3 (C++ / QGSP_BIC + EM Opt4)', role: 'Primary ions, inelastic silicon nuclear secondaries & zero-deposition counts', status: 'Verified (60k+)' },
          { layer: 'Device Simulation', tech: 'Synopsys Sentaurus W-2024.09 + GCC 10.2 PMI', role: '2D/3D mixed-mode WHR transient solving & atomic bounded-log PMI', status: 'Verified / P0 Active' },
          { layer: 'Physics-Guided AI', tech: 'uv + Python 3.11+ + PyTorch >=2.6 (CPU)', role: 'R → A → F surrogate pipeline & connected-component group CV', status: '172 Offline Tests Pass' },
          { layer: 'Server Autonomy', tech: 'server-codex-v2 (Python + systemd + Sol/Astra)', role: '17-vCPU shared-pool scheduler, fail-closed gates & two-stage cold offload', status: 'Production Active' },
          { layer: 'Telemetry & Portal', tech: 'SQLite + Caddy + Vite 7.3.8 + @material/web 2.5.0', role: 'Dual-rate redaction, anti-tamper SQLite & light/dark M3 presentation', status: 'Live' }
        ],
        bullets: [
          'Module boundaries use frozen JSON/CSV contracts and SHA256SUMS fingerprints with zero implicit shared state.',
          'Public portals (tcad.xjtu.shop / status.xjtu.shop) remain strictly decoupled from the isolated CentOS 7.9 simulation VM.'
        ]
      },
      {
        id: 'geant4',
        domain: 'transport',
        num: '02',
        badge: 'Transport',
        title: 'Geant4 High-Energy & protonInelastic Nuclear Transport',
        summary: 'Custom C++ transport binaries capture thick-silicon nuclear inelastic cascades under 100 MeV protons while retaining every zero-deposition primary event.',
        stackTable: [
          { layer: 'Physics List', tech: 'QGSP_BIC + G4EmStandardPhysics_option4', role: 'Balances precision low-energy ionization with hadronic nuclear reactions', status: 'v4 / r0.4 Verified' },
          { layer: 'Nuclear Data', tech: 'G4EMLOW7.13 · G4ENSDFSTATE2.3 · PhotonEvaporation5.7 · G4PARTICLEXS3.1.1', role: 'Pinned cross-section, photon de-excitation, and low-energy EM tables', status: 'Pinned' },
          { layer: 'Ancestry Graph', tech: 'Mother Step ID → Daughter Track ID Ledger', role: 'Reconstructs p / n / α / Li7 / γ / O15 and γ→e⁻ secondaries per vertex', status: '9 Witnesses Closed' },
          { layer: 'Space-Time Mapping', tech: 'Discrete carrier generation tables (Δt, x, y, z) + charge audit', role: 'Converts discrete tracks into continuous TCAD generation sources', status: '0.416% Error (<5%)' }
        ],
        bullets: [
          'v4 mechanism campaign (212 100 MeV protons, 5,878 tracks / 46,631 steps) captured 9 qualified protonInelastic witnesses up to 36.764 MeV Si deposition.',
          'r0.4 transported 60,000 primary protons across 6 energy/angle pairs (1–120 MeV, 0°–60°), retaining all 54,037 zero-deposition events alongside 5,963 hits.',
          'v4 205-frame fine-mesh dynamic source audit measured 1.004157 fC total generation (0.416% error, 0.0022 μm centroid deviation).'
        ]
      },
      {
        id: 'tcad-pmi',
        domain: 'tcad',
        num: '03',
        badge: 'Device Physics',
        title: 'Sentaurus TCAD 2D/3D Modeling & Atomic Bounded-Log C++ PMI',
        summary: 'Device geometries evolve from planar 1T1C and 90 nm BCAT to 14 nm LPDDR5 Saddle-Fin, backed by a lock-free atomic C++ PMI solving multi-thread contention and step-refresh defects.',
        stackTable: [
          { layer: 'Geometry & Mesh', tech: 'Sentaurus SDE + snmesh', role: 'Parameterized 13-profile r0.6 devices up to 24,429-vertex 3D Saddle-Fin', status: 'D0–D2 Verified' },
          { layer: 'Mixed-Mode Physics', tech: 'Fermi / OldSlotboom / Masetti / SRH + Auger + Circuit Netlist', role: '0–35 ns coupled Write-Hold-Strike-Readout transient simulations', status: 'Audited' },
          { layer: 'Custom C++ PMI', tech: 'GCC 10.2.0 global atomic bounded-log .so', role: 'Fixes local PMI missed BE step refreshes & 24k+ vertex log explosion', status: 'r0.6 O2 Compiled' },
          { layer: 'Solver Damping', tech: 'Localized LineSearchDamping=0.25 window', role: 'Eliminates [30.200, 30.925] ns CNorm rejections (114/421 → 8/57)', status: 'D1 Verified' }
        ],
        bullets: [
          'v4 native diagnostics proved standard local PMI Compute_r fired only at initialization (49,130 times) without refreshing across 957 BE steps; r0.6 replaces this with a global cached source.',
          'Across 24,429 mesh vertices in multi-threaded runs, std::atomic<std::uint64_t> enforces lock-free bounded logging without multi-million-line I/O bottlenecks.',
          '3D 24k-node DC benchmark averaged 110.59 s at 2×4-core parallelism versus 153.58 s at 4×2-core.'
        ]
      },
      {
        id: 'predictor',
        domain: 'ai',
        num: '04',
        badge: 'Physics AI',
        title: 'R → A → F Physics-Constrained Predictor & Leak-Free Evaluation',
        summary: 'Decomposes SEE assessment into an interpretable 3-stage pipeline with connected-component graph splitting to guarantee zero cross-fold leakage.',
        hasPredictorTabs: true,
        stackTable: [
          { layer: 'Frozen Surrogate', tech: 'v3 Physics-Feature Ridge (r50-main 128 cases)', role: 'Holdout ΔM MAE 0.527/0.550 mV; Extrapolation L=0.45 μm MAE 0.405/0.388 mV', status: 'Delivered' },
          { layer: 'Neural Architecture', tech: 'PyTorch >=2.6 (CPU) · R(64-64) → A(HT) → F(32-32)', role: 'Bridges event-level charge physics and instant pre-simulation cross-sections', status: '172 Offline Tests Pass' },
          { layer: 'Leak-Free Splitter', tech: 'splits.py connected-component 3-fold CV', role: 'Clusters shared profiles, reused primaries, and controls into isolated folds', status: 'Verified Offline' }
        ],
        bullets: [
          'Strict discipline: despite 172 passing unit tests, R_ready=false and F_ready=false remain enforced because r0.4 lacks TCAD labels and r0.6 accepted labels are pending.',
          'Formal training and mechanism-vs-MLP ablations will launch only after r0.6 delivers accepted & statistics-eligible cohorts.'
        ]
      },
      {
        id: 'agent-autonomy',
        domain: 'agent',
        num: '05',
        badge: 'Autonomy',
        title: 'server-codex-v2 Event-Driven Scheduler, Provenance & Cold Offload',
        summary: 'Evolved from synchronous scripts into a systemd-sandboxed asynchronous orchestration engine with shared-pool arbitration, advisor consultations, and lossless archiving.',
        stackTable: [
          { layer: 'Event Controller', tech: 'controller.py + runtime.py (systemd ProtectSystem=strict)', role: 'Wakes only on plan/queue/observation shifts; 300–3600s backoff; max 2 repairs', status: '243 Tests Pass' },
          { layer: 'Shared Pool Sidecars', tech: 'scheduler_{engine,collector,probe,admission,planner,pool}', role: 'Serial collector + 5s bounded probe + 3-layer admission + drain-and-switch FSM', status: 'Live' },
          { layer: 'Anti-Spoofing Ledger', tech: 'PID/start_ticks/boot_id + SHA256SUMS + reconciliation', role: 'Prevents PID reuse mismatches; receipt-verified closure without blind resubmits', status: 'Enforced' },
          { layer: 'Two-Stage Cold Offload', tech: 'results.essential.tar.gz + results.raw.tar.gz', role: 'Reclaimed 12.794 GiB on server and 20.942 GiB in VM across 4 multi-core runs', status: 'Verified Savings' }
        ],
        bullets: [
          'Sol delegates complex faults asynchronously to read-only Astra advisor (75.5s verified link) on server management cores while slot refilling continues.',
          'Modular ≤50-line SKILL.md contracts enforce check-before-collect recovery and prohibit redundant full-tree hashing.'
        ]
      },
      {
        id: 'web-telemetry',
        domain: 'web',
        num: '06',
        badge: 'Telemetry & UI',
        title: 'Dual-Rate Read-Only Telemetry, SQLite Triggers & M3 Frontend',
        summary: 'Public visibility without VM exposure: every metric passes through regex redaction and SQLite anti-tamper storage before rendering in zero-CDN Material 3 components.',
        stackTable: [
          { layer: 'Dual-Rate Projectors', tech: 'systemd timers: 15s /live.json + 60s /status.json', role: 'Reads progress.json or trailing 128 KiB logs with 180s freshness & stale fallback', status: 'Live' },
          { layer: 'Immutable Store', tech: 'SQLite user_version=1 + read-only projection + triggers', role: 'Persists Codex progress notes while blocking silent historical overwrites', status: '122 Tests Cover' },
          { layer: 'Redaction Firewall', tech: 'PUBLIC_REDACTION regex + ANON-* masking', role: 'Strips paths, run IDs, PIDs, and all 58 HR/HP holdout details before write', status: 'CI & Deploy Gated' },
          { layer: 'M3 UI & Offline Desk', tech: 'Vite 7.3.8 + @material/web 2.5.0 + deterministic NL parser', role: 'Zero external fonts, adaptive light/dark M3 UI, plus offline research-desk fallback', status: 'Upgraded' }
        ],
        bullets: [
          'status.xjtu.shop and tcad.xjtu.shop share the identical redacted JSON feeds with zero reverse-proxy routes into the CentOS 7.9 VM.',
          'Invited /desk/ inference endpoints return 503 model_pending honestly until formally trained predictor weights are released.'
        ]
      }
    ]
  }
};
