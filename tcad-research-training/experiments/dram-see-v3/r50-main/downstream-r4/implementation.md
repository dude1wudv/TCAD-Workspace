# r4 后续来源与确定性扩展

这是软件实现，不是科学完成或实际激活。主代理唯一调度；本模块不改旧源、冻结预测、计划或原失败。真实扩展目录为 `local_runtime/dram-see-v3/physical-revisions/r50-main-extensions-r4/`。旧R50科学物理版本仍为 `r50-main-r1`。

## 独立来源层

`provenance.Session(extension_plan: Path | None = None)` 只加载私有模块和只读账本快照，绝不执行控制器、SSH、写入、拟合或预测生成。属性 `ledger` 是完整全局账本快照；`R` 是原main审计/指标/数值模块，`F.P` 是冻结模型predict/score接口，`ext` 是原扩展纯case/比较模块。

- `validate_chain() -> dict`：固定r1/r2c/r2e/r2f/r3/r4来源、计划/源码snapshot、无限授权、四alias及全部原FAILED/null退出码保全。显式扩展清单是唯一合法额外输入，不隐藏账本。
- `bundle(tag) -> dict`：输入canonical或actual tag，返回原审计bundle（summary、parameters、circuit等），同时绑定manifest/inputs/results哈希；FAILED原输出禁止载入。bundle不能替代owner核验。
- `trace_case(canonical) -> dict`：case owner、prepared inputs、freeze、原档、完整recipe/matching核验；返回response_id、actual_ledger_tag、run_id、owner_plan及hash、case_freeze及hash、input_sha256、archive_sha256。
- `observation(canonical_response_id) -> dict`：trace字段加`observation={metrics,readout_BL_V}`。
- `check_prediction() -> dict`：核对原r2f预测绑定、freeze/hash/六文件、原训练来源、真实全项目输入；仅调用固定系数predict_inputs，没有fit_models。
- `scientific_first() -> list`：重审真实references、pilot/source-isolation、preregistered和训练来源，返回两项原数值比较。
- `prerequisites() -> dict`：必须实际r4 test64终态；重审128逻辑响应/训练/测试、原r4结果与原评分、四alias、原边界排序。返回`files,baseline,selection,response_sources,aliases,original_failures,raw_submission_index,first_plan_sha256,training_plan_sha256,training_audit_sha256,prediction_plan_sha256,test_plan_sha256,test_result_sha256,prediction_freeze_sha256,original_prediction_scores,observed_tests`。first=r1，training=r2e，prediction=r2f，test=r4。
- `stable() -> True`：本次读过的原档与账本字节未变；真实新solve后必须新建Session。

四alias固定在provenance.ALIASES；不能假定r4计划的三测试alias包括训练alias。r2训练原FAILED与r3/r4三测试原FAILED保留；工程重试不增加64事件/128响应分母。原Windows未知退出码永不补0。

## 扩展和交付接口

`extensions.review(session, plan_path) -> dict` 是交付复用的完整只读审计，要求Session绑定同一个真实扩展plan。重新核验前置、每一新/精确复用case、重算并逐字段比较oxide/boundary和终态指针。成功返回`state=VERIFIED,plan,oxide,boundary,cases,comparisons,files`；cases含tag/run_id/state/raw_reviewed/reused/role/stage/new_independent_event。分类跨界保留不确定，连续失败或缺档不能返回成功。此函数把私有原builder的immutable写入口临时换成相等只读检查，并在finally恢复；不会生成丢失报告。

新源manifest固定绑定旧r4+旧extensions全部依赖以及四个本实现文件，不glob目录、不依赖将来的delivery文件。后续delivery需自己的manifest，不刷新本manifest。科学case生成器、原排序、4/6nm几何/匹配、比较阈值与原14项规则全部复用原实现。

