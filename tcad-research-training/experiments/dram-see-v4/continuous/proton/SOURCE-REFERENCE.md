# 独立有限硅域源参考与真实时钟绑定

这组模块只读取原输入、原归档和原测量。它不调度、不编译、不写原始结果，不修改 `prepare.py`。输出始终保留 `native_qualified=false`、`pmi_r12_fixed=false`。字段数值比较通过也不代替主流程对提取器、原始退出、同网格和双载流子/匹配对照的验收。

## 单位、模型与判据

输入为原 `NUCLEAR_CLOSURE_SOURCE_V1`：两端坐标µm、两端时刻s、每段电荷fC、w=0.03µm、sigma=2ps。保留所有行，包括零长度和晚到沉积。原核是沿段参数u对归一化三维Gaussian与时间Gaussian的乘积积分；电子空穴对数只需在转成原生率时除以元电荷。没有再次调整3.6eV/对换算，也没有电荷重归一。

`geometry-contract.json`提供实际当前BCAT域、圆底槽、STI和GateVoid。Si域是完整外框扣除非硅体；GateVoid包含于外槽中，不会被计入Si。独立实现不导入 `geometry.py`、`couple.py` 或LET表格。它对每个Gaussian中心先解析积分x/y矩形，再对圆底部分用z=c+r sin(theta)消除根号端点，最后沿真实沉积段u积分。上部矩形和深部全硅区域使用解析z积分，避免三维体素误差。

输出分别保存全空间分配电荷、有限外框电荷、Si电荷、器件外损失、非硅损失、仿真时间窗损失。8sigma仅定义需要观测的窗口，不截断积分；时间窗外质量仍报告，晚到二级粒子超出求解终点会在时钟绑定时拒绝不完整窗口，要求延长相同匹配条件的求解。

参考积分固定初始归一化容差abs=1e-11、rel=1e-8，另用两者各除4重算全部交付区间/ROI并报告最大差值。该差值是数值加密证据，不冒称严格数学误差上界。体积积分内部再加严32倍，以保持独立Si体积核对的1e-11µm³精度。

科学数值门读取并绑定旧质子 `nuclear-closure-r1/contract.json` 的原值：源电荷5%、BE波形5%、空间质心0.01µm、ROI份额0.05、时间质心0.5ps、分区闭合5%；离线电荷门保留1e-6fC/0.001。没有套用α源资格。ROI明确来自当前BCAT：X按槽左右分3区；Y按STI两侧边界分5区；Z按圆底和STI深度分3区，另有全域Total。可通过 `--roi-file`提供显式窗口字典，但Total必须是整个有限域，自定义窗口不会自动被当成不交分区。

## 主代理集成顺序

1. 完成真实Geant4事件并通过 `couple.py` 保留原 `sources.dat` 与完整事件账本。当前参考模块支持相同源核，不将HeavyIon离散表反算为“原始源”。
2. 3D器件源窗输出每个实际接受BE区间的TDR，完整PLT保存 `IntegrSemiconductor HeavyIonGeneration`。源窗必须覆盖所有晚到步骤；空事件按结构无源记录，不伪造零场。
3. 从原solver run读取时钟，再算独立参考。下面路径中的run/source目录由实际运行替换：

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_clock.py --run local_runtime/runs/ACTUAL_RUN --output local_runtime/dram-see-v4/continuous/proton/ACTUAL_CASE/clock.json --window ACTUAL_START_S ACTUAL_END_S

