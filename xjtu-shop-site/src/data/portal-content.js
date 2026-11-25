import { homeContent } from './home-content.js';

export const portalContent = {
  en: {
    meta: {
      title: 'XJTU DRAM SEE Research Portal · www.xjtu.shop',
      description:
        'Public portal for AI-assisted DRAM single-event-effects research: explore simulation results, technical documentation, and live compute telemetry across xjtu.shop.'
    },
    hero: {
      eyebrow: 'XJTU · DRAM SEE PORTAL',
      headline: 'DRAM Single-Event Effects Research Portal',
      formalTitle: homeContent.en.hero.formalTitle,
      lead:
        'Connecting four research layers—Geant4 nuclear transport, Sentaurus TCAD mixed-mode transient response with custom atomic PMI, the R→A→F physics-constrained predictor, and server-codex-v2 autonomous orchestration—across two dedicated public portals.'
    },
    portalsAriaLabel: 'Primary sub-site portals',
    portals: {
      research: {
        domain: 'tcad.xjtu.shop',
        tag: 'Research & Docs',
        icon: 'simulation',
        title: 'Research Portal & Technical Documentation',
        description:
          'Explore multi-generation v1–r0.6 simulation results, an interactive 1T1C DRAM SEE physics demonstrator, the 4-tier provenance ledger, and 6-chapter deep technical documentation.',
        ctaLabel: 'Open tcad.xjtu.shop',
        ctaHref: 'https://tcad.xjtu.shop/',
        quickLinksTitle: 'Quick Entry',
        quickLinks: [
          { label: 'Results', href: 'https://tcad.xjtu.shop/#results', icon: 'radiation' },
          { label: 'Agent Architecture', href: 'https://tcad.xjtu.shop/#architecture', icon: 'agent' },
          { label: 'Tech Docs', href: 'https://tcad.xjtu.shop/docs/', icon: 'docs' }
        ]
      },
      status: {
        domain: 'status.xjtu.shop',
        tag: 'Live Telemetry',
        icon: 'telemetry',
        title: 'Live Simulation Status & Compute Board',
        description:
          'Inspect read-only compute telemetry, the isolated VM scheduling matrix, active simulation tasks, and month-one r0.6 formal matrix progress.',
        ctaLabel: 'Open status.xjtu.shop',
        ctaHref: 'https://status.xjtu.shop/',
        quickLinksTitle: 'Quick Entry',
        quickLinks: [
          { label: 'VM Matrix', href: 'https://status.xjtu.shop/#schedule', icon: 'server' },
          { label: 'Active Tasks', href: 'https://status.xjtu.shop/#tasks', icon: 'simulation' },
          { label: 'Research Plan', href: 'https://status.xjtu.shop/#research', icon: 'ledger' }
        ]
      }
    },
    statusBadge: {
      loading: 'Checking telemetry…',
      stale: 'Awaiting update',
      unavailable: 'Telemetry unavailable',
      operational: 'Online',
      degraded: 'Degraded',
      maintenance: 'Maintenance',
      offline: 'Offline',
      activeTasks: 'active'
    },
    highlights: {
      eyebrow: 'VERIFIED RESEARCH HIGHLIGHTS',
      title: 'Key Audited Benchmarks',
      items: [
        {
          target: 60000,
          suffix: '+',
          label: 'Primary Geant4 Protons',
          note: 'r0.4 unbiased nuclear transport with zero-deposition retention'
        },
        {
          target: 396,
          suffix: '',
          label: 'r0.6 Formal Matrix Slots',
          note: 'Includes 58 sealed holdout cases; P0 baseline tracked separately'
        },
        {
          target: 128,
          suffix: '',
          label: 'v3 TCAD Cases',
          note: 'Completed mixed-mode 1T1C & BCAT charge-funnel benchmarks'
        },
        {
          target: 172,
          suffix: '',
          label: 'Offline Predictor Tests Passing',
          note: 'R→A→F physics-guided surrogate verified before r0.6 training'
        }
      ]
    },
    scope: {
      eyebrow: 'MILESTONES & PUBLIC BOUNDARY',
      milestoneLabel: homeContent.en.signals.milestoneLabel,
      milestoneText: homeContent.en.signals.milestoneText,
      pipelineLabel: '4-Layer Pipeline',
      pipelineText: 'Geant4 10.7.3 → Sentaurus TCAD + Atomic PMI → R→A→F Surrogate → server-codex-v2',
      boundaryNote:
        'Public portals are strictly read-only: internal run IDs, private filesystem paths, and sealed holdout details are never exposed.'
    }
  },
  zh: {
    meta: {
      title: 'DRAM 单粒子效应研究总门户 · www.xjtu.shop',
      description:
        'AI 辅助下的 DRAM 存储器单粒子效应评估研究总门户：集中导航至仿真成果与技术文档（tcad.xjtu.shop）及实时算力遥测看板（status.xjtu.shop）。'
    },
    hero: {
      eyebrow: 'XJTU · DRAM SEE PORTAL',
      headline: 'DRAM 单粒子效应研究总门户',
      formalTitle: homeContent.zh.hero.formalTitle,
      lead:
        '统筹串联四层研究链路——Geant4 核非弹性输运、Sentaurus TCAD 混合模式瞬态求解与自研原子 PMI、R→A→F 物理约束预测网络以及 server-codex-v2 自主调度——分设研究文档与实时遥测两大公开子站。'
    },
    portalsAriaLabel: '核心子站入口',
    portals: {
      research: {
        domain: 'tcad.xjtu.shop',
        tag: '研究成果与技术文档',
        icon: 'simulation',
        title: '研究主页与全栈技术文档',
        description:
          '浏览 v1–r0.6 多代次仿真成果、1T1C DRAM 单粒子物理机理交互示意、四级防伪证据账本以及六章深度技术文档。',
        ctaLabel: '进入 tcad.xjtu.shop',
        ctaHref: 'https://tcad.xjtu.shop/',
        quickLinksTitle: '快捷直达',
        quickLinks: [
          { label: '仿真成果', href: 'https://tcad.xjtu.shop/#results', icon: 'radiation' },
          { label: 'Agent 架构', href: 'https://tcad.xjtu.shop/#architecture', icon: 'agent' },
          { label: '技术文档', href: 'https://tcad.xjtu.shop/docs/', icon: 'docs' }
        ]
      },
      status: {
        domain: 'status.xjtu.shop',
        tag: '实时遥测看板',
        icon: 'telemetry',
        title: '实时仿真状态与算力看板',
        description:
          '查看公网只读脱敏算力遥测、隔离虚拟机调度矩阵、当前运行任务以及首月 r0.6 正式研究矩阵推进进度。',
        ctaLabel: '进入 status.xjtu.shop',
        ctaHref: 'https://status.xjtu.shop/',
        quickLinksTitle: '快捷直达',
        quickLinks: [
          { label: '调度矩阵', href: 'https://status.xjtu.shop/#schedule', icon: 'server' },
          { label: '运行任务', href: 'https://status.xjtu.shop/#tasks', icon: 'simulation' },
          { label: '研究计划', href: 'https://status.xjtu.shop/#research', icon: 'ledger' }
        ]
      }
    },
    statusBadge: {
      loading: '正在读取遥测…',
      stale: '等待更新',
      unavailable: '遥测暂不可用',
      operational: '在线',
      degraded: '降级',
      maintenance: '维护中',
      offline: '离线',
      activeTasks: '运行中'
    },
    highlights: {
      eyebrow: 'VERIFIED RESEARCH HIGHLIGHTS',
      title: '已审计核心指标',
      items: [
        {
          target: 60000,
          suffix: '+',
          label: 'Geant4 初级质子事件',
          note: 'r0.4 完整保留零沉积事件以保证翻转截面分母无偏'
        },
        {
          target: 396,
          suffix: '',
          label: 'r0.6 正式矩阵槽位',
          note: '含 58 个留出封存算例；P0 无粒子基线单独统计'
        },
        {
          target: 128,
          suffix: '',
          label: 'v3 TCAD 算例规模',
          note: '完成 1T1C 与 BCAT 电荷漏斗效应混合模式瞬态基准'
        },
        {
          target: 172,
          suffix: '',
          label: '预测器离线测试通过',
          note: 'R→A→F 物理约束代理网络已完成离线契约验证'
        }
      ]
    },
    scope: {
      eyebrow: 'MILESTONES & PUBLIC BOUNDARY',
      milestoneLabel: homeContent.zh.signals.milestoneLabel,
      milestoneText: homeContent.zh.signals.milestoneText,
      pipelineLabel: '四层研究链路',
      pipelineText: 'Geant4 10.7.3 → Sentaurus TCAD + 原子 PMI → R→A→F 网络 → server-codex-v2',
      boundaryNote:
        '公开门户严格只读：不暴露内部 run_id、服务器文件系统路径或封存留出集明细，并严格区分工程归档与科学验收口径。'
    }
  }
};
