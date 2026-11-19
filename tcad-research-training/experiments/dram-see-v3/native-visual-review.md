# v3 原生图件实际验收

2026-10-10 15:18 UTC，主代理逐一查看下列四张真实PNG。两个对象在执行前已由原full-r3计划选定，未按结果换图；当前训练科学门槛失败不妨碍读取这些已VERIFIED原档。

| 对象 | 原生导出 | 真实自有窗口 |
| --- | --- | --- |
| 0.18µm、存储1、无粒子物理参考 | [PNG](figures/native/20261010T103149Z-v3-physical-l018-b1-33b11a8f/final-field-native.png) | [PNG](figures/native/20261010T103149Z-v3-physical-l018-b1-33b11a8f/own-window.png) |
| 0.18µm、alpha/30°、seed202610311、存储1 | [PNG](figures/native/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/final-field-native.png) | [PNG](figures/native/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/own-window.png) |

两组均可见正确run ID、4ns信号支路标题、`Abs(ElectricField-V)`电场模量色标与`V*cm^-1`单位；坐标标题注明µm。显示为竖直X、水平Y；不是空图或默认掺杂图。窗口标量选择与色标一致，无无关私密窗口内容。可见色标最大值约1.7282×10⁶及1.82037×10⁶V/cm，分别使用各图实际色标，不据颜色直接比较场强。

现有取证器核验了原results.tar、最终TDR及加载前后远端TDR哈希、自有窗口进程的创建时钟/cwd、原生proof与文件哈希；操作退出0。主代理额外留下[视觉验收JSON及四图哈希](figures/native/visual-review.json)。原 `evidence.json` 的初始 `CAPTURED_PENDING_VISUAL_REVIEW` 记录保持原字节；自动阶段报告显示该捕获时状态，后续实际目视结论以本文件和验收JSON为准。

这两项是4ns最终电场图，不能代替瞬态读出、全主矩阵完成、Workbench Run按钮执行、真实器件校准、学生演示或教师验收。两项原生窗口保留打开；未关闭用户既有窗口，未新增solver。
