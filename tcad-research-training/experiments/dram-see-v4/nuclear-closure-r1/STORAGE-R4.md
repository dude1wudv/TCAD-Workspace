# 存储条件预测 r4：固定输入与可变输出

本修订只提供离线读取函数，不接入运行入口，不发布 release，不修改原 supervisor、状态、预算、runner 或任何正在运行的输入。是否启用独立工程适配由根控制器另行验收。若某已完成阶段已有合格自然核见证，无需为本预测追加输运；本模块不会选择事件或提交请求。本文件描述 helper 准备态，后续是否激活以 runtime 的 active-entry 及独立 `release-storage-r4` 为准。

## 原预测的问题与本修订边界

旧 `supervisor.preflight` 将每份结果的全部文件字节除以请求初级数，再取历史最大值乘未来 N 和四倍余量。normal-H 的两个事件共 750,020 B，其中五种事件 CSV 仅 73,862 B；二进制、源码、冻结合同和物理清单等也一起按 N 放大。历史最大值仍是 375,010 B/primary，后续更大的 N1 不会使它下降。

不能把其余 676,158 B 全部判成固定成本：动态粒子/过程清单会随出现的新核种增长。r4 仅把有同一 build 原档及全历史字节身份证明的输入按一次计入。其余文件仍全部为 variable；包含 particle/process/physics inventories、日志、请求、task、package-origin 和未知文件。不删除或忽略原始失败、重复留档和空间占用。

## API 与证据验证

```python
from storage_forecast_r4 import forecast
result = forecast(request, record_paths)
estimated_output_bytes = result["estimated_output_bytes"]  # Python int
```

`request` 必须是归档冻结合同中的完整正初级数请求。`record_paths` 接受 canonical `record.json` 或 run 目录，必须覆盖 `transport/runs/*/record.json` 中的全部历史记录，不能遗漏失败或挑选较便宜的样本。`repository_root` 关键字参数只用于隔离测试仓库；生产默认当前仓库。

每份记录验证：canonical run/request/path 身份、原 operation 引用、三类真实退出、完成收集状态、原 archive 哈希、完整 archive 清单、逐成员哈希、原输入清单，以及所有本地已导出成员的大小和哈希。未知/运行中/未完成收集的操作立即拒绝，不读它的可变输出。原生失败但已经完整归档的 `FAILED_COLLECTED` 可以作为成本证据；是否通过科学审计不参与样本筛选。

归档只读取，不提取。拒绝路径逃逸、符号链接、重复成员和未知非文件成员。读取前后重查 archive/record/operation 身份，并确认没有新增 canonical history 导致估计遗漏。

每份 `package-origin.json` 必须指向同一已完成、成功编译的 build operation；build archive 全清单和逐文件也重新验证。混合 build 历史拒绝估计，需要另行设计显式的未来 build 身份规则，不能静默丢弃旧样本来得到更小预测。

## 严格固定输入白名单

以下八个名字只有同时满足“原 run 输入、归档字节与同一 build 相同、每份历史均存在且完全相同”才可固定计一次：

- `transport_matched`
- `transport_matched.cc`
- `matched-contract.json`
- `geometry.hh`
- `geometry-contract.json`
- `environment.sh`
- `environment-spec.json`
- `dataset-inventory.json`

其中源代码、二进制、合同、几何、header 和环境不依赖本次请求的事件数。每个候选都有原输入 SHA256 与 build archive SHA256 双重证据。即使名字在白名单，只要缺少证据或与任一历史不同，就在所有样本里退回 variable。其他文件没有“看起来固定”的豁免。

## 公式与失败样本

设第 i 份已完成归档的可证明固定输入大小为 Fᵢ，其余全部字节为 Vᵢ；Dᵢ 为实际已完成初级数。输出采用精确有理数求最大密度和向上取整：

```text
F = max_history(F_i)
D_i = max(1, actual_completed_primaries_i)
V = max_history(V_i / D_i)
estimated_output_bytes = max(32 MiB, ceil(4 * (F + V * requested_primaries)))
```

原生失败只完成部分事件时，使用实际完成数，而非更大的请求数摊薄成本。零完成样本使用明确标记的保守“单初级密度底线”，不声称它真的处理了一个初级。这也使初始化和第一事件之前的失败不会被隐含排除。没有任何正初级数历史时拒绝使用 r4，保留原初始预测规则。

输出保留完整 `history` 分类与原哈希、`records` 引用、`fixed_bytes/fixed_history_max_bytes`、`variable_per_primary` 及其精确分数和最大样本引用、`legacy_history_max_total_bytes_per_primary`、`legacy_estimated_output_bytes`、`estimated_output_bytes`、本实现 SHA256。更大的 N1 样本不能降低任一历史最大值。

## 当前完成原档的测量

已离线核验七份完成的 canonical 原档，包括 N1 `nc-r1-h-000`（1000 个初级、1118 tracks、64869 steps）。固定输入合计为 339,953 B。

| 样本 | 总输出 B | 固定输入 B | 全部其余输出 B | 完成初级 |
|---|---:|---:|---:|---:|
| normal-H | 750,020 | 339,953 | 410,067 | 2 |
| N1 H | 37,180,323 | 339,953 | 36,840,370 | 1000 |

variable 最大仍来自 normal-H：205,033.5 B/primary，初始化 H 的零事件保守底线为 202,411 B，未超过它。N2 9000 初级的 r4 条件预测为 **7,382,565,812 B**；旧公式为 **13,500,360,000 B**。这不是把所有物理清单作为固定开销后得到的较小示意值；所有这些清单都仍按 variable 保守估计。

初次正常测量保存在 `local_runtime/dram-see-v4/nuclear-closure-r1/storage-r4/dev/measured-n2-forecast.json`，最终带实现身份的复核另存，不覆盖前次记录。以上数值不是未来核次级多重性的确定上界。

## 资源门槛保持

r4 不计算或减去旧归档占用，不能用预测替代真实磁盘测量。若根控制器将来启用独立适配，仍须原样检查：远端至少 8 GiB 余量、本地至少 20 GiB 余量、总保留资源 160 GiB 上限，保留原未来本地三份/总四份副本余量和单次预测的四倍系数。

所有失败、旧 build、旧请求与重复留档继续纳入原完整 `storage_bytes()` 和远端实际 stage 占用；没有 canonical `record.json` 的早期失败也不能从保留资源中扣除。旧原档不清理，历史最大密度不降低。不因预测能够通过就声称资源足够，实际启用前仍须唯一调度者取得新现场资源证据。

## 验证

隔离自测位于 `storage-r4/dev/test_storage_forecast.py`，所有夹具明确标为测试数据，只在该 dev 目录临时创建和清理。15 项测试已通过，退出 0：逐文件/归档篡改、历史遗漏/重复、混合 build、未知/未完成操作、未注册未来请求、失败/零事件保守底线、未证明的白名单文件退回 variable、未知文件和物理清单不固定、历史最大不下降、精确整数公式以及函数无写入。

原生求解、输运、SSH、新调度和 live 状态修改均未由本模块执行。根方独立验证与运行适配不属于此 helper 的自测结论。
