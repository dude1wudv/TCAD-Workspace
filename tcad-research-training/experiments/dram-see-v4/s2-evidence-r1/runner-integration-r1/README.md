# 原 runner 归档前几何接线：离线集成候选

本目录生成可审查的原runner补丁和首四角色输入候选。原`scripts/tcad.py`、operation、capture/r3、S2 packages-r2、geometry candidate-r1、release-candidate-r2和旧预算均保留；没有应用、发布或原生调用。

```powershell
& .\local_runtime\vdmos-analysis-venv\Scripts\python.exe -X utf8 -B .\experiments\dram-see-v4\s2-evidence-r1\runner-integration-r1\prepare.py --output <全新integration-runtime目录>
```

该命令只生成文件。输出没有`project.json`，所有`project.review.json`与发布/预算提案关闭执行。`tcad.py.review`是原runner的文本审查副本，不是新增runner；两个tcad补丁分别表示相对capture/r3的新增接线和相对原源码的合成差异，不能同时应用。原operation capture/r3补丁原样带入，仍需同一次独立审查发布。

## 实际接线

D2/D3同一SDE进程输出`cell_bnd.tdr`、`cell.cmd`和CAD观测；随后原runner显式执行一次`snmesh --threads 1 --max_threads 1 cell`，得到`cell_msh.tdr`。这样可保留mesh真实子进程退出，不借用SDE摘要。原资源guard在mesh后运行，通过才制作实际mesh描述符并调用一次几何SVisual。

SVisual结束后，桥接只读原始文件生成`observation-context.json`并调用未改动的evaluate.py。几何比较通过后才继续SDevice；报告、原观测、context和原始退出均在原`results.tar`创建前形成。失败停止后续步骤，保留已有错误/原档。整个过程仍由原runner、owner、共享锁与单核单线程控制，不增添operation或探针run。

capture/r3的`step-001-sde-exit-code.txt`、`step-002-snmesh-exit-code.txt`、`step-003-svisual-exit-code.txt`原样保留；规范退出文件逐字复制并记录来源。原生返回值与capture admission返回值分别保留，缺退出文件不补0，非零不伪装成功。

两A0在冻结自己的输入前读取已明确验收的D3原档，按原报告证据清单导入同一mesh和几何记录，保留D3 producer_run_id及context；当前A0的release不会覆盖D3来源release，后者存于`geometry-producer-bindings/`。没有D3实测/验收就不能导入，也不以空值生成成功。

## 预算归属

| 角色 | 类别 | SVisual调用提案 |
|---|---|---:|
| B1-D2 | native_geometry_extractions | 1 |
| B1-D3 | native_geometry_extractions | 1 |
| B1-A0-main-b0 | native_field_extractions | 1 |
| B1-A0-main-b1 | native_field_extractions | 1 |
| 首切片合计 | 两类分别预约 | 4 |

几何提取不占用原两次字段提取，也不转借nuclear-closure-r1的历史postprocess余额。未来须在独立S2账本按角色和类别预约；失败或未知调用仍计费，纠错需要另行发布。当前批准/预约/消费全部0，原预算文件完全不改。原首切片4CPU小时、8GiB保留量提案也不增加；几何成本须纳入其内并有资源依据，超限即停止新提交而不是杀作业。其他阶段和训练预算保持原样。

## 验证边界与下一步

只验证本轮新增接线及拒绝路径，复用旧29项、15项和Tcl mock结果。离线检查不验证SDE/SVisual/snmesh厂商语义、真实原档或G1/G2。技能同家族假设审查仅provisional；原PMI实际BE未更新、R12未编译/发布仍受阻。

本轮的当前报告由`local_runtime/dram-see-v4/s2-runner-integration-r1/current-preparation.txt`定位。后续实施仍须把独立预算、精确输入/run ID、比较和资源策略、用户原生授权及原runner/owner发布连成同一份有效执行合同，再做现场准入。本候选本身不授权这些操作。

[规格](implement-stage/SPEC.md) · [事前决定](implement-stage/ASSUMPTIONS.md) · [实施记录](implement-stage/BUILD_NOTE.md)
