# r0.6 P0 原编译消费、短 prefix 发布与启动异常交接

已读取r0.6授权。清单 SHA256 `ab1b6a44b5d965e249695b32b504248428c35aa0262a405a6e5b0f5232a930c6`，预算 SHA256 `b2849f5945754919eb18050acf4870dbd54d56e37a78aea0b9d3c9576dcd0379`。主核确认 13 profile、396 planned case、214 统计用途槽位，当前 accepted/statistics_eligible 均 0。清单未改，旧 r0.5 未提交提案继续暂缓。

## 本轮真实产物

- 原编译 run `auto-r06-p0-o2-cmi-build-r1-8fcbf3ff83ef4722` 已经原 Runtime 正常收集、exit0、验签和释放；276480 bytes 归档全部32文件（31索引 payload 加索引自身）核验，新 ELF SHA256 `bb77b42878a41dbe2efc603409479b6e8d512da5996a2cb1b3b46eab411ce594`。`consume_build.py` 只读原归档并复制精确返回，未编译或求解。`build-review.json` 与真实返回目录记录完整绑定。
- 使用冻结 `p0-bootstrap-r1/prepare.py materialize` 生成 `prepared-prefix-r1/`。两项原 r4 的新输入显式2线程/2核，原 mesh、deck、零源和物理头文件不变；全局日志新源码与真实新 ELF 已绑定。终点仅 `1e-13 s`，不做 WHR 资格认定。
- 独立 `verify_prefix.py` 实际184项检查、89文件SHA通过，见 `independent-prefix-review.json`。主代理消费关键原始证据并运行实际语义 gate；`2026-11-17T17:53:41.703172+00:00` 原子追加 a/b，55→57，旧55对象及字节SHA均核回保持。队列 SHA `84161beb96526bbdf86ff758c8308597268816321c1b7901baee4d730a8df55c`。`queue-receipt.json`、`postpublication-readback.json` 是发布与回读凭据；不表示原求解成功。
- 独立旧 b0/b1 无粒子分析见 `../p0-d0-hold-window-r1/`。主代理另用 frozen cache、Decimal 与独立 bisect 核回六个候选的六信号、原邻点、31.9ns精确读出，并复验七文件包 SHA。22ns仍候选，旧PMI不当新版本匹配对照，不授予r06 D0/Z资格。

## 当前必须沿原 ID 恢复

仅在发布后读取了一次原监督文件：`2026-11-17T17:56:05.143361+00:00`。prefix-a 已有原 run `auto-r06-p0-d0-o2-zero-prefix-a-r1-2f24d43e305e4322`，r4 slot0/CPU0–1，但原 manifest 缺失、启动未知。prefix-b 未提交，依赖 a；不改该依赖或另设新ID。

原 stderr 为：

```text
ERROR: Multicore shared pool does not admit Geant4 operations; use the original single-core profile in an idle pool
```

`diagnose_launch.py` 只调用原 runner 的本地只读预检，逐字复现该错误；完整诊断见 `launch-diagnosis.json`。`scripts/tcad.py:1435` 的 `parallel_assert_local` 终态列表没有 `FAILED_BEFORE_LAUNCH`，先读到旧 C0 原 operation，随后 `parallel_record_policy` 使用当前r4配置解释其原r3 operation，触发 `parallel_policy` 的多核禁止 operation 检查；该路径位于新本地 run 目录创建之前。旧 C1 同类原记录也保留。**这说明本地阻断机制，不替代对新原ID的未启动认证。** 不手写manifest/回执，不删除锁、不重放run、不消费数值修复预算。

维护所需：在原 runner 中对有完整原入口结案回执的终态作安全兼容，并保留对未知/不完整记录的拒绝；对新已落盘TCAD intent沿原ID取得原身份/目录/租约证据并正常闭合。当前边界不允许本轮修改控制器、执行策略或原账本，因此已保留精确诊断交给原维护流程。没有另投输入绕过缺口。

## 无粒子时序观察与边界

旧r04 L08/p000：18.2ns驱动斜坡结束时BL仍约0.134918/1.062144V，不能说电学预充已完成。22ns插值偏置 b0 −7.334804µV、b1 +3.685633µV，真实邻点最大绝对偏置16.126058/7.459399µV，邻点跨度0.5ns。21/22/24ns到31.9ns延迟10.9/9.9/7.9ns。31.9ns精确原行593/638，BL=0.556235089929007/0.626057299430457V，有符号读出裕量43.764910/26.057299mV。nV级SN1差仅为缓存描述，没有给连续时间、物理或数值误差界。

## 空间与下一唤醒

17:53 UTC：服务器可用61.79GiB，满足至少20GiB缓冲；虚拟机逻辑盘500GiB，guest /home分配86.97GiB、可用56.61GiB。服务器overlay目录本轮statvfs被权限拒绝，当前物理增长余量**未观测**，不推断、不与其它层容量相加。只做一次原SSH的df/lsblk只读查询，无环境/许可重验、无锁操作。原始字节与权限限制见 `storage-observation.json`。

下一唤醒须是原维护沿该prefix-a原ID产生新的对账/释放证据或真正的新原归档；不按日志持续追加反复唤醒。若原短prefix正常收集释放，核真实日志限额/警告/错误/完成、原行序与时钟、零G/UF及波形差；仍须同新PMI版本源有效短对照、非零积分和代表长任务。O2、数值重复性、时序、D0及其它Z资格均未授予科学通过，四条旧mc2粒子事件仍unknown，无损备份未finalize。正式训练、留出解封、HPO或网页部署未启动。