14氧化层=两个厚度×(bit0 control+bit1 control+neutral+两原事件×2bit)。5nm四baseline由主逻辑响应解析，包含proton seed202610361 bit0的r3 alias。完整128按`distance,condition_id,replicate,bit`选择两个唯一response，不能从成功子集选择。两目标×两变体各匹配control/neutral/event，精确共享及原预登记复用才扣新费用；不能合并不同bit control。0.5mV/0.01fC容差及2.5/5/10mV分类不变；分类跨界、近界未确认、所有科学失败原样保留。

唯一全局账本累计全部旧/失败/重试/扩展费用。无限授权取消86400s、截止和单项估算上限，但费用缺失/非有限/负数、未知在途或孤儿仍阻断。每新case使用原锁、preflight和runner，单线程配置保持原输入。FAILED或未知原尝试不自动重发。

Windows主机检查同时枚举Python与SSH，记录PID/创建时间。只有当前进程的直接父PID、进程名为python/pythonw、当前实际入口为本extensions.py、Windows命令行逐token解析后的全部解释器参数/脚本/argv与sys.orig_argv严格一致，才豁免venv redirector（只有解释器路径允许不同）。同argv非父、参数不同父进程、SSH均不豁免。已有隐藏launcher仅限直接Python父、项目restart-launches内的单一launch.py入口（可带-B，无其他参数）；不按裸父PID或模糊子串放行。

## 根激活合同与命令

测试64、原r4评分/结果、全128及原科学门槛必须先实际完成。根检查实际控制器PID创建时间/命令、双锁、VM与manifest空闲，并独立验收源码/测试后，写 `local_runtime/dram-see-v3/physical-revisions/r50-main-extensions-r4-acceptance.json`：

```json
{
  "schema": "dram-see-v3-r50-main-extensions-r4-acceptance",
  "approved": true,
  "design_sha256": "ACTUAL",
  "aliases": {"FOUR_CANONICAL_IDS": "ACTUAL_FIXED_ALIASES"},
  "first_plan_sha256": "ACTUAL_R1",
  "training_plan_sha256": "ACTUAL_R2E",
  "training_audit_sha256": "ACTUAL_R2F_TRAINING_AUDIT",
  "prediction_plan_sha256": "ACTUAL_R2F",
  "test_plan_sha256": "ACTUAL_R4",
  "test_result_sha256": "ACTUAL_R4_RESULT",
  "prediction_freeze_sha256": "ACTUAL_UNCHANGED_FREEZE",
  "source_manifest_sha256": "ACTUAL_NEW_MANIFEST",
  "authorization_sha256": "ACTUAL_UNLIMITED_AUTH",
  "accepted_utc": "ACTUAL_UTC_AFTER_INDEPENDENT_REVIEW",
  "evidence_sha256": {"ROOT_REVIEW_EVIDENCE_PATH": "ACTUAL_SHA256"}
}
```

这是字段说明，不能当成实际验收。根在仓库根目录使用：

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/downstream-r4/extensions.py audit
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/downstream-r4/extensions.py freeze
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/downstream-r4/extensions.py execute
```

audit只读并输出核验索引；未完整时抛错。freeze只在空闲时根调用，独立目录不可覆盖；把旧账本真实字节保存ledger-before而不把可增长的ledger.json绑定为冻结依赖。execute可以在通过实时核查之后接续完整VERIFIED前缀，不重复提交，不跳过失败。终态只是`SIMULATION_STAGES_FINISHED_PENDING_DELIVERY`，仍须原生PNG逐图、最终报告/PPT/课程代理交付；学生/教师/答辩活动不虚构。

## 开发验证范围

```powershell
& local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/downstream-r4/test_downstream.py
```

所有临时fixture在 `local_runtime/dram-see-v3/downstream-r4-development/SYNTHETIC-*`，明确非物理证据。测试只读固定科学设计/源码、加载私有模块、注入synthetic I/O和工具mock；从不执行真实freeze/execute、SSH、VM、求解或GUI。具体命令/退出码/源码摘要在开发日志，独立验证及根真实激活尚需另行完成。
