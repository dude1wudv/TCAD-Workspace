# r13.2 来源、取得程度与采用边界

取证日期：2026-10-15（UTC−07）；原始抓取时间用UTC保存。较早r13“正文未取得”的状态已被本轮原档取证更新；历史文件保留。这里只记录本方案采用的定向证据，不称系统综述。

2026-10-16新增人类对齐与本地接口核对；本次未重新检索文献或改变器件数值。

| 来源 | 本轮证据与采用方式 | 边界 |
|---|---|---|
| [课程大纲](../../../docs/course-project-syllabus.md) | 课程必做功能、2–3人分工、导师审核、作品/总结/预测验证 | 本轮没有新增导师审核记录或实际学生分工 |
| 用户本轮要求及已保存导师指导 | α与质子；质子Geant4；从简单到复杂；先进选型服务课程 | 无中子初级、轨道谱、屏蔽或事件率授权 |
| [指定对话中的人类澄清](evidence/mentor-alignment-20261016.json) | 先进选型；训练中强化物理公式；先同步再按同学反馈分工 | 用户转述导师/甲方要求，不是导师已签发设计审核、PINN指定或新执行授权 |
| [物理训练实施选择](evidence/physics-training-alignment.md)；冻结S2 metrics/decks/field_audit | 现有SN电流符号、14.9984–19.9ns配对窗、显式电容和独立端点/电流标签支撑一个有限约束提案 | 公式与字段语义有代码依据；真实支路/数据尚需G1/G2；算法、权重和11fit安排是本次规划选择，未训练 |
| [Lee等2020 BCAT论文](https://www.mdpi.com/2079-9292/9/11/1908)；DOI 10.3390/electronics9111908 | 出版者PDF及XML均取得；原图/表核对。选Fig.2(c)常规非对称结BCAT；公开深度/峰值/结深范围和电学条件 | 缺横向结构、栅氧、体掺杂、电容及物理卡；本项目补充值均标假设；不是精确复现 |
| [Kim等2024 BCAT论文](https://www.mdpi.com/2079-9292/13/4/681)；DOI 10.3390/electronics13040681 | 出版者PDF及XML已取得，Table1/图核对；用于现代BCAT结构背景和选型对照 | 关键掺杂/绝对槽深未公开；部分结果明确为2D；不混入2020模型冒充同源 |
| [Samsung 2024 LPDDR5X公告](https://news.samsungsemiconductor.com/global/samsung-develops-industrys-fastest-10-7gbps-lpddr5x-dram-optimized-for-ai-applications/) | 沿用r13已核过的官方12nm-class背景 | 本轮未重新检索产品状态；不能当栅长、器件偏压、模型卡来源 |
| [SK hynix LPDDR6公告](https://news.skhynix.com/en/1c-lpddr6-development-2026/) | 沿用r13已核过的1c/第六代10nm-class背景 | 本轮未重新检索产品状态；不推断商业工艺结构或量产校准 |
| [NIST ASTAR](https://physics.nist.gov/PhysRefData/Star/Text/ASTAR-t.html)、[Si材料表](https://physics.nist.gov/cgi-bin/Star/compos.pl?matno=014)、[方法](https://physics.nist.gov/PhysRefData/Star/Text/programs.html) | 官方121行Si表及原响应已保存，3/5/7MeV数据有SHA；首批采用5MeV电子/核阻止分别记账及变LET表 | CSDA不是实测随机轨迹；未建封装/非Si路径；名义CAD掩膜积分已离线实现，未获原生场资格 |
| [Oldiges等，作者官方摘要](https://research.ibm.com/publications/theoretical-determination-of-the-temporal-and-spatial-structure-of-a-particle-induced-electron-hole-pair-generation-in-silicon)，DOI 10.1109/23.903811 | 约50nm径向、亚皮秒形成的量级依据；采用w=50nm/σ=0.2ps作显式假设 | 未取得论文全文；摘要半径不自动等于HeavyIon的w，σ不是原文校准值 |
| 本地W-2024.09 SDevice手册 pp810–816 | 已视觉核对HeavyIon单位、时间Gaussian、StartPoint、表数组、输出字段语义 | 受限手册与截图只留local_runtime；文档支持不等于新模型原生资格通过 |
| [Kim与Lee 2025 BCAT重离子研究题录](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART003221141) | 沿用既有相关工作记录，否定“BCAT辐射首次”的说法 | 本轮未取全文，不采用其中可能混用的能量/LET作为源参数 |
| [NASA SEE方法报告](https://ntrs.nasa.gov/api/citations/20240004894/downloads/20240004894-Ladbury_v2.pdf?attachment=true) | 沿用既有检索线索，未用于器件数值 | 本轮未全文审查；不能据系统级条目校准单元TCAD或事件率 |

细粒度来源与页/图/表、原始URL/字节数/SHA见 [device-evidence.md](evidence/device-evidence.md)、[device-source-manifest.json](evidence/device-source-manifest.json)及[alpha-evidence-manifest.json](evidence/alpha-evidence-manifest.json)。公开数值表和离线推导见[α报告](evidence/alpha-source-design.md)。原档分别留在 `local_runtime/dram-see-v4/course-plan-r13/device-evidence/` 与 `alpha-evidence/`。

结论边界：本轮已解决“候选全文与可用参数未知”，形成明确首选和实施假设；未解决商业/原文校准、真实3D构造、无粒子功能、原生源和数据预测的验证。先进代际相关性、代表模型数值有效性、真实器件可靠性是不同结论，不能相互替代。
