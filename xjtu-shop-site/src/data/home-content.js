export const homeContent = {
  zh: {
    hero: {
      chip: '查看全栈技术文档',
      eyebrow: 'XJTU · RADIATION EFFECTS & AI AUTONOMY',
      title: 'DRAM 单粒子效应评估研究',
      formalTitle: 'AI辅助下的DRAM存储器单粒子效应评估研究',
      lead: '打通 Geant4 粒子输运、Sentaurus TCAD 混合模式瞬态求解、R→A→F 物理约束预测与服务器 Agent 自治调度，构建面向 DDR5 / LPDDR5 的可追溯单粒子效应评估链路。',
      ctaPrimary: '查看仿真成果',
      ctaDocs: '技术文档',
      ctaStatus: '实时状态',
      blueprintTitle: '1T1C DRAM 单粒子物理机理交互示意',
      blueprintHint: '点击节点切换下方四层研究契约',
      simDemoBadge: '物理机理示意 · Mechanism Demo',
      simFireBtn: '发射粒子',
      simClickHint: '点击硅衬底任意位置触发粒子入射',
      simNodeDropLabel: '存储节点响应',
      simReadoutLabel: '特征口径',
      simPresets: [
        {
          id: 'v4',
          label: 'v4 · 100 MeV 质子核反应',
          statLabel: '次级核沉积峰',
          caption: '100 MeV 质子进入硅衬底触发 protonInelastic 核反应顶点，分支级联次级轻核与重离子电离产生瞬态漏电收集。'
        },
        {
          id: 'v3',
          label: 'v3 · LET 漏斗收集',
          statLabel: '电离柱条件',
          caption: '高 LET 电离径迹在电场漏斗效应下向存储节点电容（SN）快速漂移收集，驱动 ΔV_SN 与位线电位偏移。'
        },
        {
          id: 'd1',
          label: 'D1 · 差分偏置抵消',
          statLabel: '共模偏置变化',
          caption: '固定参考单元叠加 +12.01 ~ +13.24 mV 字线耦合正偏；切换全匹配中性参考后共模抵消约 98%，剩 -0.259 mV 残余。'
        }
      ],
      nodes: [
        {
          id: 'geant4',
          step: '01',
          name: 'Geant4 10.7.3',
          role: '核非弹性输运与零沉积保留',
          badge: '60,000+ 初级事件',
          detail: '采用 QGSP_BIC + EM Opt4 与母步—子轨迹血缘追踪；完整保留零沉积事件以保证翻转截面分母无偏。'
        },
        {
          id: 'tcad',
          step: '02',
          name: 'Sentaurus TCAD',
          role: '混合模式瞬态与原子 PMI',
          badge: '14 nm Saddle-Fin',
          detail: '覆盖平面 1T1C、BCAT 与 Saddle-Fin 器件；自研全局原子有界日志 C++ PMI 解决 24k+ 顶点竞争与步间刷新缺陷。'
        },
        {
          id: 'predictor',
          step: '03',
          name: 'R → A → F 网络',
          role: '物理约束预测与分层聚合',
          badge: '172 离线测试通过',
          detail: '低阶机理+残差（R）→ Horvitz-Thompson 无偏聚合（A）→ 仿真前宏观截面头（F）；正式训练等待 r0.6 全量合格标签。'
        },
        {
          id: 'agent',
          step: '04',
          name: 'server-codex-v2',
          role: '双层隔离与异步共享池',
          badge: '17 vCPU 共享池',
          detail: 'Rocky Linux 9 控制面协同隔离 CentOS 7.9 虚拟机，结合 Sol/Astra 顾问与四级防伪账本稳定推进求解。'
        }
      ]
    },
    signals: {
      stageLabel: '当前运行阶段',
      stageFallback: '正在同步仿真进度…',
      matrixLabel: 'r0.6 正式矩阵（P0 独立）',
      matrixFallback: '396 正式槽位（含 58 留出封存）',
      milestoneLabel: '已审计核心里程碑',
      milestoneText: 'v3 128 算例 · v4 9 例核见证 · r0.4 6 万质子',
      healthLabel: '服务健康状态',
      planned: '计划',
      solved: '求解',
      accepted: '验收',
      running: '运行中'
    },
    workbench: {
      stepLabel: '专题视图',
      prevLabel: '上一专题',
      nextLabel: '下一专题',
      keyboardHint: 'Alt + ← / → 快捷切换',
      exploreAllCue: '4 大专题工作台 · 点击任意卡片直达',
      loopBackLabel: '回到首屏专题',
      jumpDocsLabel: '进入完整技术文档中心',
      views: [
        {
          id: 'results',
          num: '01',
          short: '仿真成果',
          caption: 'v1–r0.6 成果与实时图表',
          teaser: '多代次 DRAM SEE 实测指标、v3 128 算例误差降幅与 r0.6 在研阵列进度。'
        },
        {
          id: 'architecture',
          num: '02',
          short: 'Agent 架构',
          caption: '双层隔离与流程仿真',
          teaser: 'server-codex-v2 在服务器与仿真虚拟机间的动态调度与隔离红线演示。'
        },
        {
          id: 'evidence',
          num: '03',
          short: '证据账本',
          caption: '四级口径与科学边界',
          teaser: 'COLLECTED ≠ solved ≠ accepted ≠ statistics_eligible 契约与未决事项。'
        },
        {
          id: 'status',
          num: '04',
          short: '状态与文档',
          caption: '实时探针与技术源码指南',
          teaser: '关联 status.xjtu.shop 实时健康快照，直达 6 章深度技术文档中心。'
        }
      ]
    },
    arch: {
      eyebrow: 'SERVER AGENT ARCHITECTURE',
      title: '双层隔离与 server-codex-v2 自治架构',
      lead: '控制面与仿真执行面严格分离，依靠异步共享池、进程身份链与 Fail-Closed 门禁保障高并发下的数据真实性。',
      guardrailSwitch: '显示工程防呆红线',
      tabs: [
        {
          id: 'isolation',
          label: '双层物理隔离',
          summary: '公网只读展示、服务器自治控制与离线仿真虚拟机三层职责边界清晰。',
          cards: [
            {
              title: 'Rocky Linux 9 服务器（20 核控制面）',
              badge: '控制面 · 公网只读',
              tone: 'primary',
              points: [
                '托管静态门户与双频脱敏遥测（15s /live.json + 60s /status.json）。',
                '控制器运行于 systemd 严格沙箱，CPU17–19 专留控制与顾问推理。',
                '切断一切向虚拟机的反向代理，严禁暴露内部路径与 run_id。'
              ],
              guardrail: '红线：公网端零穿透；SQLite 只读投影配防篡改触发器。'
            },
            {
              title: 'CentOS 7.9 仿真虚拟机（17 vCPU + 28 GiB）',
              badge: '执行面 · 无公网暴露',
              tone: 'teal',
              points: [
                '仅经本地回环端口受控提交，虚拟机完全不对公网开放。',
                '13 个 TCAD 槽位：CPU0–11（12×1核）+ CPU12–15（1×4核），CPU16 留后台。',
                'Geant4 沿用单核 profile 最多 4 并发，在空闲共享池内按需轮换。'
              ],
              guardrail: '红线：共享池切换须全部锁空闲且无未登记求解器。'
            }
          ]
        },
        {
          id: 'scheduler',
          label: '异步共享池调度',
          summary: '以事件驱动与单通道收集取代阻塞轮询，防止并发死锁与盲目重投。',
          cards: [
            {
              title: '异步共享池侧车流水线',
              badge: 'server-codex-v2',
              tone: 'primary',
              points: [
                'controller.py 仅由计划/队列/观测变更唤醒，异常按 300–3600s 指数退避。',
                '唯一串行归档通道（concurrency=1）搭配 5s 有界只读状态采样。',
                '准入器结合三层剩余空间与未覆盖 RSS 执行保守放行。'
              ],
              guardrail: '红线：watchdog 只告警不强杀求解进程，防止静默丢数。'
            },
            {
              title: 'Fail-Closed 门禁与回执对账',
              badge: '唯一科学账本',
              tone: 'good',
              points: [
                'r06_gate 逐提交核验物理完整性与收尾条件，未过关禁止入库。',
                'intent_reconciliation 凭完整回执核销未启动意图，绝不盲目重投。',
                '以 PID + start_ticks + boot_id 身份链与 SHA256SUMS 绑定每次求解。'
              ],
              guardrail: '红线：工程归档（COLLECTED）≠ 求解完成（solved）≠ 科学验收（accepted）。'
            }
          ]
        },
        {
          id: 'advisor',
          label: 'Sol + Astra 协同',
          summary: '主控研究代理与只读顾问异步协作，故障排查不阻塞算力补槽。',
          cards: [
            {
              title: '主控 Sol + 只读顾问 Astra',
              badge: '75.5s 实测联通',
              tone: 'violet',
              points: [
                'Sol 主控负责实验规划、失败谱系追踪（每谱系最多 2 次修复）与账本核验。',
                '遇难解收敛或 PMI 缺陷时异步派生管理核只读顾问 Astra（禁用写与 shell）。',
                '等待会诊期间主循环继续执行收集与补槽，零吞吐损失。'
              ],
              guardrail: '红线：顾问只输出诊断意见，无权改写账本或绕过门禁。'
            },
            {
              title: '≤50 行模块化 SKILL.md 契约',
              badge: '规范固化',
              tone: 'teal',
              points: [
                'sentaurus-vm-runner：断线先查后收，严禁重复全目录哈希或误触许可工具。',
                'tcad-experiment-plan：严格锁定实验分母、中性对照与防泄漏划分。',
                '多课程与报告同源复用原始账本与图表，禁止复制或重跑实验。'
              ],
              guardrail: '红线：所有历史失败记录永久保留，严禁覆盖或伪造。'
            }
          ]
        },
        {
          id: 'storage',
          label: '三层资源与冷备',
          summary: '严格区分物理与逻辑余量口径，通过两步无损压缩应对 GB 级瞬态归档。',
          cards: [
            {
              title: '三层磁盘与内存独立核算',
              badge: '各层余量绝不相加',
              tone: 'warn',
              points: [
                '磁盘：区分服务器剩余空间（≥20 GiB 缓冲）、VM 磁盘文件可增长空间、虚拟机剩余空间（启双层 fstrim）。',
                '内存：区分服务器可用内存、虚拟机分配内存（28 GiB）、虚拟机可用内存。',
                '逻辑容量绝不可视作服务器物理可用余量，严禁跨层累加。'
              ],
              guardrail: '红线：准入校验取三层最小安全余量，严防写穿物理盘。'
            },
            {
              title: '两步式无损冷备回收',
              badge: '实测节余 20.94 GiB',
              tone: 'good',
              points: [
                'ready 阶段打包精简分析包 essential.tar.gz 与逐字节无损包 raw.tar.gz 后清理热目录。',
                '4 份多核算例实测节省服务器 12.794 GiB、虚拟机 20.942 GiB，精简包仅 147.66 MiB。',
                '仅当进入 finalize 完成交叉核验后才可释放无损原始备份。'
              ],
              guardrail: '红线：未完成流式校验与关键字段核对前，禁止清理热副本。'
            }
          ]
        }
      ],
      topology: {
        title: '服务器—虚拟机—Agent 运行拓扑',
        subtitle: '点击节点查看该层职责与安全边界',
        nodes: [
          {
            id: 'public',
            x: 32, y: 44, w: 228, h: 82,
            kicker: 'PUBLIC EDGE',
            label: 'Caddy 只读门户',
            sub: '15s / 60s 脱敏投影',
            tone: 'primary',
            detail: '托管脱敏静态页面与 /live.json、/status.json；不设任何通往仿真虚拟机的反向代理。'
          },
          {
            id: 'controller',
            x: 296, y: 44, w: 228, h: 82,
            kicker: 'SERVER CONTROL',
            label: 'server-codex-v2',
            sub: 'systemd · Sol + Astra',
            tone: 'violet',
            detail: '运行于 Rocky Linux 9 服务器管理核，执行事件唤醒、r06_gate 门禁与三层保守准入。'
          },
          {
            id: 'ledger',
            x: 560, y: 44, w: 228, h: 82,
            kicker: 'PROVENANCE',
            label: 'SQLite & 两步冷备',
            sub: '防篡改 · SHA256SUMS',
            tone: 'teal',
            detail: '存储不可覆盖的进程身份链与输入指纹，并通过 essential + raw 两步压缩回收 TB 级热盘压力。'
          },
          {
            id: 'pool',
            x: 128, y: 202, w: 262, h: 78,
            kicker: 'LOOPBACK POOL',
            label: '17-vCPU 异步共享池',
            sub: '串行收集 · 5s 有界采样',
            tone: 'good',
            detail: '仅通过本地回环提交作业，保持唯一串行归档通道与共享池锁空闲仲裁。'
          },
          {
            id: 'vm',
            x: 430, y: 202, w: 262, h: 78,
            kicker: 'ISOLATED GUEST VM',
            label: 'CentOS 7.9 仿真虚拟机',
            sub: '13 TCAD 槽位 + Geant4',
            tone: 'warn',
            detail: '无公网暴露；CPU0–11（12×1核）与 CPU12–15（1×4核）并行求解，28 GiB 内存统一调度。'
          }
        ],
        scenarioTitle: '选择调度情景 · 实时观察服务器与虚拟机闭环流转',
        replayLabel: '重放流程',
        scenarios: [
          {
            id: 'admission',
            label: 'r0.6 准入与验收闭环',
            steps: [
              { nodes: ['controller', 'pool'], edge: 'ctrl-pool', tag: '步骤 1/4', text: 'Sol 主控核验三层磁盘/内存余量，通过本地回环向 17-vCPU 异步共享池放行任务。' },
              { nodes: ['pool', 'vm'], edge: 'pool-vm', tag: '步骤 2/4', text: 'CentOS 7.9 仿真虚拟机按 12×1 核与 1×4 核槽位调度 Sentaurus TCAD + 原子 PMI 求解。' },
              { nodes: ['vm', 'ledger'], edge: 'vm-ledger', tag: '步骤 3/4', text: '唯一串行归档通道回收并打包 essential + raw，写入 PID + start_ticks + SHA256SUMS 账本。' },
              { nodes: ['ledger', 'controller', 'public'], edge: 'ctrl-pub', tag: '步骤 4/4', text: 'r06_gate 验收合格后更新 /live.json 脱敏摘要，Caddy 只读门户 15s 内同步展示。' }
            ]
          },
          {
            id: 'isolation',
            label: '双层隔离与红线拦截',
            steps: [
              { nodes: ['public'], edge: '', tag: '拦截 1/4', text: '公网端 Caddy 只提供静态文档与脱敏 JSON；任何通向仿真虚拟机的代理路由在网关层被零暴露阻断。' },
              { nodes: ['controller'], edge: 'ctrl-pub', tag: '拦截 2/4', text: 'server-codex-v2 运行于 systemd 严格沙箱，Astra 只读顾问无写盘与 shell 权限。' },
              { nodes: ['pool', 'vm'], edge: 'ctrl-pool', tag: '拦截 3/4', text: '共享池切换 profile 前必须确认锁空闲与零未登记求解器；watchdog 只告警不强杀求解。' },
              { nodes: ['ledger'], edge: 'ctrl-ledger', tag: '拦截 4/4', text: 'SQLite 防篡改触发器与四级门禁阻断未验收结果直接晋升为 statistics_eligible。' }
            ]
          },
          {
            id: 'offload',
            label: '两步冷备与账本对账',
            steps: [
              { nodes: ['pool', 'vm'], edge: 'pool-vm', tag: '冷备 1/4', text: '5s 有界探针确认求解自然收尾，唯一串行收集器锁定热工作目录准备归档。' },
              { nodes: ['vm', 'ledger'], edge: 'vm-ledger', tag: '冷备 2/4', text: 'ready 阶段并行构建精简 essential.tar.gz（147.66 MiB）与逐字节无损 raw.tar.gz。' },
              { nodes: ['controller', 'ledger'], edge: 'ctrl-ledger', tag: '冷备 3/4', text: '通过流式完整性与关键物理字段交叉核对后释放热副本，实测节省虚拟机 20.94 GiB 空间。' },
              { nodes: ['ledger', 'public'], edge: 'ctrl-pub', tag: '冷备 4/4', text: 'intent_reconciliation 核销意图回执，脱敏遥测同步刷新至公开状态看板。' }
            ]
          }
        ]
      }
    },
    results: {
      eyebrow: 'SIMULATION ACHIEVEMENTS',
      title: '多代次 DRAM 单粒子效应仿真成果与物理发现',
      lead: '按研究代次切换查看关键实测指标，下方图表实时汇总 r0.6 进度、v3 代理误差跃升与 D1 偏置抵消机理。',
      stages: [
        {
          id: 'v1',
          tab: 'v1 · 全链路贯通',
          status: '已审计完成',
          statusTone: 'good',
          title: 'v1：平面 1T1C 端到端链路验证',
          summary: '在 L=0.18–0.45 μm 平面 1T1C 上完成 16/16 粒子工况与网格细化校验，打通自然语言模板到代理预测全链。',
          metrics: [
            { label: '物理工况完备度', value: '16 / 16', note: '含 4 无粒子对照 + 2 网格细化' },
            { label: '源积分注入偏差', value: '0.20% – 1.24%', note: '低于 <5% 验收容差' },
            { label: 'KCL 残差 & 细化差', value: '0.35 mV', note: '细化后 ΔV 差 0.0715%' },
            { label: 'OLS 域外外推 MAE', value: '3.414 mV', note: 'L=0.45 μm 跨尺寸外推' }
          ],
          highlights: [
            '校正存储节点电压降 ΔV 覆盖 0.0186 – 0.4908 V。',
            '发现写入初态漂移局限，直接推动 v2 钳位初态与差分读出重构。'
          ]
        },
        {
          id: 'v2d1',
          tab: 'v2 & D1 · 偏置机理',
          status: '9/9 专项验证通过',
          statusTone: 'good',
          title: 'v2 差分读出与 D1 栅耦合偏置消除',
          summary: '统一理想钳位初态后发现 +12.1 mV 读出正偏；D1 9/9 确定性诊断揭示字线耦合根因并验证中性参考抵消方案。',
          metrics: [
            { label: 'WL 开启净耦合注入', value: '+1.32 ~ +1.46 fC', note: '栅极耦合 +1.464 fC 主导' },
            { label: '单端固定参考偏移', value: '+12.01 ~ +13.24 mV', note: 'WL 关闭对照仅 -0.005 mV' },
            { label: '中性参考抵消残余', value: '-0.259 mV', note: '共模偏置抑制约 98%' },
            { label: '重启 / 半步长差异', value: '2e-12 / 0.034 mV', note: '5 mV 判据分类稳定' }
          ],
          highlights: [
            '解释了 5 mV 阈值下 α 粒子写入 b1 出现 3/4 临界读出的物理来源。',
            '确立同条件匹配中性参考单元规范，成为 v3 及后续代次标准配置。'
          ]
        },
        {
          id: 'v3',
          tab: 'v3 · 128 算例交付',
          status: '128/128 实测交付',
          statusTone: 'good',
          title: 'v3 (r50-main)：128 配对响应与代理精度跃升',
          summary: '采用 50 Ω 预充配对中性参考，完成 64 训练 / 32 留出 / 32 外推共 128 组主响应及 22 扩展算例归档交付。',
          metrics: [
            { label: '主响应与扩展规模', value: '128 + 22', note: '211 个核验交付文件' },
            { label: '5 mV 判据分类', value: '96 / 20 / 8 / 4', note: '正确 / 误读 / 临界 / 不确定' },
            { label: 'Tox 4–6 nm 敏感度', value: '≤ 0.113 mV', note: '远低于 0.5 mV 容差上限' },
            { label: '岭回归留出/外推 MAE', value: '0.53 / 0.40 mV', note: '较均值基线降幅 >97%' }
          ],
          highlights: [
            'Holdout (L=0.25 μm) ΔM MAE 为 0.527 / 0.550 mV（b0 / b1）。',
            'Extrapolation (L=0.45 μm) ΔM MAE 低至 0.405 / 0.388 mV。'
          ]
        },
        {
          id: 'v4',
          tab: 'v4 · 核反应见证',
          status: '见证与审计通过',
          statusTone: 'teal',
          title: 'v4：100 MeV 质子核见证与 205 帧源审计',
          summary: '引入 90 nm BCAT 结构与厚硅核反应输运，完成次级血缘追踪、205 帧细网格源守恒审计并定位局部 PMI 回调缺陷。',
          metrics: [
            { label: '质子核非弹性见证', value: '9 例 protonInelastic', note: '来自 212 事件（46,631 步）' },
            { label: '核次级硅沉积峰值', value: '36.764 MeV', note: '追踪 p/n/α/Li7/γ/O15 级联' },
            { label: '205 帧源积分误差', value: '0.416%', note: '质心偏移仅 0.0022 μm' },
            { label: '两比特无粒子裕量', value: '53.93 / 47.77 mV', note: '网格细化扰动差 ≤0.469 mV' }
          ],
          highlights: [
            '实证标准局部 PMI 在 957 个向后欧拉步间不刷新，促成 r0.6 全局原子扩展。',
            '保留历史 TDR 覆盖失败记录，正式三维矩阵按计划转入 r0.6 体系。'
          ]
        },
        {
          id: 'r06',
          tab: 'r0.4 & r0.6 · 推进中',
          status: '396 正式槽位实时推进',
          statusTone: 'warn',
          title: 'r0.4 六万质子输运与 r0.6 DDR5/LPDDR5 双主线',
          summary: 'r0.4 已完成 60,000 初级质子输运快照；r0.6 冻结 13 器件（含 14 nm Saddle-Fin）× 10 辐照共 396 正式槽位，正持续推进验收。',
          metrics: [
            { label: 'r0.4 质子输运规模', value: '60,000 初级', note: '含 54,037 零沉积无偏分母' },
            { label: 'r0.6 正式槽位配额', value: '396 槽位', note: '含 214 统计上限与 58 封存留出' },
            { label: 'D0 / D1 零源裕量', value: '+26.21 / +26.15 mV', note: '局部阻尼将拒步从 114/421 降至 8/57' },
            { label: '3D 24k 顶点 DC 均值', value: '110.59 s', note: '2×4 核并行（对比 4×2 核 153.58 s）' }
          ],
          highlights: [
            'O2 全局原子有界日志 PMI 成功编译收集，解决 24k+ 顶点并发日志竞争。',
            '实时完成与验收计数见下方 /live.json 联动图；统计资格快照（not_connected）及 R→A→F 正式训练仍待全量闭合。'
          ]
        }
      ]
    },
    techBridge: {
      eyebrow: 'TECHNICAL STACK & DOCS',
      title: '探索全栈技术细节与工程实现',
      lead: '技术文档站完整收录粒子输运、器件物理与 PMI 扩展、神经网络与自主调度系统的源码级设计规范。',
      cta: '进入技术文档站',
      items: [
        { anchor: 'geant4', badge: '物理输运', title: 'Geant4 核非弹性输运', desc: 'QGSP_BIC + EM Opt4、次级血缘与零沉积无偏分母。' },
        { anchor: 'tcad-pmi', badge: '器件物理', title: 'Sentaurus 与原子 PMI', desc: '14 nm Saddle-Fin、原子有界日志 .so 与局部阻尼。' },
        { anchor: 'predictor', badge: '物理 AI', title: 'R → A → F 预测网络', desc: '机理+残差、Horvitz-Thompson 与连通分量划分。' },
        { anchor: 'agent-autonomy', badge: '工程自治', title: 'server-codex-v2 调度', desc: '17-vCPU 共享池、Sol+Astra、防伪链与两步冷备。' }
      ]
    },
    status: {
      eyebrow: 'LIVE SERVICE & TELEMETRY',
      title: '研究服务与遥测实时可见',
      lead: '直接消费与 status.xjtu.shop 同源的脱敏只读 JSON（优先 /live.json，180s 新鲜度门限），仅展示白名单服务与安全摘要。',
      openStatus: '打开完整状态看板',
      openDocs: '查看遥测文档',
      previewTitle: 'status.xjtu.shop',
      refresh: '刷新状态',
      loading: '同步遥测中…',
      updated: '最近检查',
      expandNote: '展开服务说明',
      collapseNote: '收起服务说明',
      fullBoard: '进入完整看板',
      services: [
        { id: 'research-site', name: '研究展示站 (tcad / status)', desc: '公开门户、技术文档与状态看板静态服务可用性。' },
        { id: 'tcad-controller', name: 'TCAD 自主控制器 (server-codex-v2)', desc: '服务器事件驱动调度器与状态守护进程可用性。' },
        { id: 'simulation-runtime', name: '仿真运行环境 (CentOS 7.9 VM)', desc: '隔离仿真虚拟机、17-vCPU 共享池与只读采样探针可用性。' }
      ],
      stateLabels: {
        operational: '运行正常',
        degraded: '部分异常',
        offline: '服务离线',
        maintenance: '维护中',
        loading: '读取中',
        unknown: '等待更新',
        stale: '数据待刷新'
      }
    }
  },
  en: {
    hero: {
      chip: 'Open Technology Docs',
      eyebrow: 'XJTU · RADIATION EFFECTS & AI AUTONOMY',
      title: 'Single-Event Effects in DRAM',
      formalTitle: 'AI-Assisted Assessment of Single-Event Effects in DRAM Memories',
      lead: 'Unifying Geant4 nuclear transport, Sentaurus TCAD mixed-mode simulation, the R→A→F physics-constrained predictor, and server-codex-v2 autonomy for DDR5 / LPDDR5 reliability assessment.',
      ctaPrimary: 'Explore Results',
      ctaDocs: 'Tech Docs',
      ctaStatus: 'Live Status',
      blueprintTitle: 'Interactive 1T1C DRAM SEE Physics Demo',
      blueprintHint: 'Select any stage below to inspect its contract',
      simDemoBadge: 'Mechanism Demo · Schematic',
      simFireBtn: 'Fire Particle',
      simClickHint: 'Click inside the cell cross-section to trigger a strike',
      simNodeDropLabel: 'SN Response',
      simReadoutLabel: 'Signature',
      simPresets: [
        {
          id: 'v4',
          label: 'v4 · 100 MeV Nuclear',
          statLabel: 'Secondary Peak',
          caption: 'A 100 MeV proton triggers a protonInelastic nuclear vertex inside Si, spawning high-LET secondary fragments.'
        },
        {
          id: 'v3',
          label: 'v3 · LET Charge Funnel',
          statLabel: 'Track Condition',
          caption: 'Dense ionization carriers funnel rapidly into the Storage Node capacitor (SN), driving transient bitline swing.'
        },
        {
          id: 'd1',
          label: 'D1 · Offset Cancellation',
          statLabel: 'Common-Mode Shift',
          caption: 'Fixed references incur +12.01~+13.24 mV WL coupling offset; matched neutral cells cancel ~98% (-0.259 mV residual).'
        }
      ],
      nodes: [
        {
          id: 'geant4',
          step: '01',
          name: 'Geant4 10.7.3',
          role: 'Nuclear & Zero-Deposition Transport',
          badge: '60,000+ Primaries',
          detail: 'Uses QGSP_BIC + EM Opt4 with mother-step ancestry while retaining zero-deposition events for unbiased cross-section denominators.'
        },
        {
          id: 'tcad',
          step: '02',
          name: 'Sentaurus TCAD',
          role: 'Mixed-Mode & Atomic PMI',
          badge: '14 nm Saddle-Fin',
          detail: 'Covers planar 1T1C, BCAT, and Saddle-Fin cells; custom global atomic bounded-log C++ PMI resolves 24k+ vertex contention.'
        },
        {
          id: 'predictor',
          step: '03',
          name: 'R → A → F Network',
          role: 'Physics-Guided Surrogate',
          badge: '172 Offline Tests Pass',
          detail: 'Mechanism + residual MLP (R) → Horvitz-Thompson aggregator (A) → pre-sim head (F); formal training awaits full r0.6 labels.'
        },
        {
          id: 'agent',
          step: '04',
          name: 'server-codex-v2',
          role: 'Isolated Server–VM Autonomy',
          badge: '17-vCPU Shared Pool',
          detail: 'Rocky Linux 9 server orchestrates an isolated CentOS 7.9 VM using Sol/Astra collaboration and a 4-tier provenance ledger.'
        }
      ]
    },
    signals: {
      stageLabel: 'Current Stage',
      stageFallback: 'Syncing live telemetry…',
      matrixLabel: 'r0.6 Formal Matrix (P0 separate)',
      matrixFallback: '396 formal slots (58 sealed)',
      milestoneLabel: 'Audited Milestones',
      milestoneText: 'v3 128 cases · v4 9 witnesses · r0.4 60k protons',
      healthLabel: 'Platform Health',
      planned: 'Planned',
      solved: 'Solved',
      accepted: 'Accepted',
      running: 'Running'
    },
    workbench: {
      stepLabel: 'Section View',
      prevLabel: 'Previous',
      nextLabel: 'Next Section',
      keyboardHint: 'Alt + ← / → to switch',
      exploreAllCue: '4 Interactive Views · Click any card to jump',
      loopBackLabel: 'Back to View 01',
      jumpDocsLabel: 'Explore Full Tech Docs',
      views: [
        {
          id: 'results',
          num: '01',
          short: 'Results',
          caption: 'v1–r0.6 metrics & live charts',
          teaser: 'Multi-generation DRAM SEE findings, v3 ridge MAE drop, and live r0.6 cohort tracking.'
        },
        {
          id: 'architecture',
          num: '02',
          short: 'Agent Arch',
          caption: 'Isolation & live flow demo',
          teaser: 'Interactive server–VM orchestration trace, Sol/Astra workflow, and admission boundaries.'
        },
        {
          id: 'evidence',
          num: '03',
          short: 'Evidence Ledger',
          caption: '4-tier scope & boundaries',
          teaser: 'COLLECTED ≠ solved ≠ accepted ≠ statistics_eligible provenance contracts.'
        },
        {
          id: 'status',
          num: '04',
          short: 'Live & Docs',
          caption: 'Telemetry & 6-chapter docs',
          teaser: 'Live status.xjtu.shop probe snapshot and direct bridge into deep technical articles.'
        }
      ]
    },
    arch: {
      eyebrow: 'SERVER AGENT ARCHITECTURE',
      title: 'Two-Tier Isolation & server-codex-v2 Autonomy',
      lead: 'Strict boundary between public read-only delivery, autonomous server control, and offline VM execution.',
      guardrailSwitch: 'Show Engineering Guardrails',
      tabs: [
        {
          id: 'isolation',
          label: 'Server–VM Isolation',
          summary: 'Public read-only edge, sandboxed server control, and air-gapped VM execution.',
          cards: [
            {
              title: 'Rocky Linux 9 Server (20-Core Control Plane)',
              badge: 'Control · Public Read-Only',
              tone: 'primary',
              points: [
                'Serves static portal and dual-rate redacted telemetry (15s /live.json + 60s /status.json).',
                'Controller runs in a systemd strict sandbox with CPU17–19 reserved for management.',
                'Zero reverse-proxy routes into the VM; internal paths and run IDs stay hidden.'
              ],
              guardrail: 'Guardrail: Zero VM proxy; anti-tamper SQLite projection triggers.'
            },
            {
              title: 'CentOS 7.9 Simulation VM (17 vCPU + 28 GiB)',
              badge: 'Execution · Zero Public Access',
              tone: 'teal',
              points: [
                'Loopback-only controlled submission with zero public network exposure.',
                '13 TCAD slots: CPU0–11 (12×1-core) + CPU12–15 (1×4-core) + CPU16 background.',
                'Geant4 rotates up to 4 single-core jobs within idle shared-pool windows.'
              ],
              guardrail: 'Guardrail: Profile switches require idle locks and zero unregistered solvers.'
            }
          ]
        },
        {
          id: 'scheduler',
          label: 'Shared-Pool Scheduler',
          summary: 'Event-driven scheduling with serial collection and fail-closed admission.',
          cards: [
            {
              title: 'Asynchronous Shared-Pool Pipeline',
              badge: 'server-codex-v2',
              tone: 'primary',
              points: [
                'Wakes only on plan, queue, or observation shifts (300–3600s backoff).',
                'Single serial archive collector (concurrency=1) + 5s bounded read-only probe.',
                'Conservative admission checks 3-layer free space and uncovered RSS.'
              ],
              guardrail: 'Guardrail: Watchdog alerts only and never kills active solvers.'
            },
            {
              title: 'Fail-Closed Gate & Reconciliation',
              badge: 'Single Ledger',
              tone: 'good',
              points: [
                'r06_gate audits every submission fail-closed before scientific promotion.',
                'Receipt-verified intent reconciliation prevents blind resubmission.',
                'PID + start_ticks + boot_id chain and SHA256SUMS pin every run.'
              ],
              guardrail: 'Guardrail: COLLECTED ≠ solved ≠ accepted ≠ statistics_eligible.'
            }
          ]
        },
        {
          id: 'advisor',
          label: 'Sol + Astra & Skills',
          summary: 'Asynchronous read-only advisor troubleshooting without stalling slot refilling.',
          cards: [
            {
              title: 'Sol Orchestrator + Astra Advisor',
              badge: '75.5s Verified Link',
              tone: 'violet',
              points: [
                'Sol manages planning, failure lineage (max 2 repairs), and verification.',
                'Spawns read-only Astra (no shell/write) on management cores for hard faults.',
                'Main loop continues archive collection and refilling asynchronously.'
              ],
              guardrail: 'Guardrail: Advisor cannot mutate ledgers or bypass gates.'
            },
            {
              title: 'Modular ≤50-Line SKILL.md Contracts',
              badge: 'Zero Duplication',
              tone: 'teal',
              points: [
                'Enforces check-before-collect recovery and bans full-tree re-hashing.',
                'Locks cohort denominators, reference pairings, and leak-free splits.',
                'All downstream reports reuse canonical ledgers without re-running.'
              ],
              guardrail: 'Guardrail: Failed historical attempts stay immutable in the ledger.'
            }
          ]
        },
        {
          id: 'storage',
          label: '3-Layer Storage & Offload',
          summary: 'Non-additive resource accounting and two-stage lossless archiving.',
          cards: [
            {
              title: 'Strict 3-Layer Resource Accounting',
              badge: 'Never Sum Across Layers',
              tone: 'warn',
              points: [
                'Disk separates server free space (≥20 GiB buffer), VM image growth headroom, and VM free space.',
                'Memory separates server RAM, VM allocated RAM (28 GiB), and VM available RAM.',
                'Logical VM capacity is never treated as physical server free space.'
              ],
              guardrail: 'Guardrail: Admission uses the tightest layer margin.'
            },
            {
              title: 'Two-Stage Essential + Raw Cold Offload',
              badge: '20.94 GiB VM Saved',
              tone: 'good',
              points: [
                'Creates compact essential.tar.gz + lossless raw.tar.gz before pruning hot dirs.',
                'Saved 12.794 GiB on server and 20.942 GiB in VM across 4 multi-core runs.',
                'Raw backup removed only after finalize cross-checks clear.'
              ],
              guardrail: 'Guardrail: Streaming verification required before pruning.'
            }
          ]
        }
      ],
      topology: {
        title: 'Server–VM–Agent Operational Topology',
        subtitle: 'Select any node to inspect its boundary',
        nodes: [
          {
            id: 'public',
            x: 32, y: 44, w: 228, h: 82,
            kicker: 'PUBLIC EDGE',
            label: 'Caddy Static Edge',
            sub: '15s / 60s Redacted Feed',
            tone: 'primary',
            detail: 'Serves redacted static pages plus /live.json and /status.json with zero proxy routes into the VM.'
          },
          {
            id: 'controller',
            x: 296, y: 44, w: 228, h: 82,
            kicker: 'SERVER CONTROL',
            label: 'server-codex-v2',
            sub: 'systemd · Sol + Astra',
            tone: 'violet',
            detail: 'Runs on Rocky Linux 9 management cores, enforcing event wakeups, r06_gate, and 3-layer admission.'
          },
          {
            id: 'ledger',
            x: 560, y: 44, w: 228, h: 82,
            kicker: 'PROVENANCE',
            label: 'SQLite & Cold Archive',
            sub: 'Triggers · SHA256SUMS',
            tone: 'teal',
            detail: 'Stores immutable process provenance and reclaims multi-GB transient space via two-stage archiving.'
          },
          {
            id: 'pool',
            x: 128, y: 202, w: 262, h: 78,
            kicker: 'LOOPBACK POOL',
            label: '17-vCPU Shared Pool',
            sub: 'Serial collector · 5s probe',
            tone: 'good',
            detail: 'Loopback-only submission with single-concurrency archive collection and lock-safe arbitration.'
          },
          {
            id: 'vm',
            x: 430, y: 202, w: 262, h: 78,
            kicker: 'ISOLATED GUEST VM',
            label: 'CentOS 7.9 Simulation VM',
            sub: '13 TCAD slots + Geant4',
            tone: 'warn',
            detail: 'Air-gapped from public internet; CPU0–11 (12×1-core) + CPU12–15 (1×4-core) with 28 GiB RAM.'
          }
        ],
        scenarioTitle: 'Choose an execution scenario to watch server–VM orchestration live',
        replayLabel: 'Replay',
        scenarios: [
          {
            id: 'admission',
            label: 'r0.6 Admission & Gate Loop',
            steps: [
              { nodes: ['controller', 'pool'], edge: 'ctrl-pool', tag: 'Step 1/4', text: 'Sol verifies 3-layer disk/RAM margins and admits jobs via loopback into the 17-vCPU shared pool.' },
              { nodes: ['pool', 'vm'], edge: 'pool-vm', tag: 'Step 2/4', text: 'CentOS 7.9 VM runs Sentaurus TCAD + atomic PMI across 12×1-core and 1×4-core execution slots.' },
              { nodes: ['vm', 'ledger'], edge: 'vm-ledger', tag: 'Step 3/4', text: 'Single serial collector archives outputs and writes PID + start_ticks + SHA256SUMS provenance.' },
              { nodes: ['ledger', 'controller', 'public'], edge: 'ctrl-pub', tag: 'Step 4/4', text: 'r06_gate clears scientific acceptance and publishes redacted /live.json metrics to Caddy edge.' }
            ]
          },
          {
            id: 'isolation',
            label: 'Two-Tier Isolation Guard',
            steps: [
              { nodes: ['public'], edge: '', tag: 'Guard 1/4', text: 'Public Caddy serves static docs and JSON only; any reverse-proxy route into the VM is zero-exposed.' },
              { nodes: ['controller'], edge: 'ctrl-pub', tag: 'Guard 2/4', text: 'server-codex-v2 executes inside strict systemd sandboxing while Astra advisor stays read-only.' },
              { nodes: ['pool', 'vm'], edge: 'ctrl-pool', tag: 'Guard 3/4', text: 'Pool profile switching requires idle locks and zero rogue solvers; watchdog alerts without force-kills.' },
              { nodes: ['ledger'], edge: 'ctrl-ledger', tag: 'Guard 4/4', text: 'SQLite anti-tamper triggers and fail-closed gates prevent unaccepted artifacts from entering stats.' }
            ]
          },
          {
            id: 'offload',
            label: 'Two-Stage Cold Offload',
            steps: [
              { nodes: ['pool', 'vm'], edge: 'pool-vm', tag: 'Offload 1/4', text: 'Bounded 5s probe confirms solver completion; serial collector locks hot job folder for packaging.' },
              { nodes: ['vm', 'ledger'], edge: 'vm-ledger', tag: 'Offload 2/4', text: 'Ready stage builds compact essential.tar.gz (147.66 MiB) alongside lossless raw.tar.gz.' },
              { nodes: ['controller', 'ledger'], edge: 'ctrl-ledger', tag: 'Offload 3/4', text: 'After streaming hash checks clear, hot tree is reclaimed—saving 20.94 GiB VM space across 4 runs.' },
              { nodes: ['ledger', 'public'], edge: 'ctrl-pub', tag: 'Offload 4/4', text: 'Intent reconciliation clears receipts and syncs updated health telemetry to public feeds.' }
            ]
          }
        ]
      }
    },
    results: {
      eyebrow: 'SIMULATION ACHIEVEMENTS',
      title: 'Multi-Generation DRAM SEE Results & Physics Findings',
      lead: 'Switch across study generations below; interactive figures aggregate live r0.6 progress, v3 accuracy, and D1 offset cancellation.',
      stages: [
        {
          id: 'v1',
          tab: 'v1 · End-to-End',
          status: 'Audited Complete',
          statusTone: 'good',
          title: 'v1: Planar 1T1C Pipeline Validation',
          summary: 'Completed 16/16 ion conditions and mesh refinements on L=0.18–0.45 μm planar 1T1C cells.',
          metrics: [
            { label: 'Case Completion', value: '16 / 16', note: '+ 4 controls + 2 mesh checks' },
            { label: 'Source Integral Error', value: '0.20% – 1.24%', note: 'Within <5% tolerance' },
            { label: 'KCL & Mesh Diff', value: '0.35 mV', note: '0.0715% ΔV refinement delta' },
            { label: 'OLS Extrap MAE', value: '3.414 mV', note: 'Out-of-domain L=0.45 μm' }
          ],
          highlights: [
            'Calibrated ΔV spanned 0.0186 – 0.4908 V across particle angles and energies.',
            'Exposed write initial-state drift, motivating clamped initial states in v2.'
          ]
        },
        {
          id: 'v2d1',
          tab: 'v2/D1 · Offset',
          status: '9/9 Verified',
          statusTone: 'good',
          title: 'v2 Differential Readout & D1 Coupling Offset Root Cause',
          summary: 'Clamped initial states uncovered a +12.1 mV readout offset; D1 9/9 diagnostics proved WL coupling and neutral cancellation.',
          metrics: [
            { label: 'WL Net Charge Injection', value: '+1.32 ~ +1.46 fC', note: 'Gate coupling +1.464 fC' },
            { label: 'Fixed-Ref Offset', value: '+12.01 ~ +13.24 mV', note: 'WL-off baseline is -0.005 mV' },
            { label: 'Matched Neutral Residual', value: '-0.259 mV', note: '~98% common-mode cancellation' },
            { label: 'Restart / Half-Step', value: '2e-12 / 0.034 mV', note: 'Stable at 5 mV threshold' }
          ],
          highlights: [
            'Explained 3/4 marginal b1 α readouts at 5 mV threshold.',
            'Established matched neutral reference cells as the standard from v3 onward.'
          ]
        },
        {
          id: 'v3',
          tab: 'v3 · 128-Case',
          status: '128/128 Archived',
          statusTone: 'good',
          title: 'v3 (r50-main): 128 Paired Responses & >97% MAE Reduction',
          summary: 'Adopted 50 Ω precharge + neutral reference, delivering 128 paired responses plus 22 extension runs.',
          metrics: [
            { label: 'Delivered Runs', value: '128 + 22', note: '211 verified delivery files' },
            { label: '5 mV Classification', value: '96 / 20 / 8 / 4', note: 'Correct / Misread / Marginal / Uncertain' },
            { label: 'Tox 4–6 nm Sensitivity', value: '≤ 0.113 mV', note: 'Well below 0.5 mV tolerance' },
            { label: 'Ridge Holdout/Extrap', value: '0.53 / 0.40 mV', note: '>97% lower than ~19.2 mV baseline' }
          ],
          highlights: [
            'Holdout (L=0.25 μm) ΔM MAE: 0.527 / 0.550 mV (b0 / b1).',
            'Extrapolation (L=0.45 μm) ΔM MAE: 0.405 / 0.388 mV.'
          ]
        },
        {
          id: 'v4',
          tab: 'v4 · Nuclear',
          status: 'Witness & Audit Passed',
          statusTone: 'teal',
          title: 'v4: 100 MeV Nuclear Witnesses & 205-Frame Source Audit',
          summary: 'Moved to 90 nm BCAT + thick-silicon nuclear reactions, closing ancestry tracking and diagnosing local PMI refresh gaps.',
          metrics: [
            { label: 'Nuclear Witnesses', value: '9 protonInelastic', note: 'From 212 events (46,631 steps)' },
            { label: 'Secondaries Si Dep', value: '36.764 MeV', note: 'Tracks p/n/α/Li7/γ/O15 cascades' },
            { label: '205-Frame Source Error', value: '0.416%', note: 'Centroid deviation 0.0022 μm' },
            { label: 'Two-Bit WHR Margins', value: '53.93 / 47.77 mV', note: 'Mesh refinement diff ≤0.469 mV' }
          ],
          highlights: [
            'Proved local PMI Compute_r skipped 957 BE step refreshes, motivating r0.6 atomic C++ PMI.',
            'Preserved historical TDR overwrite records; 3D production runs under r0.6.'
          ]
        },
        {
          id: 'r06',
          tab: 'r0.4/r0.6 · Active',
          status: '396-Slot Live Matrix',
          statusTone: 'warn',
          title: 'r0.4 60k-Proton Transport & r0.6 DDR5/LPDDR5 Dual Tracks',
          summary: 'r0.4 delivered 60,000 primary protons; r0.6 freezes 13 profiles (incl. 14 nm Saddle-Fin) × 10 radiations = 396 formal slots.',
          metrics: [
            { label: 'r0.4 Transport Scale', value: '60,000 Primaries', note: 'Retains 54,037 zero-deposition hits' },
            { label: 'r0.6 Formal Slots', value: '396 Slots', note: '214 stats cap · 58 sealed HR/HP' },
            { label: 'D0 / D1 Zero-Source', value: '+26.21 / +26.15 mV', note: 'Damping cut rejections 114/421 → 8/57' },
            { label: '3D 24k-Node DC Mean', value: '110.59 s', note: '2×4-core vs 153.58 s at 4×2-core' }
          ],
          highlights: [
            'O2 global atomic bounded-log C++ PMI (.so) compiled and collected cleanly in VM runtime.',
            'Live cohort progress updates below from /live.json; stats snapshot & R→A→F training remain pending.'
          ]
        }
      ]
    },
    techBridge: {
      eyebrow: 'TECHNICAL STACK & DOCS',
      title: 'Explore Full-Stack Engineering Specs',
      lead: 'Browse the /docs/ portal for implementation details across particle physics, TCAD PMI, neural models, and server autonomy.',
      cta: 'Open Tech Docs',
      items: [
        { anchor: 'geant4', badge: 'Transport', title: 'Geant4 Nuclear Transport', desc: 'QGSP_BIC + EM Opt4, ancestry ledger & zero-deposition denominator.' },
        { anchor: 'tcad-pmi', badge: 'Device Physics', title: 'Sentaurus & Atomic PMI', desc: '14 nm Saddle-Fin, std::atomic bounded-log .so & local damping.' },
        { anchor: 'predictor', badge: 'Physics AI', title: 'R → A → F Predictor', desc: 'RC skeleton + residual MLP, HT estimator & graph splits.' },
        { anchor: 'agent-autonomy', badge: 'Autonomy', title: 'server-codex-v2 Stack', desc: '17-vCPU pool, Sol+Astra, PID/SHA256 provenance & cold offload.' }
      ]
    },
    status: {
      eyebrow: 'LIVE SERVICE & TELEMETRY',
      title: 'Transparent Public Services & Telemetry',
      lead: 'Reads the exact redacted /live.json (fallback /status.json) feed shared with status.xjtu.shop with a 180s freshness threshold.',
      openStatus: 'Open Full Status Board',
      openDocs: 'Telemetry Docs',
      previewTitle: 'status.xjtu.shop',
      refresh: 'Refresh status',
      loading: 'Syncing telemetry…',
      updated: 'Last checked',
      expandNote: 'Expand details',
      collapseNote: 'Collapse details',
      fullBoard: 'Full status board',
      services: [
        { id: 'research-site', name: 'Research Site (tcad / status)', desc: 'Public homepage, tech docs, and status dashboard availability.' },
        { id: 'tcad-controller', name: 'TCAD Controller (server-codex-v2)', desc: 'Event-driven server scheduler and watchdog availability.' },
        { id: 'simulation-runtime', name: 'Simulation Runtime (CentOS 7.9 VM)', desc: 'Isolated simulation VM, 17-vCPU pool, and 5s probe availability.' }
      ],
      stateLabels: {
        operational: 'Operational',
        degraded: 'Degraded',
        offline: 'Offline',
        maintenance: 'Maintenance',
        loading: 'Loading',
        unknown: 'Awaiting update',
        stale: 'Awaiting refresh'
      }
    }
  }
};
