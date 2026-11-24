export const docsArticles = {
  zh: {
    overview: [
      {
        id: 'art-cross-scale',
        title: '跨尺度评估全景：为什么必须串联 Geant4、TCAD、AI 与 Agent 四套系统？',
        readTime: '3 分钟',
        tag: '系统方法论',
        tldr: '单个软件算不全“高能粒子撞芯片→电信号翻转→器件族失效率”的整条因果链，四层各自做最擅长的事并用冻结契约交接。',
        why: '评估 DDR5 / LPDDR5 在辐射环境下的软错误率（SER），横跨四个相差十几个数量级的物理与工程尺度：微米级的粒子核散射、纳米级的硅晶体管载流子漂移、数万次事件的统计学聚合，以及连续数周的多槽位服务器调度。',
        mechanism: '可以把整条流水线比作“接力赛”：第一棒 Geant4 算出粒子在硅里撞出了多少电子—空穴对及分布在哪；第二棒 Sentaurus TCAD 把这些电荷放进晶体管三维网格里，算出存储电容电压会不会掉到翻转阈值以下；第三棒 R→A→F 网络把成千上万次事件汇总并学会举一反三；第四棒 server-codex-v2 像严谨的实验室主管一样，在服务器上全自动排队、核账并防呆。',
        engineering: [
          '第一层（Geant4 10.7.3）：负责高能物理与次级核反应，产出带时空坐标的能量沉积表。',
          '第二层（Sentaurus W-2024.09）：通过外电路混合模式耦合，把单比特写、保持、撞击与差分读出一次性算透。',
          '第三层（R→A→F）：用低阶机理骨架兜底，结合分层权重算出无偏截面与快速宏观预测。',
          '第四层（server-codex-v2）：管理 17 vCPU 共享池与进程防伪链，确保所有输出都能回溯到唯一输入指纹。'
        ],
        evidence: '该分层链路已在 v1–v3 完整交付（v3 达 128 组配对响应）并正在 r0.6 的 396 槽位双主线矩阵中持续运转。',
        snippet: 'Geant4 (MeV 粒子沉积) ──▶ [时空源表] ──▶ TCAD (fC/mV 混合瞬态) ──▶ [四级账本] ──▶ R→A→F (σ / SER)'
      },
      {
        id: 'art-frozen-contract',
        title: '冻结契约与可复现交接：为什么不写一个“一跑到底”的大脚本？',
        readTime: '2 分钟',
        tag: '可复现工程',
        tldr: '“大一统脚本”一旦在第十小时崩掉就前功尽弃；冻结输入指纹与四级状态机，才能让每一棒断点续跑且绝不混淆状态。',
        why: '三维 DRAM 瞬态求解单次耗时可达数小时、归档体积达 3.6–3.9 GB。如果把输运、求解、后处理和训练揉进一个脚本，中间哪怕发生一次服务器重启或网络闪断，就很难分清哪些算例真正算到了终点、哪些只是残缺目录。',
        mechanism: '系统把每个环节的输入文件计算 SHA256SUMS 冻结下来，并规定：数据交接只认“已冻结的清单与回执”，不认口头或临时文件。同时把任务状态严格拆成四级阶梯——“收到压缩包（COLLECTED）”不代表“求解器正常跑到终点（solved）”，更不代表“物理守恒与收敛复核通过（accepted）”或“抽样权重齐全（statistics_eligible）”。',
        engineering: [
          '跨课程与多份报告（如毕业设计与项目报告）共用同一套原始账本与核验图表，严禁为写新报告而复制重跑。',
          '所有历史失败尝试（哪怕是早期语法错误或文件覆盖）永久保留在账本中，只追加新修正版本号，不删改旧记录。'
        ],
        evidence: '该契约已通过 243 项控制器回归测试与 173 项状态投影测试守护，在断网与重连场景下均保持账本一致。'
      }
    ],
    geant4: [
      {
        id: 'art-proton-inelastic',
        title: '高能质子不止“直穿”：通俗拆解 protonInelastic 核非弹性次级级联',
        readTime: '4 分钟',
        tag: '核物理机制',
        tldr: '100 MeV 质子本身电离能力很弱，但一旦撞碎硅原子核，就会原地爆出一簇重反冲核与 α 粒子，这才是诱发纳米 DRAM 翻转的真凶。',
        why: '直觉上很多人以为“能量越高的质子破坏力越大”，但实际上 100 MeV 质子的直接电离阻止本领（LET）很低，直接穿过几十纳米的存储节点往往留不下多少电荷。真正的危险在于极小概率发生的“核非弹性散射（protonInelastic）”。',
        mechanism: '当质子迎头撞上硅原子核，就像高速台球击碎了紧簇的母球堆：会瞬间产生质子（p）、中子（n）、α 粒子、锂-7（Li7）、氧-15（O15）以及随后转化成电子（γ→e⁻）的 γ 光子。这些重反冲核虽然跑不远，却在微米级局部倾泻出几十 MeV 的高密度电荷，足以击穿存储单元电容。',
        engineering: [
          '采用 QGSP_BIC 强子核物理列表搭配 EM option4 高精度低能电磁模块，并锁定核截面数据库版本。',
          '自研 Mother Step ID → Daughter Track ID 血缘追踪表，把每一次核撞击点生长出的全部子轨迹精确归因。'
        ],
        evidence: '在 v4 厚硅机制见证中，212 个 100 MeV 质子事件（共 5,878 条轨迹、46,631 步）成功捕获 9 例合格 protonInelastic 见证，其中典型核反应次级在硅中沉积高达 36.764 MeV。',
        snippet: 'Primary Proton (100 MeV) ─[protonInelastic]─▶ { p, n, α, Li7, O15, γ → e⁻ }  (Si 局部沉积达 36.764 MeV)'
      },
      {
        id: 'art-zero-deposition',
        title: '为什么要花硬盘保留 54,037 条“零沉积”事件？—— 截面分母的无偏铁律',
        readTime: '3 分钟',
        tag: '统计无偏性',
        tldr: '如果只统计“撞中并留下电荷”的幸运粒子，算出来的失效率会凭空放大十倍；必须把“打偏了或零沉积”的事件算进分母。',
        why: '在蒙特卡洛粒子输运里，大多数高能粒子穿过极微小的 DRAM 灵敏体积时，或者直接擦肩而过，或者几乎没有发生能量沉积。科研中最隐蔽的“数据泄漏”之一，就是为了省事只把“有能量沉积”的事件送去算平均概率。',
        mechanism: '设想你在投飞镖测命中率：投了 60,000 支镖，只有 5,963 支留在了靶面上，另外 54,037 支虽然穿过区域却没有在关键灵敏区沉积有效能量。计算翻转截面（σ）时，分母必须是完整的 60,000，而不能偷偷换成 5,963。',
        engineering: [
          'Geant4 输运程序在输出端显式保留零沉积事件计数与几何边界信息，绝不在采集脚本里做静默过滤。',
          '下游统计聚合器 A（Horvitz-Thompson 估计器）直接读取完整初级粒子发射数与抽样纳入概率 π_i，确保截面估计严格无偏。'
        ],
        evidence: 'r0.4 输运快照包含 6 个能角工况（1–120 MeV, 0°–60°）共 60,000 个初级质子：完整保留 5,963 例正沉积与 54,037 例零沉积（总计 546,628 步）。'
      },
      {
        id: 'art-source-conservation',
        title: '把离散径迹“翻译”成连续电流源：205 帧细网格电荷守恒审计',
        readTime: '3 分钟',
        tag: '源项耦合',
        tldr: 'Geant4 算的是“一粒粒点状能量沉积”，TCAD 吃的是“连续时空载流子生成率”，中间必须经过严格的电荷积分守恒审计。',
        why: '粒子在硅中产生的电子—空穴对按物理公式大约每 3.6 eV 产生一对。如果在把 Geant4 坐标离散化投影到 TCAD 有限元网格时发生“丢点”或“插值变形”，后续器件电压降算得再准也是假结果。',
        mechanism: '我们在 0.95–1.05 ns 的粒子轰击窗口内切分出 205 个时间帧，将每一步沉积能量转化为空间三维坐标与时间步上的载流子生成率表格，并在 TCAD 内部把所有网格单元的注入总电荷积分出来，与 Geant4 原始应产生电荷逐帧对比。',
        engineering: [
          '同时核查三项指标：总注入电荷积分误差（要求 <5%）、中心区域能量占比误差（要求 <0.05）、电荷质心偏移量。',
          '对比粗网格与细网格下的存储节点（SN）与位线（BL）电压扰动差，验证空间离散不扭曲读出判决。'
        ],
        evidence: 'v4 205 帧细网格审计结果：A1 源总生成 1.004157 fC（积分偏差仅 0.416%），Center 占比误差 0.014，质心偏移 0.0022 μm；粗细网格 SN/BL 扰动差仅 0.469 / 0.043 mV。'
      }
    ],
    tcad: [
      {
        id: 'art-d1-coupling',
        title: '读出电压为何凭空多出 +12.1 mV？—— D1 栅极耦合机理与中性参考抵消',
        readTime: '4 分钟',
        tag: '器件物理发现',
        tldr: '开启字线晶体管那一瞬间，栅极电容会把 +1.464 fC 电荷“耦合”进存储电容；用同条件中性参考单元做差分，就能把误差从 +12 mV 压回 -0.26 mV。',
        why: '在 v2 实验中，哪怕没有粒子撞击，把字线（WL）打开读出存储单元时，位线电压总是比理想电容分压公式高出约 +12.1 mV，导致存入“1”态的 α 粒子样本在 5 mV 判据下出现大量临界误判。',
        mechanism: '这并非软件 bug，而是真实的半导体物理电容耦合效应。当字线电压在 3–4 ns 拉高以导通存取管时，栅极交叠电容与沟道/衬底耦合会向存储节点（SN）与位线（BL）净注入约 +1.32 ~ +1.46 fC 的额外正电荷。对于仅 10 fF 的微小存储电容来说，这相当于平白抬升了十几毫伏。',
        engineering: [
          'D1 专项设计了 WL 关闭对照、慢开对照与不同初态扫描（9/9 诊断验证通过），证实 WL 关闭时偏移仅 -0.005 mV，锁死罪魁祸首为栅耦合。',
          'v3 起放弃简化的固定 0.5 V 理想参考电压，改用一颗完全相同几何与工艺的“未受辐照中性参考单元”同步开启字线，让两边的栅耦合共模偏移自然相减。'
        ],
        evidence: '实测将读出系统偏置从 +12.01 ~ +13.24 mV 精密抵消至 -0.259 mV（抑制约 98%），为后续 128 算例与 14 nm 器件判定奠定物理基准。'
      },
      {
        id: 'art-atomic-pmi',
        title: '攻克“步间写零”与“千万行日志爆炸”：自研 std::atomic 全局有界日志 C++ PMI',
        readTime: '4 分钟',
        tag: 'C++ 核心扩展',
        tldr: '商业求解器默认局部回调在向后欧拉步间竟然不刷新！我们改用 GCC 编译的全局共享源缓存 + std::atomic 无锁有界日志彻底攻克。',
        why: '要让 Sentaurus TCAD 按 205 帧真实三维时空表逐微步注入电荷，必须通过 C++ 物理模型接口（PMI）接管生成率函数 Compute_r。但在 v4 原生诊断中，我们踩中了一个极隐蔽的求解器机制陷阱。',
        mechanism: '实测发现，标准局部 PMI 的 Compute_r 只在求解器初始化网格顶点时被触发了 49,130 次，随后在连续 957 个向后欧拉（BE）时间步中居然不再回调刷新，导致粒子撞击窗期间注入的源直接变成“主动写零”！另一方面，24,429 个网格顶点在多线程并行下如果直接向标准输出写日志，瞬间就会爆出千万行并发乱码并拖垮 I/O。',
        engineering: [
          '在 r0.6 P0 中重构为进程全局共享时间—空间缓存查找架构，确保每个瞬态子步都能拿到实时插值生成率。',
          '使用 GCC 10.2.0 编译为 .so 动态库，并引入 std::atomic<std::uint64_t> 实现多线程无锁计数与严格有界日志上限，杜绝千万行日志膨胀。'
        ],
        evidence: 'O2 全局原子有界日志 PMI 已在 CentOS 7.9 虚拟机完成编译与实机收集验证，当前正通过 P0 诊断核查极小电流重复性与非零源积分容差。',
        snippet: 'static std::atomic<std::uint64_t> g_log_lines{0};\nif (g_log_lines.fetch_add(1, std::memory_order_relaxed) < kMaxBoundedLogs) { /* bounded trace */ }'
      },
      {
        id: 'art-cnorm-damping',
        title: '三维瞬态为什么会卡步？—— CNorm 电子拒步定位与局部阻尼 LineSearchDamping',
        readTime: '3 分钟',
        tag: '数值收敛调优',
        tldr: '别盲目调松全局收敛精度！精准定位到读出末尾 0.7 ns 窗口内的电子浓度震荡后，仅在局部区间加 0.25 阻尼即可把拒步砍掉 93%。',
        why: '在 0–35 ns 完整“写—保持—读出”瞬态仿真中，D1 写 1 零源算例虽然最后能算出结果，但光是一小段区间就吃掉了整条仿真 63% 的计算时间。',
        mechanism: '通过逐段剖分牛顿迭代日志，我们精确定位到卡顿集中在 [30.200, 30.925] ns 的读出耦合尾段：该时段 2264/2191 号网格顶点上电子连续性方程（CNorm）反复出现小幅过冲，触发了 139 次时间步拒绝回退。',
        engineering: [
          '不以牺牲全局误差容差为代价换取速度，而是仅在读出耦合窄时间窗内精准施加局部 LineSearchDamping = 0.25。',
          '调优前后仍严格比对关键节点读出裕量，确保物理曲线未被人为扭曲。'
        ],
        evidence: '施加局部阻尼后，该开区间内的牛顿拒步次数由 114/421 锐减至 8/57，而 31.9 ns 处的存储节点读出裕量仍稳定保持在 +26.154 mV（与 D0 基线 +26.214 mV 高度一致）。'
      }
    ],
    ai: [
      {
        id: 'art-raf-philosophy',
        title: '为什么不用纯黑盒 MLP？—— 拆解 R → A → F 物理约束三阶段哲学',
        readTime: '4 分钟',
        tag: '物理引导机器学习',
        tldr: 'TCAD 算例极其昂贵，纯黑盒神经网络一离开训练集就胡说；用低阶 RC 机理公式做主干、神经网络只学残差，外推才能稳。',
        why: '即便用满服务器算力，一个精细三维矩阵也就几百条高价值 TCAD 样本。对于维度包含器件结构、粒子能量/角度、击中坐标与存储态的问题，纯黑盒多层感知机（MLP）极易在训练集外出现负截面或违背物理单调性的荒谬预测。',
        mechanism: '我们把评估拆成三棒：R（Event Response）先把电容充放电的 RC 机理骨架算出来，再用轻量的 64-64 SiLU MLP 去补足三维边界上的非线性残差；A（Aggregator）把 R 算出的单事件翻转概率结合真实灵敏面积与 Horvitz-Thompson 分层权重聚合出无偏截面；F（Fast Macro Head）只看仿真前器件与辐照参数，用 32-32 SiLU 接双非负 Softplus 头直接输出宏观截面与错误率区间。',
        engineering: [
          'R 阶段联合优化连续电荷/电压 Huber 损失、翻转二元交叉熵（BCE）与残差 L2 正则。',
          'F 阶段原生计数直接对齐 Poisson 对数似然，代理标签采用 asinh-Huber 鲁棒损失。',
          'Softplus 输出层在结构上保证预测翻转截面永远大于等于零。'
        ],
        evidence: '在前期 v3 128 算例上，带物理特征的岭回归基线已展示出极强外推力：Holdout (L=0.25 μm) ΔM MAE 仅 0.527/0.550 mV，外推至未见尺寸 L=0.45 μm 时 MAE 仍低至 0.405/0.388 mV（相对 ~19.2 mV 均值基线降幅超 97%）。',
        snippet: 'Event x ─▶ [R: RC机理 + 64×64 SiLU残差] ─▶ p_seu ─▶ [A: Horvitz-Thompson无偏聚合] ─▶ σ_hat ◀─ [F: 32×32 Softplus]'
      },
      {
        id: 'art-leak-free-splits',
        title: '防泄漏底线：splits.py 连通分量分组与当前 172 离线测试诚实边界',
        readTime: '3 分钟',
        tag: '科学防泄漏',
        tldr: '同一颗器件、同一次 Geant4 初级粒子或同一条无粒子对照，绝不能一半进训练集、一半进测试集；代码已过 172 项测试，但正式训练严格等待 r0.6 全量合格数据。',
        why: '如果在普通随机划分下，把相同器件工艺变体或同一组粒子输运派生的不同击中点分别放进训练集和验证集，模型靠“背题”就能刷出极低误差，却会在面对真正新器件时彻底失效。',
        mechanism: 'splits.py 把样本之间的共享关系（相同的 profile、复用的 primary 粒子、关联的对照样本与统计来源）建成一张无向图，先提取“连通分量”，再以整个连通分量为不可拆分的最小原子块做 3 折分组交叉验证，并彻底隔离 58 条 HR/HP 留出案例。',
        engineering: [
          '代码包（PyTorch >=2.6 CPU 版 + uv 管理）已实现 R/A/F 全链路、校验器与端到端离线集成测试。',
          '严格执行就绪开关：目前因 r0.4 快照缺少配对 TCAD 响应、r0.6 正式矩阵尚未全量收齐，R_ready 与 F_ready 明确保持 false，尚未对外发布正式预测曲线。'
        ],
        evidence: '当前 predictor 仓库已通过 172 项离线单元测试；将在 r0.6 正式矩阵与统计资格快照闭合后，正式启动超参搜索及“机理+残差 vs 纯 MLP”消融实验。'
      }
    ],
    agent: [
      {
        id: 'art-double-isolation',
        title: '既要全自动并发，又要管住 AI 不乱动账本：双层隔离、共享池与 Sol+Astra 会诊',
        readTime: '4 分钟',
        tag: 'Agent 工程治理',
        tldr: '让服务器只做控制和只读公开、虚拟机断网专心算物理、AI 顾问只提诊断不碰文件，四重锁死把自主Agent变成靠谱的科研工程师。',
        why: '直接让 AI Agent 在跑着商业 TCAD 许可和数百 GB 结果的机器上自由执行 bash，一旦遇到断网或并发冲突，Agent 很容易出现“误删热目录、重复提交同一批任务、甚至强杀正在收敛的求解器”等灾难性操作。',
        mechanism: '我们将 Rocky Linux 9 服务器与 CentOS 7.9 仿真虚拟机物理解耦：控制器在 systemd 严格沙箱（ProtectSystem=strict, NoNewPrivileges）下通过事件驱动唤醒，绝不靠死循环轮询；调度采用“唯一串行收集器 + 5 秒有界探针 + 保守准入”侧车架构。遇到疑难收敛故障时，主控 Sol 异步召唤运行在管理核上的只读顾问 Astra（75.5s 实测联通），会诊期间主引擎照常推进收集与补槽。',
        engineering: [
          '17 vCPU 共享池精细划分：CPU0–11 为 12 个单核 TCAD 槽位，CPU12–15 为 1 个四核大网格槽位，CPU16 留虚拟机后台，Geant4 在空闲池轮换 ≤4 并发。',
          'watchdog 只发心跳与滞留告警，绝不擅自强杀活跃进程；回执对账（intent_reconciliation）必须拿到完整侧回执才闭合未启动意图。',
          '将全部操作铁律固化进 ≤50 行的模块化 SKILL.md 契约中。'
        ],
        evidence: 'server-codex-v2 已通过 243 项控制器回归测试、7 项运行器协议测试与 30 项 Geant4 回归测试，并在真实生产队列中完成接管。'
      },
      {
        id: 'art-provenance-offload',
        title: '驯服单次近 4 GB 的瞬态归档：进程身份链、三层不相加口径与两步冷备',
        readTime: '3 分钟',
        tag: '存储与防伪',
        tldr: '用 PID + start_ticks + boot_id 锁死进程身份防重启误认，并用 essential + raw 两步无损归档实测帮虚拟机省下 20.94 GiB 空间。',
        why: '一条长瞬态仿真不仅耗时数小时，未压缩输出目录动辄 3.6–3.9 GB；同时在虚拟机和服务器套娃架构下，把虚拟磁盘逻辑剩余容量误当成服务器物理剩余空间，极易导致物理盘写穿崩溃。',
        mechanism: '首先确立三层空间与内存互不相加原则：服务器剩余、服务器上虚拟机磁盘文件可增长空间、虚拟机剩余三者独立核算，准入永远取最紧阈值。其次对大归档实行“ready → finalize”两步瘦身：ready 阶段先打好核心分析小包（essential.tar.gz）与逐字节可还原无损包（raw.tar.gz）并校验流式免解压读取无误后，立即删掉笨重的未压缩热目录。',
        engineering: [
          '每次运行绑定 PID + start_ticks + boot_id 三元组，杜绝虚拟机重启后 PID 复用导致的错误收割。',
          'Python 后处理直接使用流式 tarfile 免解压读取提取波形与误差曲线，不产生二次临时解包目录。'
        ],
        evidence: '4 份多核实测归档验证：两步冷备共节省服务器空间 12.794 GiB、节省虚拟机空间 20.942 GiB，而精简核心分析包合计仅 147.66 MiB。'
      }
    ],
    web: [
      {
        id: 'art-redaction-pipeline',
        title: '内网算力如何安全晒到公网？—— 双频投影、SQLite 防篡改与 ANON-* 封存网关',
        readTime: '3 分钟',
        tag: '安全遥测',
        tldr: '公网端永远是纯静态文件 + 只读脱敏 JSON；一切内部路径、run_id、PID 与 58 条留出测试明细都在进入公网前被正则防火墙彻底剥离。',
        why: '我们希望科研进度（正在跑几核、处于微步收敛还是慢收敛、已核验几条算例）对评审与合作者全天候透明，但同时必须遵守实验室脱敏与防泄漏红线，绝不能在公网暴露服务器目录、许可证或测试集留出案例细节。',
        mechanism: '服务器通过 systemd 双频定时器分别每 15 秒生成轻量 /live.json、每 60 秒生成全量 /status.json。探针只读 progress.json 或日志末尾 128 KiB，绝不扫描庞大结果目录；所有任务标签先经安全别名映射，58 条 HR/HP 留出案例强制匿名成 ANON-* 且只暴露安全区块计数。',
        engineering: [
          'SQLite 进展库（user_version=1）配置只读投影视图与防历史覆盖触发器，确保过往排查记录可追溯。',
          '写入公网目录前执行 PUBLIC_REDACTION 正则校验并采用同目录原子 replace；若上游损坏则安全回退上一版并标为 cached_stale。'
        ],
        evidence: '状态检查器与脱敏投影已由 173 项单元测试及每次发布前的自动化正则审计双重守护，前端默认 180s 无更新即提示过期。'
      },
      {
        id: 'art-m3-offline-desk',
        title: '零外链 Google M3 前端与断网降级：研究台离线词表解析器设计',
        readTime: '3 分钟',
        tag: 'Web 与交互设计',
        tldr: '全站不依赖任何外网字体或 CDN 脚本，用原生 ESM + @material/web 2.5.0 打造亮暗自适应界面，并为受邀研究台准备了断网可用的词表解析器。',
        why: '科研门户常需在受限校园网或内网离线环境下稳定打开。如果页面依赖外部 Google Fonts CDN 或重型在线推理脚本，一旦断网就会出现白屏、字体回退错位或功能瘫痪。',
        mechanism: '前端全量打包本地系统字体栈、内联矢量 SVG 图标集与 @material/web 2.5.0 官方 Web Components，在 HTML 头部注入轻量防闪烁脚本同步亮/暗主题与中英文状态。同时针对配套的受邀研究台 /desk/，在离线页面内置了确定性中文自然语言词表解析器，即使脱离后端大模型也能精准拆解器件尺寸、粒子与角度参数。',
        engineering: [
          'Vite 多页打包将公共 M3 组件拆分为共享 chunk（site-shell），实现主页与 /docs/ 秒开切换。',
          '/desk/ 在线预测端点在模型训练完成前诚实返回 503 model_pending 占位响应，绝不用假数据充数。'
        ],
        evidence: '当前门户（tcad.xjtu.shop、/docs/ 与 status.xjtu.shop）均已通过跨桌面/移动端及亮暗双主题实测校验，零外链阻断风险。'
      }
    ]
  },
  en: {
    overview: [
      {
        id: 'art-cross-scale',
        title: 'Cross-Scale Pipeline: Why Chain Geant4, TCAD, Physics AI & Agent Autonomy?',
        readTime: '3 min',
        tag: 'Methodology',
        tldr: 'No single simulator spans nuclear scattering to circuit upset and fleet orchestration; four specialized layers hand off via frozen contracts.',
        why: 'Assessing DDR5/LPDDR5 soft-error rates bridges scales separated by over 12 orders of magnitude: MeV nuclear tracks, nanometer drift-diffusion transients, unbiased cross-section statistics, and multi-week cluster orchestration.',
        mechanism: 'Think of it as a four-leg relay race: Geant4 records where secondary ions deposit charge; Sentaurus TCAD injects that charge into 3D transistor meshes to test bit-flip margins; the R→A→F network aggregates unbiased cross-sections and generalizes across devices; and server-codex-v2 schedules, audits, and safeguards every step.',
        engineering: [
          'Layer 1 (Geant4 10.7.3): tracks primary ions and nuclear secondaries into space-time deposition tables.',
          'Layer 2 (Sentaurus W-2024.09): runs coupled Write-Hold-Strike-Readout mixed-mode transients.',
          'Layer 3 (R→A→F): pairs a physical RC skeleton with stratified Horvitz-Thompson estimators.',
          'Layer 4 (server-codex-v2): arbitrates the 17-vCPU shared pool and provenance ledger.'
        ],
        evidence: 'Validated end-to-end across v1–v3 (128 paired responses delivered) and actively driving the 396-slot r0.6 campaign.',
        snippet: 'Geant4 (MeV tracks) ──▶ [Space-Time Source] ──▶ TCAD (fC/mV transient) ──▶ [4-Tier Ledger] ──▶ R→A→F (σ / SER)'
      },
      {
        id: 'art-frozen-contract',
        title: 'Frozen Contracts & Resumable Handoffs Over Monolithic Scripts',
        readTime: '2 min',
        tag: 'Reproducibility',
        tldr: 'Monolithic scripts fail catastrophically on multi-hour 3D runs; frozen SHA256SUMS and 4-tier states make every step auditable and resumable.',
        why: 'A single 3D DRAM transient can run for hours and emit 3.6–3.9 GB archives. Without strict stage boundaries, a transient disconnect makes it impossible to tell finished physics runs from partial directories.',
        mechanism: 'Every stage freezes input SHA256SUMS and separates status into four distinct tiers: COLLECTED (archived) never implies solved (clean exit), which never implies accepted (physics & convergence audited) or statistics_eligible (full sampling weights).',
        engineering: [
          'Downstream reports and theses reuse the exact canonical ledger and verified figures without duplicating or re-running experiments.',
          'Historical failed runs remain immutable in the ledger; fixes append new revision records rather than erasing past trails.'
        ],
        evidence: 'Protected by 243 controller regression tests and 173 status-projection tests.'
      }
    ],
    geant4: [
      {
        id: 'art-proton-inelastic',
        title: 'Beyond Direct Ionization: How 100 MeV protonInelastic Cascades Flip DRAM Cells',
        readTime: '4 min',
        tag: 'Nuclear Physics',
        tldr: 'A 100 MeV proton barely ionizes on its own, but hitting a silicon nucleus triggers a dense burst of heavy recoils and alphas that flip bits.',
        why: 'High-energy protons have low linear energy transfer (LET) when passing straight through silicon. The dominant threat to nanoscale DRAM comes from rare inelastic nuclear collisions inside or near the sensitive junction.',
        mechanism: 'When a 100 MeV proton shatters a silicon nucleus via protonInelastic scattering, it emits a localized shower of protons (p), neutrons (n), alpha particles, Li7, O15, and gamma photons converting to electrons (γ→e⁻) that dump tens of MeV within micrometers.',
        engineering: [
          'Pairs QGSP_BIC hadronic models with EM option4 physics and pinned nuclear data tables.',
          'Custom Mother Step ID → Daughter Track ID ancestry tables trace every secondary cascade back to its primary reaction vertex.'
        ],
        evidence: 'In the v4 witness campaign (212 100 MeV protons, 5,878 tracks, 46,631 steps), 9 qualified protonInelastic witnesses deposited up to 36.764 MeV in silicon.',
        snippet: 'Primary Proton (100 MeV) ─[protonInelastic]─▶ { p, n, α, Li7, O15, γ → e⁻ }  (up to 36.764 MeV in Si)'
      },
      {
        id: 'art-zero-deposition',
        title: 'Why Preserve 54,037 Zero-Deposition Protons? The Unbiased Denominator Rule',
        readTime: '3 min',
        tag: 'Statistical Rigor',
        tldr: 'Dropping non-depositing primaries inflates estimated cross-sections by an order of magnitude; all zero-deposition events stay in the denominator.',
        why: 'Most high-energy particles cross microscopic DRAM cells without depositing significant charge. Filtering them out before computing upset rates is a classic hidden selection bias.',
        mechanism: 'If 60,000 protons are fired and only 5,963 deposit energy, the cross-section denominator must remain 60,000 (weighted properly by sampling inclusion probabilities π_i), never 5,963.',
        engineering: [
          'Geant4 transport binaries record explicit zero-deposition tallies alongside positive hit records.',
          'Stage A (Horvitz-Thompson aggregator) reads exact total primary counts and stratum probabilities.'
        ],
        evidence: 'r0.4 transported 60,000 primaries across 6 conditions (1–120 MeV, 0°–60°), retaining all 54,037 zero-deposition tracks alongside 5,963 hits.'
      },
      {
        id: 'art-source-conservation',
        title: 'Translating Discrete Tracks to Continuous Currents: 205-Frame Charge Conservation Audit',
        readTime: '3 min',
        tag: 'Source Coupling',
        tldr: 'Discrete Geant4 energy steps must map onto finite-element TCAD meshes without losing charge or shifting the hit centroid.',
        why: 'Grid interpolation bugs during space-time carrier generation mapping can silently distort transient currents even when both Geant4 and TCAD converge.',
        mechanism: 'Across 205 frames in the 0.95–1.05 ns strike window, deposited energy is converted into 3D carrier generation density tables and integrated inside TCAD to verify total injected charge against the raw physics target.',
        engineering: [
          'Audits total integral error (<5% threshold), center-region fraction error (<0.05), and charge centroid drift.',
          'Cross-checks coarse vs fine mesh perturbations on both storage-node (SN) and bitline (BL) voltages.'
        ],
        evidence: 'v4 205-frame fine-mesh audit verified 1.004157 fC native generation (0.416% error), 0.0022 μm centroid drift, and ≤0.469 mV mesh perturbation.'
      }
    ],
    tcad: [
      {
        id: 'art-d1-coupling',
        title: 'Why Did Readout Voltage Shift by +12.1 mV? D1 Gate Coupling & Neutral Cancellation',
        readTime: '4 min',
        tag: 'Device Physics',
        tldr: 'Wordline turn-on injects +1.464 fC via gate overlap capacitance; pairing a matched neutral reference cell cancels 98% of the bias down to -0.259 mV.',
        why: 'In v2, even without radiation, opening the wordline produced a systematic +12.1 mV positive shift on bitline readout, creating false marginal readouts for stored bit-1 alpha strikes.',
        mechanism: 'D1 deterministic sweeps proved that raising the wordline gate during 3–4 ns couples +1.464 fC through the gate-to-storage-node overlap (partially offset by substrate coupling), injecting +1.32 to +1.46 fC onto a tiny 10 fF storage capacitor.',
        engineering: [
          'D1 verified 9/9 deterministic controls, confirming the WL-off baseline has only -0.005 mV drift.',
          'v3 replaced the fixed 0.5 V reference with an identical unirradiated neutral cell switched in lockstep so common-mode coupling cancels out.'
        ],
        evidence: 'Differential readout offset dropped from +12.01 ~ +13.24 mV down to -0.259 mV (~98% cancellation).'
      },
      {
        id: 'art-atomic-pmi',
        title: 'Solving Missed Step Refreshes & I/O Explosions: Atomic Bounded-Log C++ PMI',
        readTime: '4 min',
        tag: 'C++ Extension',
        tldr: 'Standard local PMI callbacks skipped 957 backward-Euler steps; our global cached source with std::atomic bounded tracing fixes both accuracy and thread contention.',
        why: 'Injecting time-varying 205-frame 3D carrier profiles requires a custom Sentaurus C++ PMI shared library implementing Compute_r.',
        mechanism: 'v4 diagnostics revealed local Compute_r was called 49,130 times at initialization but stopped refreshing across 957 BE transient steps, writing zero source mid-strike. Worse, naively logging across 24,429 mesh vertices in multi-threaded runs generates multi-million-line I/O lock contention.',
        engineering: [
          'Rebuilt for r0.6 as a process-global cached space-time lookup compiled with GCC 10.2.0.',
          'Uses lock-free std::atomic<std::uint64_t> counters to enforce strict bounded diagnostic trace budgets.'
        ],
        evidence: 'O2 global atomic PMI compiled and collected cleanly inside the CentOS 7.9 VM; P0 repeatability and non-zero source integral proofs are actively closing.',
        snippet: 'static std::atomic<std::uint64_t> g_log_lines{0};\nif (g_log_lines.fetch_add(1, std::memory_order_relaxed) < kMaxBoundedLogs) { /* bounded trace */ }'
      },
      {
        id: 'art-cnorm-damping',
        title: 'Fixing 3D Transient Stalls: Targeted CNorm Step-Rejection Damping',
        readTime: '3 min',
        tag: 'Solver Tuning',
        tldr: 'Instead of loosening global accuracy, applying LineSearchDamping=0.25 strictly inside a 0.725 ns readout tail window cut solver rejections by 93%.',
        why: 'One narrow readout window in D1 zero-source transient runs consumed 63% of total wall-clock time due to repeated Newton step rejections.',
        mechanism: 'Log profiling isolated 139 electron continuity (CNorm) overshoot rejections on vertices 2264/2191 inside [30.200, 30.925] ns.',
        engineering: [
          'Scoped LineSearchDamping=0.25 solely to that narrow window while leaving write, hold, and strike tolerances untouched.',
          'Verified post-damping readout margin against un-damped baselines.'
        ],
        evidence: 'Cut open-interval rejections from 114/421 down to 8/57 while preserving the 31.9 ns margin at +26.154 mV (matching D0 +26.214 mV).'
      }
    ],
    ai: [
      {
        id: 'art-raf-philosophy',
        title: 'Why Not a Black-Box MLP? Inside the R → A → F Physics-Constrained Design',
        readTime: '4 min',
        tag: 'Physics-Guided AI',
        tldr: 'TCAD data is scarce; anchoring predictions on an RC charge skeleton while learning only residuals preserves physical monotonicity.',
        why: 'Even with full cluster automation, a 3D TCAD campaign yields hundreds—not millions—of labeled devices. Black-box MLPs easily predict negative cross-sections or inverted length scaling out-of-domain.',
        mechanism: 'Stage R pairs a calibratable RC charge-collection skeleton with a 64-64 SiLU residual MLP; Stage A computes unbiased Horvitz-Thompson cross-sections; Stage F uses a 32-32 SiLU network with dual non-negative Softplus heads for instant pre-simulation estimates.',
        engineering: [
          'Stage R optimizes Huber (continuous ΔQ/ΔV/ΔM) + BCE (upset) + residual L2 regularization.',
          'Stage F trains with exact Poisson likelihood on raw counts and asinh-Huber loss on surrogate targets.'
        ],
        evidence: 'On the frozen v3 128-case dataset, physics-feature ridge regression reduced ΔM MAE from ~19.2 mV down to 0.527/0.550 mV (holdout) and 0.405/0.388 mV (extrapolation L=0.45 μm).',
        snippet: 'Event x ─▶ [R: RC + 64×64 SiLU] ─▶ p_seu ─▶ [A: Horvitz-Thompson] ─▶ σ_hat ◀─ [F: 32×32 Softplus]'
      },
      {
        id: 'art-leak-free-splits',
        title: 'Leak-Free Discipline: Connected-Component Splits & 172 Offline Tests',
        readTime: '3 min',
        tag: 'Leakage Prevention',
        tldr: 'Variants sharing a device profile, primary ion, or control never cross train/val folds; 172 unit tests pass while formal training awaits full r0.6 labels.',
        why: 'Random row-level splitting leaks shared device baselines and reused Geant4 primaries across folds, inflating validation scores.',
        mechanism: 'splits.py constructs an undirected graph connecting shared profiles, primaries, controls, and statistical sources, running 3-fold group cross-fitting at the connected-component level while isolating 58 sealed HR/HP cases.',
        engineering: [
          'Full PyTorch >=2.6 (CPU) training, validation, and calibration package passes 172 offline tests.',
          'Honest readiness gates: R_ready=false and F_ready=false remain enforced until r0.6 delivers accepted & statistics-eligible cohorts.'
        ],
        evidence: 'Formal hyperparameter tuning and mechanism-vs-MLP ablations will trigger automatically once r0.6 cohorts clear scientific gates.'
      }
    ],
    agent: [
      {
        id: 'art-double-isolation',
        title: 'Full Autonomy Without Ledger Corruption: Two-Tier Isolation & Sol + Astra',
        readTime: '4 min',
        tag: 'Agent Governance',
        tldr: 'Air-gapped VM execution, event-driven systemd sandboxing, and read-only Astra advisor consultations keep concurrency safe and auditable.',
        why: 'Granting an autonomous LLM unrestricted shell access over live TCAD licenses and multi-GB archives risks silent overwrites, blind resubmits, or premature solver kills.',
        mechanism: 'Rocky Linux 9 hosts the sandboxed controller (ProtectSystem=strict, NoNewPrivileges) talking over loopback-only links to the air-gapped CentOS 7.9 VM. Sol handles planning and invokes read-only Astra (75.5s verified link) asynchronously on server management cores without stalling slot collection or replenishment.',
        engineering: [
          '17-vCPU pool allocates 12×1-core + 1×4-core TCAD slots plus ≤4 rotating single-core Geant4 jobs.',
          'Watchdog emits non-destructive alerts; intent_reconciliation requires full receipts before closing unlaunched intents.',
          'Operational guardrails live in concise ≤50-line SKILL.md contracts.'
        ],
        evidence: 'Verified by 243 controller regression tests, 7 runner protocol tests, and 30 Geant4 tests.'
      },
      {
        id: 'art-provenance-offload',
        title: 'Taming 3.9 GB Transients: Provenance Chains & Two-Stage Lossless Offload',
        readTime: '3 min',
        tag: 'Storage & Provenance',
        tldr: 'PID + start_ticks + boot_id stops PID-reuse misattribution, while essential + raw archiving reclaimed 20.94 GiB inside the VM.',
        why: 'Long 3D transient outputs reach 3.6–3.9 GB each, and confusing logical VM disk space with physical server free space risks exhausting host storage.',
        mechanism: 'Admission enforces strict non-additive 3-layer accounting (server free, VM image growth headroom, VM free). Two-stage archiving writes compact essential.tar.gz + byte-identical raw.tar.gz, verifies streaming reads, and only then prunes uncompressed hot directories.',
        engineering: [
          'Every run binds kernel PID + start_ticks + boot_id alongside frozen input SHA256SUMS.',
          'Python post-processing streams directly from tar archives without re-extracting multi-GB temp trees.'
        ],
        evidence: 'Measured across 4 multi-core runs: saved 12.794 GiB on the server and 20.942 GiB in the VM (essential bundle totaled 147.66 MiB).'
      }
    ],
    web: [
      {
        id: 'art-redaction-pipeline',
        title: 'Publishing Live Progress Safely: Dual-Rate Projectors & ANON-* Redaction Firewall',
        readTime: '3 min',
        tag: 'Security Telemetry',
        tldr: 'Public pages consume strictly static builds + regex-redacted JSON; all paths, run IDs, PIDs, and 58 HR/HP holdouts are stripped at projection time.',
        why: 'External reviewers need live visibility into solver convergence and cohort progress without exposing private paths, licenses, or sealed holdout test cases.',
        mechanism: 'Dual systemd timers emit 15s /live.json and 60s /status.json by reading progress.json or trailing 128 KiB log slices. PUBLIC_REDACTION regex filters scrub sensitive tokens while mapping sealed holdout tasks to ANON-* placeholders.',
        engineering: [
          'SQLite store (user_version=1) enforces read-only views and anti-overwrite triggers.',
          'Atomic same-directory replacement falls back cleanly to cached_stale if upstream validation fails.'
        ],
        evidence: 'Guarded by 173 unit tests and pre-deploy redaction checks; UI flags feeds older than 180s as stale.'
      },
      {
        id: 'art-m3-offline-desk',
        title: 'Zero-CDN Material 3 Frontend & Offline Deterministic Desk Parser',
        readTime: '3 min',
        tag: 'Web Engineering',
        tldr: 'Zero external fonts or CDN scripts ensure reliable loading under restricted networks, paired with an offline parser for the invited research desk.',
        why: 'Academic portals must remain responsive behind restricted campus networks or air-gapped reviews without external font blocking.',
        mechanism: 'Bundles system font stacks, inline SVG icons, and @material/web 2.5.0 Web Components with anti-FOUC Light/Dark and EN/ZH bootstrap scripts. The invited /desk/ app includes a deterministic offline Chinese vocabulary parser when disconnected.',
        engineering: [
          'Vite multi-page bundling shares the common site-shell chunk across / and /docs/.',
          '/desk/ prediction endpoints honestly return 503 model_pending until trained weights land.'
        ],
        evidence: 'Verified across desktop and mobile viewports in both light and dark modes with zero external network dependencies.'
      }
    ]
  }
};