python -B experiments/dram-see-v4/continuous/proton/source_reference.py --source local_runtime/dram-see-v4/continuous/proton/ACTUAL_SOURCE/sources.dat --geometry local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-build-20261017t043911z/collected/geometry-contract.json --clock local_runtime/dram-see-v4/continuous/proton/ACTUAL_CASE/clock.json --output local_runtime/dram-see-v4/continuous/proton/ACTUAL_CASE/reference.json
```

默认原生帧名模式为 `source_window[A-Za-z0-9_.-]*\.tdr`，可以 `--frame-pattern`精确指定实际deck的文件名。从原BE log读取每次真实尝试、接受/拒绝与Writing记录，用日志实际印出精度唯一对应完整PLT的精确时间；不按TDR序号或预期时间补时钟。保留重复分段初态行数量，只有时间和所有原生源列严格一致才保留先前接受端点。保留拒绝尝试，拒绝缺帧、重复写、映射歧义和PLT区间缺口。

新runner `tcad-native-run-r2`核对collection_verified、原始archive、remote/collection/version/tool退出和归档内原退出文件；SSH原码保留，可非零。无schema的旧run保留旧SSH+原wrapper规则，并明确单独tool退出是否可得。未知schema不会继承旧规则。

4. 原生提取器输出下述JSON，所有字段必须是同一TDR实际测量；`ONE`是对应Si∩ROI的体积，不能填包围盒体积。X/Y/Z乘场坐标必须是µm，积分体积必须是µm³：

```json
{
  "schema": "continuous-proton-native-field-measurements-v1",
  "field_name": "HeavyIonGeneration",
  "reference_sha256": "ACTUAL_REFERENCE_SHA256",
  "clock_sha256": "ACTUAL_CLOCK_SHA256",
  "roi_boxes_um": { "Total": [-1, -0.25, 0, 1, 0.25, 1] },
  "units": {
    "G": "cm^-3 s^-1 um^3",
    "XG": "cm^-3 s^-1 um^4",
    "YG": "cm^-3 s^-1 um^4",
    "ZG": "cm^-3 s^-1 um^4",
    "ONE": "um^3"
  },
  "frames": [
    {
      "source_file": "ACTUAL_ARCHIVED_FRAME.tdr",
      "source_sha256": "ACTUAL_TDR_SHA256",
      "accepted_index": 1,
      "rois": {
        "Total": { "G": 0, "XG": 0, "YG": 0, "ZG": 0, "ONE": 0 }
      }
    }
  ]
}
```

以上零值只是JSON接口示意，**禁止作为实际测量提交**。真实数据必须包含reference里所有ROI、clock里所有帧，完整原生字段和真实数值；上游提取归档/退出的独立验证由原唯一pipeline完成。

```powershell
python -B experiments/dram-see-v4/continuous/proton/source_compare.py --reference local_runtime/dram-see-v4/continuous/proton/ACTUAL_CASE/reference.json --clock local_runtime/dram-see-v4/continuous/proton/ACTUAL_CASE/clock.json --measurements local_runtime/dram-see-v4/continuous/proton/ACTUAL_CASE/measurements.json --output local_runtime/dram-see-v4/continuous/proton/ACTUAL_CASE/comparison.json
```

比较使用真实dt和右端BE平均率，换算因子为 `1e-12 × 1.602176634e-19 × 1e15`；保存全程scalar电荷、场窗口scalar/TDR/参考三方比较、峰值归一化波形、ROI份额、空间/时间质心和分区闭合。质心检查同时覆盖实测活跃帧和参考活跃帧，不能让丢失峰值通过自我排除逃过检查。原生提取器证明仍有独立 `upstream_extraction_provenance_verified=false`，由主流程集成后处理，不通过手写true授予资格。

## 此次实际验证与边界

新增13项检查覆盖独立x方向圆帽积分对照、解析体积/深部Gaussian、表面点截断、斜段时空分裂可加性、点/晚到保留、ROI与区间闭合、加密差值、真实BE token/回退、缺帧/改动重复时间拒绝、单位/哈希/负源拒绝、标量与缺峰失败。只复验了失败/新增检查，没有重跑旧11项测试。

初次9项有3项因体积函数asin端点浮点超界失败；改为与物理区间一致的[-1,1]端点保护后，仅复验3项，其中体积误差1.9355e-11µm³仍未过原1e-11断言。加严积分后该项通过，原断言未改。原失败日志保留在runtime。

新时钟实现从原R10归档读取到957个实际BE接受区间、69张原TDR；这只是新时钟解析器对既有失败档的读取证明，R10的414项PMI时钟失败没有改变。最新原档索引为 `r10-original-clock-index-r2.json`。

CLI的明确合成检查为 `source-reference-cli-fixture-r1/UNIT_FIXTURE_NOT_NATIVE_*`：分配0.6fC，有限Si全时间0.3116150051375239fC，非硅损失0.28838499486187213fC，25ns窗外晚到质量0.2fC；加密最大电荷差约1.9954e-11fC，区间闭合残差0。此例不包含新的Geant4或TCAD结果，不可用于训练或科研验收。

尚未取得当前BCAT质子事件、当前器件源场、真实字段提取、双载流子响应与数值收敛。上述实现提供可执行的独立参考和比较模块，不能据离线成功宣布源/器件资格。
