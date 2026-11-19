# v4 厚硅核机制见证：阶段简报

本轮完成了预注册的 **212 个初级质子事件**及其逐轨迹、逐步骤记录，得到 **9 个合格的质子核非弹性机制见证事件**。首例能够追溯到核相互作用步骤、直接次级及其电磁后代。这里验证的是 Geant4 记录链与物理机制分类；**厚硅靶不是 DRAM，尚不能据此声称 TCAD 耦合完成或得到 DRAM 翻转概率**。[冻结合同](../../witness-contract.json)、[汇总及证据哈希](summary.json)

## 条件、事件清单与分母

几何为 10 mm Si 立方体与边长 40 mm 的真空 world；100 MeV 质子正入射，发射点在入射面中心前 1 um。H 臂使用 QGSP_BIC，并将电磁部分替换为 Opt4；E 臂只使用 Opt4。production cut 为 10 um，Si 带电粒子最大记录步长为 100 um，保留参考列表的 10 us 中子追踪时限。E 臂仍包含 Opt4 的 nuclear stopping/NIEL，不能理解成“去掉所有核能损”。这些是宏观机制诊断条件，不能当作 DRAM 源映射分辨率。[实现与物理语义](../../README-implementation.md)

| 预注册运行 | seed | 初级事件数 | 合格见证 event ID | 最终采用的审计 |
|---|---:|---:|---|---|
| H/E 初始化 | 40131401 / 40131402 | 0 / 0 | 不产生粒子事件 | r1，零事件建表 |
| H/E pilot | 40131501 / 40131502 | 2 / 2 | 无 / 无 | r2 |
| H 固定种子 1 | 40131601 | 64 | 3、13、32 | [r4](../../../../../local_runtime/dram-see-v4/transport-probe/audits/witness-fixed-h-s1-r1/audit.json) |
| H 固定种子 2 | 40131602 | 64 | 10、11、41 | [r4](../../../../../local_runtime/dram-see-v4/transport-probe/audits/witness-fixed-h-s2-r1/audit.json) |
| H 固定种子 3 | 40131603 | 64 | 3、16、21 | [r4](../../../../../local_runtime/dram-see-v4/transport-probe/audits/witness-fixed-h-s3-r1/audit.json) |
| E 固定种子 1 | 40131701 | 16 | 无 | [r4](../../../../../local_runtime/dram-see-v4/transport-probe/audits/witness-fixed-e-s1-r1/audit.json) |

总分母为 H **194** 个、E **18** 个初级事件，包括 pilot；初始化不计入。发现首例后仍完成并保留全部预注册事件，没有换 seed、按见证挑选样本或追加事件。导出的 [all-events.csv](all-events.csv) 有 212 行，按 run 与 event ID 唯一标识；共记录 **5878 条轨迹、46631 步、5666 条稳定出生绑定**。其中 16 个事件存在 type 4 核过程步骤，但只有 9 个满足本轮见证条件。本批没有零 Si 电离沉积事件；记录与审计仍保留零沉积事件及步骤的处理规则。[完整汇总](summary.json)

以上是固定诊断样本的描述计数。不同物理臂的事件不能按相同序号相减；9 个见证也不能除以 212 后解释为 DRAM 概率、翻转截面或空间环境事件率。图中的出生能量分布是这批记录的样本分布，不是按入射通量归一化的能谱。

## 首例及母子链

选择规则在合同中预先固定：按 requests 顺序（含 pilot），再按数值 event ID 选首个合格 H 事件。首例为 `witness-fixed-h-s1-r1`、seed `40131601`、**event 3 / primary track 1 / step 31**；实际过程为 `protonInelastic`，type **4**、subtype **121**。其直接子轨迹为 **9–15**，进一步后代包括 track **16**，这些核后代的 Si 电离沉积合计 **36.76421607279538 MeV**。[首例出生绑定](selected-birth-links.csv)、[轨迹原始字段](selected-tracks.csv)、[步骤原始字段](selected-steps.csv)

首例直接次级含两条质子、一个中子、α、Li7、γ 和 O15；其中 γ track 14 通过 `compt`（type 2/subtype 13）产生电子 track 16。该电子的出生动能为 **0.10707513207089731 MeV**，属于“核后代再产生的电磁后代”。中子 track 11 的 Si 电离沉积为零，仍保留在记录中。整个 event 3 另有原初质子的直接电离与其他 EM 次级，因此全事件 Si 电离沉积 **40.41779593491412 MeV** 不等于上面的核后代分量。[事件台账摘要](source-ledger-summary.json)

