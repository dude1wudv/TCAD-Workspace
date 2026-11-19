# F5 capture 未应用补丁候选

状态：离线实现完成，候选待主审、未应用。只生成针对现有 `scripts/tcad.py` 与
`experiments/dram-see-v4/transport-probe/operation.py` 的 unified diff；不应用，不另存可执行runner，
不调用SSH、原生工具或候选代码。主账本 E001–E003 约束所有证据含义。

以下决定先于依赖代码登记；后续由主代理整合到实施记录。

| ID | 补全决定 | 边界 |
|---|---|---|
| C001 | 两入口原始SHA-256必须与冻结基线一致，否则build_patches立即拒绝，输出新目录不得已存在 | 不按模糊上下文匹配或自动迁移旧补丁 |
| C002 | 仅向原有run.sh添加共享的只读/proc观察函数；每次仍只启动一个原有native命令，随后wait真实child PID并保存其实际返回值 | 观察失败不能kill、重试或启动替代native任务；stdout/stderr原重定向保留 |
| C003 | TCAD按`step-{index:03d}-{tool}`命名exit/process证据，防止同名工具多次调用覆盖；SVisual用`svisual-process-status.txt`及原`task.sh`写出的`svisual-exit-code.txt` | 主代理接受索引绑定；当前S2每角色一个SDevice，多个须新合同 |
| C004 | 进程发现仅遍历明确启动child的`/proc/<pid>/task/<pid>/children`链，并核对每条PPid/starttime；只接受Name和ELF可执行文件basename都与请求tool精确相同且exe在配置安装根下的进程。lifetime键为PID/PPid/starttime，允许同一PID从taskset/launcher正常exec而改变Name | 不用pgrep/全局进程名扫描定位；多个匹配保留ambiguous，缺失/短命/launcher不可绑定保留unavailable |
| C005 | 记录真正匹配native PID的原始/proc/status、exe、启动tick和完整父子链；成功写status前复核链身份 | 父shell的affinity不能替代；单次快照只证明观测时刻，native并行banner及其他门仍独立核对 |
| C006 | SVisual仍由现有operation内的`bash task.sh`调用。wrapper只对这个task PID的后代做有界观察，再wait原task；不改写/拦截task.sh或原生命令 | task的退出码与SVisual退出码分开；后者必须来自task现有真实调用记录，缺失仍为null |
| C007 | 观察最多2秒、每50ms重查一次；仅增加短时只读observer，可漏过过短或延迟启动的native进程 | 漏观测不终止健康任务；未知不能成为原生资格通过 |
| C008 | `flock -n 9`成功之后立即写`shared-lock-evidence.txt`，含ACQUIRED、fd=9、锁路径、wrapper PID及UTC | 该状态来自控制流刚通过真实flock，不从工程完成标记推导 |
| C009 | tcad manifest新增collection_exit_code及原archive退出/各step退出字段，初始均null；只从实际调用返回值或唯一原始exit成员填数 | CalledProcessError保留实际rc；超时/没有returncode保持null；不因COLLECTED默认填0 |
| C010 | 两补丁须同批次审查发布；operation候选调用tcad候选的共享capture函数 | 当前没有部署；不满足基线、原生资格及发布要求不得执行 |
| C011 | 按主E008，未来真实入口创建manifest/operation时写`origin=native_pipeline`、`synthetic=false` | 当前构建报告为patch candidate，绝不创建native receipt；这两字段也不能代替执行/原始归档证据 |
| C012 | 原tcad.py已有的`sdevice -v`保留一次调用并独立捕获为`metadata-sdevice-version`，不计入求解steps；operation wait非零须exit原rc | 不增加版本探测；不把所有非零task退出码改为test命令的1 |
| C013 | 按主代理新增要求，SDE/snmesh/SDevice step必须先wait实际child并写真实tool rc；tool rc为0时再做独立process-observation准入，缺测/歧义/线程或CPU违约阻止同run后续依赖step | 不杀健康child、不把观察失败改写为native非零rc。独立准入失败码86，与tool-exit-code文件分开；原版本探测仅记录rc，不要求PID观测。此新增准入候选待主审 |

## API与最终候选

`build_patches(output: Path) -> dict`：输出必须位于本轮
`local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/capture/`内的新目录。只有两份
`.review.patch`及`capture-patch-report.json`会被写出，不保存完整candidate `.py`文件，
也没有apply、SSH或原生命令入口。

本轮交接候选为 `capture/r3/`；r1、r2保留为离线迭代历史。r1之后修订了root进程从
launcher正常exec时的lifetime判断，加入原有版本探测真实rc，以及wait后的独立准入。
r2/r3的补丁正文相同，r3额外核对ELF magic为真实4字节并完善未验证声明。

