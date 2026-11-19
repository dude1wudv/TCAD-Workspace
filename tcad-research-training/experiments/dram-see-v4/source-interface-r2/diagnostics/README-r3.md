# r3：常数场、保存状态和时间核核对

`inspect_tdr_r3.tcl`保留r2的显式plot/geom上下文，将常数1改成`0*<HeavyIonGeneration>+1`。本机SVisual UG p426说明新field必须由已有field参加表达式；纯数字`1`在本机实际返回“Formula result is not a field”，不能据此填0。前两次脚本、结果及失败均保留。

命令仍为纯后处理：

```bash
/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script inspect_tdr_r3.tcl
```

除了已有CSV，增加`tdr-state-metadata.csv`：按UG pp292、294、327调用`list_tdr_states`、`get_plot_prop -tdr_state/-tdr_state_index/-title`，原样记录实际元数据。字段中的`declared_time_s`仍仅为请求时间；如果原生state没有时间标签，**直接解码TDR内部时间仍未完成**，不能用名称、索引或理论拟合代替。正常sentinel仍为`R2_NATIVE_TDR_DIAGNOSTIC_COMPLETED mandatory_errors=0`，status增加`script_revision=3`。

## 已确认的公式误读

已将本机`local_runtime/dram-see-v1/sdevice_ug.pdf`第813页实际渲染并查看公式(810)像素。准确表达式为：

\[
T(t)=\frac{2\exp[-((t-t_0)/(\sqrt{2}s_{hi}))^2]}
{\sqrt{2}s_{hi}\sqrt{\pi}\,[1+\mathrm{erf}(t_0/(\sqrt{2}s_{hi}))]}.
\]

因此`t0 >> s_hi`时标准差为`s_hi`，不是`√2*s_hi`。r2契约/解析oracle中的`2*s_hi`分母是此前误读；TCAD deck实际仍为`s_hi=2ps`，没有改变求解器源参数。两种公式均可归一化为1，不能靠总积分相等发现时间宽度错误。该发现需要记录新契约修订，不能静默改掉历史oracle或将旧结果改称通过。

原图仅保存在受忽略的`local_runtime/dram-see-v4/source-interface-r2/audit-dev/tdr-diagnostic-r3/sdevice-page813.png`，不把商业文档副本加入研究源码。

## 瞬时定义与实际保存值必须区分

SDevice UG p812文字将`HeavyIonGeneration`称作instant generation rate，p813公式描述连续时间核；已查辐射章节及CurrentPlot章节，**没有找到明确说明该输出会按BE步平均的文字**。不能把实测吻合升格成文档保证。

另一方面，A1原始日志在五次写TDR前都有成功BE步终点，原始PLT有对应接受时刻：

| TDR | 前一步起点/s（PLT） | 已接受终点/s（PLT） | 写TDR日志行 |
|---|---:|---:|---:|
| gfield0 | 9.94758283899995e-10 | 9.95e-10 | 7095 |
| gfield1 | 9.99499999999999e-10 | 9.99999999999999e-10 | 7407 |
| gfield2 | 1.0045e-9 | 1.005e-9 | 7714 |
| gfield3 | 1.0095e-9 | 1.01e-9 | 8012 |
| gfield4 | 1.0145e-9 | 1.015e-9 | 8310 |

未拟合`s_hi`、`t0`、时间偏移；将五个实际TDR无Window硅域积分除以gfield1，仅作形状诊断，所得比值与上述各步的正确核平均值`integral(T dt)/dt`吻合，最大相对残差约`3.5e-12`。用`erfc`差计算尾部，避免`erf`近1相减丢精度。相比之下，正确瞬时核在±5ps比值均为0.0439369，而实测分别为0.0382295、0.0609364；旧错误oracle给出0.209611。这是**强烈支持步平均解释的观察**，不是新的物理验收，更不是用理论值补测量。完整哈希、保存日志行及比值在`audit-dev/tdr-diagnostic-r3/saved-step-time-shape-diagnostic-erfc.json`。

该差异意味着时间波形oracle和时间积分规则都需独立复核：若后续证明CurrentPlot也输出本步平均量，应用每步平均核比较，并用`sum(G_bar*dt)`核算电荷；同时保留旧梯形积分作历史诊断。不能不验证就假设TDR与CurrentPlot所有路径相同。

## 空间门槛仍未通过

原生SVisual r2已观察到峰时硅域无Window和Total窗口积分相同、面积约1.02000006914µm²；HI场非零。但Center/Total约0.783205，解析`erf(1)`约0.842701，差约0.0595，超过预冻结0.05门槛。应保留为实际空间差异，可能涉及网格对窄Gaussian的表示/场输出积分离散；不能只修PLT就报通过。

SVisual对保存的节点场和单元几何做后处理；SDevice求解/CurrentPlot的离散权重是另一条测量链。已读SVisual UG pp160–162、309–310说明支持的单元与积分域，但未给出足以证明它等于SDevice控制体求和的权重算法。因此不能将两者直接互换，亦不能把0.0595差异当作已定位的具体权重bug。需要在同一完整解上对照两条路径，保留原ROI与阈值。

## 下一次SDevice的最小测量修复方案（建议，尚未执行）

先完成r3后处理与上述证据审阅。若仍需求解，先冻结独立测量修订，只跑一个非零A1作为测量链诊断，不扩整个批次：

1. 恢复历史已实际成功的无Window `HeavyIonGeneration(Integrate(Semiconductor))`作独立总量锚点；同时保留现有具名Window输出，不能用后处理替换其零值。
2. 增加本机UG pp186–191明确支持的Tcl CurrentPlot：`Formula="set value [tcl_cp_ReadScalar HeavyIonGeneration]"`；分别使用`Operation="Integrate Semiconductor IntegrationUnit=um"`和`Operation="Integrate Semiconductor Window=[(...)(...)] IntegrationUnit=um"`，显式独立Dataset名。
3. 同时加入`Formula="set value 1"`的无Window及ROI积分验证求解内域面积；Tcl公式数值输出与SVisual新field是不同接口，不能复用后者的纯数字限制。用Finish记录结果中的积分/质心，按p191例子绑定实际曲线时刻/行。先少量代表Total、Left、Center诊断，不把未输出其余ROI称为正式空间通过。
4. 对照无Window锚点、现有Window、Tcl Window、常数面积及TDR原生快照。若只有Window路径零，定位选域；若具名/未具名或全局/实例上下文不同，定位输出绑定。全部使用同源、同器件、同网格和源时间参数，不为修复测量改动电荷、半径或阈值。
5. 按正确公式和被证实的输出时间语义建立修订oracle；对TDR和CurrentPlot分别验真。空间Center差仍须同原门槛核查，再决定是否进入已计划的网格细化。

当前2/19次已使用；上述一次非零诊断求解会变成3/19，剩16次，失败也计数。是否替换后续工况或在不足时停下由主Agent决定；本目录不调度、不增加预算、不覆盖旧输入。
