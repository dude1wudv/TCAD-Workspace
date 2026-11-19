# A0 A1 A4 原始输出审计

`audit_probe.py` 只读既有运行器的 `manifest.json`、`inputs.tar`、`results.tar` 和 `run.sh`。它不连接SSH、不启动求解、不解压归档、不运行旧审计器的导出入口，也不更新v3或v4运行账本。显式指定 `--output` 才写审计JSON和曲线CSV。

## 调用

```powershell
python -B experiments/dram-see-v4/source-probe/audit_probe.py audit <run目录> --project <冻结工程目录> --output <v4审计输出目录>
python -B experiments/dram-see-v4/source-probe/audit_probe.py compare <A0运行目录> <A1运行目录> <A4运行目录> --output <v4比较输出目录>
```

Python接口为 `audit(run_path, project_path=None, output=None)` 和 `compare(a0_run, a1_run, a4_run, project_paths=None, output=None)`。`project_paths` 可为 `{'A0': path, 'A1': path, 'A4': path}`。比较函数重新审计三个原始归档，不接受未经核验的曲线或摘要替代。CLI通过返回0，失败或不完整返回1；报告保留失败检查名称与原因。输出参数是目录，必须位于 `local_runtime/dram-see-v4/source-probe/`、本目录 `data/` 或 `results/` 的子目录。默认没有写入。

单次输出 `audit.json` 及可用的 `circuit.csv`、`circuit_raw.csv`、`device.csv`、`device_raw.csv`；CSV保留数据集原名。比较输出 `audit.json`，包含三份独立审计结果、A1/A4生成曲线与连续电压/电流的差，以及相对同存储态A0的保持节点电压、电容电荷及4ns位线电压增量。

## 核查内容

- `COLLECTED`、原始整数SSH退出码0、归档内远端退出码0、执行及SDevice完成标记；未知值、恢复补值或非零退出码均拒绝。旧运行器没有独立持久化归档传输退出码，报告如实标为未知，不伪造0；归档哈希、完整输入与产物另行核验。
- 输入归档全部文件与manifest一致，结果归档中的输入副本仍一致；可选冻结工程目录也逐文件比对。对全部tar成员拒绝路径穿越、重复文件、链接和特殊文件，全程不解压。
- 当前冻结 `source_contract.json` 与归档副本逐字节相同，容差等于主代理冻结值。源事件身份、A0空轨迹、A1的1fC和A4两个同形同位同时0.5fC分别验证。
- 命名HeavyIon命令、参数文件的十个显式系数、LET单位标记与源记录一致；去掉源和参数文件声明后的完整deck必须等于继承R50的物理、电路、全程初始化及时序模板。
- 电路与器件曲线时间有限、单调、从0到4ns且包含要求的节点电压、端电流及电流分量；保留重复时刻原始行。局部KCL、电容电荷和端电流符号采用原有R50纯数值检查，不调用旧审计/导出函数。
- `HeavyIonGeneration(Integrate(Semiconductor))` 必须有明确总量数据集。非零源缺字段或字段不唯一时拒绝。A0无该字段时，单独标为 `source_free_deck_without_generation_dataset`，不声称观察到了数值零生成场。
- A1/A4必须拥有相同实际网格字节和公共器件/时序契约。生成、电压及电流曲线按原始采样时间并集做分段线性比较，禁止外推；保存最大差、出现时刻和判定界限。

生成量的量纲合同为：空间积分采用µm³，生成率为电子空穴对每cm³每秒，时间为秒；积分乘 `1e-12` 转换成对数，再乘基本电荷和 `1e15` 得fC。对应继承二维器件的1µm有效厚度和 `AreaFactor=1`，不将电子与空穴重复乘2。报告同时保存原始积分、对数、生成电荷与源目标。这个维度核查不是独立三维校准，生成电荷也不等于最终节点收集电荷。

## 容差与边界

TCAD生成积分相对误差5%，零源绝对值 `1e-6 fC`，终点绝对误差 `1e-18 s`；A1/A4生成电荷差 `1e-4 fC`，生成曲线差为成对峰值的 `1e-3`，电压差 `1e-5 V`，端电流差 `1e-12 A + 1e-3 × 成对最大绝对电流`。解析源离线积分0.1%由输入生成器检查，不与TCAD的5%混同，也不随结果放宽。

本轮仅存储1的A0/A1/A4能力验证。报告始终保留 `scientific_calibration_passed=false` 和 `numerical_convergence_validated=false`。通过不代表90nm器件校准、网格或时间步独立性、临界分类稳定、空间分离多轨迹有效、三维验证、核反应输运或真实粒子概率。没有独立中性单元参照，不计算v3裕量或位翻转分类；只报告原始电压、电流和对A0的连续增量。

## 开发验证

开发测试位于 `local_runtime/dram-see-v4/source-probe/audit-dev/test_audit_probe.py`。八项软件检查覆盖完整制造夹具及比较、未知SSH退出码、归档哈希错误、路径穿越与符号链接、非有限/截断曲线、禁止外推及电流差、重复JSON字段/缺失运行和旧原档解析。制造夹具明确标为 `SYNTHETIC SOFTWARE TEST`，仅暂存在开发目录，不作为真实v4结果；真实旧归档仅用于复用解析器和电路曲线格式验证。
