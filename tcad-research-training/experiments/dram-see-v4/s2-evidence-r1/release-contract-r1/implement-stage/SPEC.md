# 首四角色离线发布合同

Target: 将已验收 integration candidate-r2、原 owner/runner、精确预定 run ID、输入、独立 S2 预算和比较/资源策略组成关闭执行的审查包。记录本轮真实用户授权；缺失批准不补造。

Inputs: 原 integration candidate-r2 及主验收、course budget proposal、原 supervisor/runner/operation、nuclear active-entry/budget、当前用户原文。

Outputs: ignored `local_runtime/dram-see-v4/s2-release-contract-r1/<stamp>/candidate-r1/`，包含 `contract.json`、首四 `roles/*/*.review.json`、独立 `budget.review.json`、owner/authorization/缺项记录及文件索引；全部是 review 数据，无 `project.json` 或可调用发布入口。

Success command: existing Python `prepare.py --output <new-candidate-directory> --authorization <record.json> --stamp <UTC-stamp>`；必要新增合同/拒绝路径检查。

Base commit: `eb49585b6d1c7c833fa5c17bc83393612232c379`，既有未提交工作保留。

Scope: 本次交付离线合同。用户允许调整细节、应用补丁及原生求解/编译/提取/训练，记录为有效行动授权；没有因此编造预算批准、策略批准、现场准入或原生资格。首四无编译/训练角色，不扩矩阵，不改旧入口/账本/冻结包，不新建 runner/operation，不重跑旧通过套件。
