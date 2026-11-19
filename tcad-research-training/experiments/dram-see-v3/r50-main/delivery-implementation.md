# R50-main只读结果验收与课程材料入口

`delivery.py`只读现有证据，生成独占的新快照；不调用调度、transport、SSH、求解、GUI、安装或Git，不写ledger、阶段索引、模型冻结或原始档。适用科学设计SHA256为`6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740`，schema `dram-see-v3-r50-main`，physical revision `r50-main-r1`。

本源码实现完成不代表任何后续真实实验完成。真实收集与独立验收由主代理执行；首段活动源码及既有各manifest均未修改。

## 接口

以下是主代理后续调用模板，不是已经执行的命令。`SNAPSHOT_ID`必须是新目录。

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/delivery.py `
  --design experiments/dram-see-v3/r50-main/design.json `
  --ledger local_runtime/dram-see-v3/ledger.json `
  --stage-index local_runtime/dram-see-v3/physical-revisions/r50-main-r1/stage-index.json `
  --followup-plan local_runtime/dram-see-v3/physical-revisions/r50-main-followup-r1/plan.json `
  --extension-plan local_runtime/dram-see-v3/physical-revisions/r50-main-extensions-r1/plan.json `
  --prediction-dir experiments/dram-see-v3/r50-main/data/predictions `
  --native-root experiments/dram-see-v3/r50-main/figures/native `
  --snapshot experiments/dram-see-v3/r50-main/data/delivery/SNAPSHOT_ID
