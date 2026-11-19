# 原生TDR后处理r2：显式建立plot/geom

首版实际后处理`r2-a1-tdr-diagnostic-r1`已完整保留：它加载了五个TDR并观察到真实`HeavyIonGeneration`字段和`Silicon`材料，但115个必需命令报错。错误集中在缺少有效plot/geom上下文，而不是物理积分为零：`create_field`报Invalid plot/dataset、`integrate_field`报reference resolving failed [geom]、极值命令要求`/plots/block=false`。这些API错误不能转写为测量零。

本机W-2024.09 UG p331的`load_file`只返回dataset名称；p239提供`create_plot -dataset <dataset>`创建对应二维/三维plot；p237允许`create_field -plot ... -geom ...`，pp227、309–310允许积分/极值命令明确指定plot和geom。r2先`load_file ... -alldata`，再`create_plot -dataset $data`，记录实际返回plot名称，后续测量统一指定`-plot $plot -geom $data`。不调用未文档化的`/plots/block`内部设置。此仓库旧`tests/pn-field-desktop/field.tcl`也采用已实际运行的dataset→create_plot→plot/geom链。

新脚本为`inspect_tdr_r2.tcl`，首版`inspect_tdr.tcl`不覆盖。root仍在新operation目录放置五个与原档哈希相同的TDR复制件，不改原run，不启动SDevice：

```bash
/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script inspect_tdr_r2.tcl
```

输出文件及正常stdout sentinel与首版相同：`field-inventory.csv`、`field-measurements.csv`、`diagnostic-status.txt`及`R2_NATIVE_TDR_DIAGNOSTIC_COMPLETED mandatory_errors=0`。status另写`script_revision=2`。正常sentinel仅在stdout/SVisual日志，包装器必须从`svisual.log`核对，并保留`svisual-exit-code.txt`真实进程码；status核查`mandatory_command_errors=0`和版本。缺sentinel或API错误均不得凭外层退出0认定完成。

常数1、面积、五快照、九ROI、生成场无Window积分和极值位置等测量保持原样。SVisual新上下文的实际适用性仍须本次后处理验证；本地只检查了Tcl完整性和CSV转义，未伪造原生执行成功。此次不改变SDevice源、冻结门槛或19次TCAD预算。
