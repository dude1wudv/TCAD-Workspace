# A1空间测量链诊断

此目录只诊断已完成结果，不修改builder、source contract、审计阈值或原始工程，不执行SDevice。原始A1为`20261013T115652Z-v4-source-interface-r2-a1-b1-base-9aee36a9`。

已知直接证据：原日志识别`HeavyIon("Ion1")`、方向`(0,1,0)`、StartPoint`(.425,.3,0)µm`、Length`.6µm`、LET`1.6667e-3pC/µm`，并列出`HeavyIonGeneration`场及九个`Integral(Name=...SemiconductorWindow)`；没有相关warning。日志确认积分长度单位µm。原PLT的九个Window积分及全域质心均为0，正式5%总电荷门槛失败。电路扰动不能替代源项验收。

本机SDevice UG p181规定Window角点单位µm及1D/2D/3D窗口；p184说明二维积分单位`µm²·cm⁻³`。这些说明不支持擅自改坐标倍率。也没有明确共享边界控制体权重。TDR头是Ogawa压缩容器，不是可直接当CSV或HDF5解析的数据。

## 只读原档的原生SVisual操作

主Agent通过既有operation共享锁，将五个`gfield_*_access_des.tdr`复制到新的独立诊断目录，核对复制件与原始归档SHA256相同，再上传本目录`inspect_tdr.tcl`。脚本仅使用相对文件名，只读复制件，输出在这个独立cwd中。包装脚本应保留TDR运行前后SHA256、SVisual版本、命令、真实退出码和stdout/stderr；不修改原run。以下SVisual绝对路径来自主Agent已核实安装：

```bash
/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script inspect_tdr.tcl
```

参数依据本机W-2024.09 SVisual UG pp24–25。`-b`为纯批处理，不需要GUI、Mesa图形输出或虚拟X桌面。原生字段列表用p319的`list_fields`，材料列表用p322的`list_materials`，积分及domain面积用pp309–310的`integrate_field`，峰值/坐标用p227的`calculate_field_value`。常数1场按p237的`create_field -function "1"`仅在内存创建，积分独立验证硅域/窗口面积单位；不保存或改写TDR。输出文件独占创建。

预期产物：

- `field-inventory.csv`：五个TDR中的全部原生字段名及材料名。
- `field-measurements.csv`：常数1的无Window硅域和九个窗口积分；每个实际HeavyIonGeneration字段的全结构无Window积分、硅材料无Window积分、同冻结九个Window的积分及几何域面积、峰值/坐标。另有扩大二维Window和显式z域诊断，都是诊断对照，不替代原ROI或新门槛。
- `diagnostic-status.txt`：脚本完成及必需命令错误数。错误单独记录为`ERROR`，不转成零。原生API失败时继续收集其他证据，最后退出2；无必需命令错误退出0也只表示诊断收集成功。

包装器必须同时核对真实退出0、stdout最后的`R2_NATIVE_TDR_DIAGNOSTIC_COMPLETED mandatory_errors=0`、状态文件及完整CSV。Tcl中途异常可能没有正确退出码，**无正常结束sentinel即失败**，不得只依据进程退出0。脚本收集到必需API错误则打印FAILED sentinel并退出2。

表中时间由冻结快照请求标注为`declared_time_s`，不冒称已独立解码TDR内部时间。必须用原始run输入/文件哈希和实际输出日志关联。五个快照不能重建0.5ps完整时间曲线或替代4ns源项积分。

## 结果判别及后续依赖

1. 若TDR没有实际生成场，先定位场输出/命名，不补理论值。
2. 若无Window硅域积分非零，而同窗口积分为零且返回域面积零，优先定位窗口选域/坐标或API二维语义。不能改源电荷弥补。
3. 若TDR无Window和各ROI均有合理非零积分，而SDevice PLT皆零，问题更集中在SDevice CurrentPlot测量路径。保留PLT失败，用TDR描述有限快照证据，不宣称整条生成曲线通过。
4. 若TDR生成场及无Window积分也为零，需继续检查源时刻、实际字段分量及保存的解；不从节点电压反推生成量。

只读SVisual不消耗SDevice19次预算。如果最终必须补充或修正CurrentPlot，需要主Agent先冻结独立修订；重求解A1每次消耗**额外1次实际TCAD尝试**，不会恢复已使用预算。先用一个受控非零案例同时保存历史无Window总积分和待修正ROI/质心，测量链通过后再决定剩余清单，不能自动扩批。原始r2 A1失败不覆盖，门槛仍为总量5%、空间/时间预注册门槛。