```

八个路径显式必填。尚未生成的阶段路径可以明确传入，输出`MISSING`/`INCOMPLETE`或依赖阻塞，不猜测结果。只接受该冻结设计、唯一全局ledger、R50专属prediction/native路径。`--no-plots`明确跳过绘图，保留JSON/CSV/材料，不能算图片验收。

可选`--visual-review <ROOT内JSON路径>`仅用于主代理已经实际检查两份原生PNG之后留下的真实记录；不提供时永远不认定目视通过。新源码manifest为`delivery-source-manifest.json`，`files_sha256`是五个已冻结首段/后半/扩展/报告/GUI固定清单的并集，加本源码与本说明；manifest自身通过文件字节SHA绑定到输出。不是目录glob，后来新增其他文件不改变此清单。依赖manifest冲突、文件缺失或哈希漂移直接失败。

正常的诚实部分快照返回0，含义仅是交付脚本成功。存在阶段/来源错误时仍尽量生成可审查快照，返回2。源码/设计漂移、重复全局run ID、路径逃逸、证据在收集和写出之间变化、输出已存在等致命错误会抛异常，不降级为成功。渲染中途失败可能留下未完成目录；没有完整`snapshot-manifest.json`就不是完整快照，后续使用新目录而不覆盖。

## 验收链及拒绝条件

1. 复用独立`reporting.py`的`RawReader`、实际R50审计/配对指标、8个物理参考+2个源隔离及预登记比较重算。只打开全局VERIFIED、runner0的完整原档；RUNNING、未知、FAILED和仅COLLECTED的响应原档不读。保留失败/缺失槽位。控制器函数不导入；固定case生成器、原边界排序及GUI纯解析函数按名称从受哈希保护源码AST提取，作用域显式给出。
2. 首段92个case逐项检查原计划、源码snapshot、原档参数、角色、parent、G4三原始文件、prepared inputs及case-freeze；原ledger快照的既有行、failure前缀及stages保持。训练阶段仍须完整64个训练响应，原始指标与stage文件一致。旧100 Ω、probe、不同几何/网格/角色均拒绝。
3. 预测检查`freeze.json`/marker/plan binding、六个冻结文件、实际UTC、64 training+64 test input身份以及完整来源覆盖。训练目标和测试已知control/neutral从原档重算；所有64个G4事件必须有验证过的三文件及真正收集的operation/events.tar/退出码，Qdep特征来自实际沉积。
4. 只以冻结64训练行重构四组bit/target模型，核验8条件LOCO的每fold训练scaler、lambda候选/选择、coef、mean及全部64条预测。该重构是内存只读审计，不产生新模型、不写新freeze；测试响应不进入拟合或选择。原模型的运行环境声明保留，算法数值按当前既有venv精确比对，环境变化造成差异时停止，不放宽容差。
5. 全项目实际`inputs.tar`中的参数及manifest run ID参与测试防泄漏，不能只靠旧tag。测试含失败提交也必须晚于真实冻结UTC；run ID秒级时区区间与ledger精确started UTC互查。已知活动项不读其归档，不能据此完成测试。发现不明来源/无输入档/未计划的R50输入则留错误。该过程只读input metadata，不读未验证的测试response结果。
6. 64个真实test case从自己的case-freeze与原档重审，原test-result和原冻结模型score重算比对。快照另以当前完整数值证据评分：所有failure别名都算invalid/failed，缺失单列；已知连续失败或未知状态使该响应及其匹配角色相关连续值无效，三阈值数值不确定。critical但连续审计通过仍保留评分。不拿氧化层、refinement、旧版或probe补齐测试。
7. extension计划重新用完整128个主响应计算所有阈值最小距离、condition/replicate/bit稳定tie，核对冻结ranking、selected、全部baseline和14项oxide/边界case。复用只允许原预登记完全相同的角色/位/步长/网格，绑定唯一run和原freeze，不重复记费。oxide逐个三联重算且核查新mesh、4/6nm与5nm同事件差值；boundary两目标×两变体重算，核对整张128阈值不确定表。实际连续失败返回NUMERICAL_FAILED；分类跨界保留不确定。未选但近边界无完整两变体的响应仍不确定。
8. 每个native目标独立核验，限定原设计两对象。校验原档4ns/TDR及actual runner source、真实view.tcl、两PNG结构/CRC/尺寸和hash、源前后校验operation、上传helper/Tcl、owned进程输出、真实capture stdout及completion指针。仅有完整机器来源证据仍为CAPTURED_PENDING_VISUAL_REVIEW，机器检查不证明色标实际视觉正确或隐私安全。

各证据门槛分别记录，不用后续总status替代各自原档。扩展已存在但未完整时可列出已完成/失败/未提交case；没有完成comparison文件则不预造比较。边界个别case来源错误不会隐藏独立完整oxide证据，但整体不能通过。所有主响应始终128个槽位、64独立事件；分层N=4、2.5/5/10 mV和原Wilson/零事件上界算法不变。唯一费用来源仍原global ledger，旧版/probe/验证/失败都保留，未结及缺费用单列。

## 明确目视记录合同

可选JSON要求：

```json
{
  "schema": "dram-see-v3-r50-main-visual-review",
  "physical_revision": "r50-main-r1",
  "images": [
    {
      "run_id": "ACTUAL_RUN_ID",
      "evidence_sha256": "ACTUAL_EVIDENCE_BYTES_SHA256",
      "png_sha256": {
        "final-field-native.png": "ACTUAL_PNG_SHA256",
        "own-window.png": "ACTUAL_PNG_SHA256"
      },
      "reviewed_utc": "ACTUAL_UTC_AFTER_CAPTURE",
      "reviewer": "ACTUAL_REVIEWER",
      "method": "actual_image_inspection",
      "approved": true,
      "field_verified": true,
      "units_verified": true,
      "run_identity_verified": true,
      "privacy_checked": true
    }
  ]
}
```

这只是字段模板，不能作为已审核记录，脚本不会写该文件。每目标至多一项，时间必须不早于capture完成、hash对应两张实际PNG；明确拒绝或任一检查非true保留`VISUAL_REVIEW_REJECTED`。没有记录保留pending。真实窗口、原生导出及DATA PLOT各自标明用途；不宣称Workbench Run按钮流程。

## 输出及课程边界

独占新快照包含`summary.json`、128行`responses.csv`、三阈值`statistics.csv`、`extension-cases.csv`、`stage-verification.json`、来源hash、可用时预测score/residual CSV、真实可画点的PNG/SVG与逐图source侧车、`figure-review-required.json`、`report.md`及全输出SHA清单。无观测只画计划状态计数，不造零响应、初态曲线或残差。每个DATA PLOT均为`PENDING_ROOT_ACTUAL_IMAGE_INSPECTION`；本入口不接受自身生成图的自动视觉通过。

课程材料生成：可行性、冻结设计/步骤/实际进度入口、两端方法与AI披露、参数来源表、作品演示脚本、10–12页答辩提纲、资料交接及材料索引。它们是代理可生成的草稿，单独状态`AGENT_DRAFT_MATERIALS_GENERATED`；不是已执行的学生演示/已渲染PPT/已提交课程报告。自然语言限定接口的实际学生演示及R50入口映射仍待独立真实证据，旧版演示不自动替代。

原始课程大纲及报告提纲在每次收集时按当前字节作为证据绑定，避免把后续真实日志更新当代码漂移。实际2–3学生分工、教师审核、资源交接、组内试讲、答辩、考核始终真实待办。导师20%/报告20%/答辩演示60%仅为大纲比例，不预测成绩。仿真完整时最多`SIMULATION_EVIDENCE_VERIFIED_PENDING_DELIVERY_REVIEW`；仍不能宣称全课程完成。所有结果维持未校准二维探索、理想初态、条件响应范围，不推商业可靠性或截面。

## 私有开发验证和未做事项

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B local_runtime/dram-see-v3/r50-delivery-dev/self_check.py
```

`self-check-03.log`：13项通过、exit0。覆盖固定92/64/14清单和完整128 selector；训练不全/测试泄漏/模型篡改拒绝；带显式raw stub的完整预测artifact路径；实际input metadata UTC/hash/未知来源/失败提交；六状态和critical连续评分；近界两变体和跨界；RUNNING不读；原版/probe拒绝；完整合成native链仍pending及PNG篡改拒绝；私有不可覆盖快照、PNG/SVG来源、课程pending。所有fixture和合成PNG/TDR/进程记录均在`local_runtime/dram-see-v3/r50-delivery-dev/SYNTHETIC-*`，显著声明非物理结果。

未真实调用collect、freeze、execute、SSH、solver、GUI或正式publish；未修改现有生产代码/manifest/ledger/data。合成测试显式stub原档审计/来源时，不构成真实原档通过证据。后续真实128/模型/扩展/native尚须主代理在实际完成后调用并独立审核；真实DATA PLOT逐张查看与人类课程活动尚未完成。