| 目标 | 冻结来源SHA-256 | 内存candidate SHA-256 |
|---|---|---|
| `scripts/tcad.py` | `8a08d895d788f053da8d07cc29dd7c745ede9b5f3b29b757ad012ca79f7779d5` | `12e96339903dda5f5cdcdc32f69473e383e94787294de3c8db17903acff9f4a3` |
| `transport-probe/operation.py` | `55d4b650b047be490a1aeb6b5c6d97c833e9bcab3c7ccbfc17ce7ee53c930d1b` | `1b8ce6b9d27ed7db0cca90f3f339c16acdfd76bb8ca91d1c21cb77573a453ba7` |

补丁SHA-256分别为：

```text
tcad.review.patch
8e2cb94c190b8dfcfff0f365efc6116ea3f54b60ee1de5587479de4f9b6ab87f
operation.review.patch
254f3c52b93d27e7d2cd86f18366569d05277da24b50a0275a5cb81179613b22
```

## 未来真实调用会留下的文件

TCAD manifest新增`origin=native_pipeline`、`synthetic=false`、`collection_exit_code`、
`remote_exit_code`、`version_probe_exit_code`、`tool_exit_codes`、`tool_evidence`，未知初值均为null。
原始远端`exit-code.txt`、逐工具`step-NNN-TOOL-exit-code.txt`仍在原归档中；manifest只从唯一、
regular、大小有界且合法的原始退出成员读取，不从工程完成标记生成数值。

每个step的证据文件通过manifest的`tool_evidence`映射绑定：

- `step-NNN-TOOL-process-status.txt`：真正native PID的原始`/proc/PID/status`；缺测不创建。
- `step-NNN-TOOL-process-observation.json`：真实root child PID、wrapper PID、native PID/exe、
  启动tick、完整PPid链、采样UTC和raw status hash；状态OBSERVED/UNAVAILABLE/AMBIGUOUS。
- `step-NNN-TOOL-process-admission.json`及独立`...-process-admission-exit-code.txt`：在native
  child已结束且真实tool rc已保存后，判断观察绑定、原始线程=1及CPU为指定单核。失败阻断
  后续step；它不会改写tool的0退出码。失败码86只是捕获准入失败。

operation保留原`task.sh`内容、执行输入哈希、SVisual命令与stdout重定向，新增
`operation-task-exit-code.txt`记录原task的实际wait返回。若task包含当前配置安装目录下明确
的SVisual命令行，观察其精确后代链并写`svisual-process-status.txt`和
`svisual-process-observation.json`。没有重写task，也没有第二runner。
operation记录中的`tool_exit_codes.svisual`只能来自task原本写出的`svisual-exit-code.txt`；
缺失仍null，不用task rc冒充SVisual rc。

两入口仅在真实`flock -n 9`成功之后写`shared-lock-evidence.txt`，字段为
`status=ACQUIRED`、`fd=9`、`lock_path`、`pid`、`acquired_utc`。候选的配置锁路径与原锁一致。
当前没有产生这些native文件；报告里的文件名都是未来接口定义。

## 已完成的离线检查

本轮用本机既有Python运行 `python -B -`，通过stdin导入新generator并调用：

```python
report = capture_patch.build_patches(capture_patch.CAPTURE_ROOT / "r3")
```

最终退出码0，证据为`capture/offline-check-r3.json`。实际检查仅涉及文本与AST：

- 两candidate Python AST解析、compile；嵌入的/proc观察器与准入器也只解析/compile，没有exec。
- 对`connection`、`remote`、`execute`、`doctor`、`main`比对AST，确认严格SSH入口未改；
  SDevice线程参数、输出存在检查、共享锁和原任务调用保留。
- 检查实际wait rc先写、准入rc后写、原task非零rc原值传播、版本探测只有原有一次调用、
  多匹配拒绝、真正PID/exe/父子链、无pgrep/kill/原生启动的observer。
- 只在generator内存中故障注入错误expected SHA：构建拒绝且未创建输出目录；原文件未修改。
- 已存在输出拒绝覆盖；最终输出仅2个patch和1个JSON；来源SHA在构建前后仍等于冻结基线。

没有运行候选脚本、Bash语法检查、原生进程模拟、SSH、SDE、snmesh、SDevice或SVisual。

## 待主审与未验证

这些补丁不能发布为“已验证修复”。vendor launcher实际Name/exe是否满足保守匹配、短命或
延迟native进程是否落入2秒窗口、Bash运行语义、真实wait/异常归档路径、实际后续step阻断
均未原生验证。Name或ELF basename不精确匹配时不会猜测；该观察可缺失并阻止后续预算消耗。
单次真正native快照只证明那个采样时刻，不能证明整个运行期间始终单核单线程。

主代理特别要求的C013是新增观测准入候选，需和新collector、发布合同一起审查。
SVisual operation没有后续native阶段，观察缺失不会改变原task rc；新审计须拒绝原生资格。
两patch因共享函数依赖必须同批审查；新预算、实际native资格和明确执行发布仍未取得。