[首例母子图](figures-r2/selected-ancestry.png)与[轨迹、出生能量图](figures-r2/selected-tracks-and-birth-energies.png)用于展示这一链条。精确关联来自产生时建立的 token，再绑定实际 childTrackID；位置或时间相近不作为母子关系的判据。

## 分类含义与本批观察

| 分类 | 本批轨迹数 | 判定含义 |
|---|---:|---|
| 直接核后代 | 73 | 自身 creator type 为 4；包括符合条件的核弹性等过程，不仅限于 `protonInelastic` |
| 核祖先链中的 EM 后代 | 62 | 自身 creator type 为 2，且母链存在 type 4 creator |
| 核祖先链合计 | 135 | 自身或任一祖先的 creator 为 type 4；与前两行不是可重复相加的独立分母 |
| 原初核作用后产生的 EM 次级 | 106 | 母轨迹是原初质子，且在产生步骤开始前已经发生核作用；不能据此标为核 creator 后代 |
| 原初首次核作用同一步产生的 EM 次级 | 0 | 单独保留歧义类别，不声称发生顺序严格在核作用之后 |

计数来自 [summary.json](summary.json) 的 `ancestry_classification_counts`。同一初级事件的全部轨迹共同保留，不能把每个次级当作新的独立入射样本。

终止记录为 **244 条逃出 world、5634 条自然停止或吸收**，本批没有 unknown 终止。标准 `nKiller` 实际触发步数和轨迹数均为 **0**。它仍存在于 H 物理列表，身份按 neutron PDG 与实际过程 type/subtype 核对；本批未触发不能证明晚中子截断对其他工况无影响，也不能替代该实际终止分支的验证。[逐事件计数](all-events.csv)、[各运行审计引用](summary.json)

## 审计修订及保留的限制

最终四个固定批次均由 **r4** 审计通过；审计代码 SHA256 为 `245161332df6b078809d1eaf79c88b67951b8bf78824ccd7df4d5d79272534b5`。初始化和 pilot 沿用当时有效的通过记录，并未改写成“全部由 r4 审计”。每个运行的原始退出码、归档和输入输出哈希见汇总链接的审计文件。

- **MSC 端点语义修订（r1 → r2）：**原先附加的 `chord <= step` 断言不适用于 Geant4 分别提出输运步长与抽样位移后的端点。H pilot 的失败原档与审计保留；修订删除错误的普适不等式，保留坐标重算、有限性、100 um 记录步长限制与超出诊断，没有扩大数值容差。[r1 快照与失败证据](../../revisions/audit-r1-before-msc-fix/revision-evidence.json)
- **延迟次级语义修订（r2 → r3）：**模型可在同一母产生步骤返回晚于母步骤结束、甚至晚于母轨迹结束的次级。保留原始时间和精确 token，移除两处不成立的出生时间上界；因果下界及轨迹内部时间单调性保持。延迟不被裁剪，也不直接解释成某一核能级寿命。[r2 快照与官方依据](../../revisions/audit-r2-before-delayed-secondary-fix/revision-evidence.json)
- **动态离子库存修订（r3 → r4）：**默认粒子表遍历跳过 GeneralIon 核素，导致首组固定 H 审计失败。本批共 **19 处**过程核对采用受限 GenericIon 继承，涉及 **12 种核素标签**；原始逐离子库存缺口明确保留。只允许普通正核素 PDG、相符的 Z/A 与元素名称、合理质量范围，并精确匹配本次 GenericIon 的 process name/type/subtype；轻离子、中子、反粒子或未知过程不能通用回退。**这是继承过程证据，不是所有动态离子的原生库存已完整。**未来记录器应采用 `iterator.reset(false)`。[r3 快照与失败证据](../../revisions/audit-r3-before-generic-ion-inventory-fix/revision-evidence.json)、[规则和反例测试说明](../../README-implementation.md)

这些修订没有改变 C++、物理合同、seed 或原始 CSV，也没有为通过审计而重跑事件。记录中的沉积与 NIEL 分量已作算术闭合检查，但未证明包含静质量、核激发、反应 Q 值和逃逸能量的完整能量守恒。局部 `ionizing/step` 是离散沉积与记录输运步长之比，不等于无限制 LET 或质量 LET。

当前三维源台账仍标记 `tcad_ready=false`。[源台账摘要](source-ledger-summary.json)不能作为多径迹联合注入已完成的证明。下一步需将这条可追溯链路用于器件域映射、源项闭合和三维代表单元的联合注入验证，再讨论 DRAM 响应与预测数据。

本简报核对了合同与汇总哈希、各审计的通过状态/退出码和 hash 引用；逐行比对了 212 条事件导出与原始 events，以及首例 tracks/steps/birth-links 与对应 run 的 event 3 原档。这里只新增简报，未修改现有结果。
