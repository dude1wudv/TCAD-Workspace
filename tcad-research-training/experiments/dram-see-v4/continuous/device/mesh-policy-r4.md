# 梯度网格 r4 输入

```powershell
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request experiments/dram-see-v4/continuous/device/request-d3-gradient-r4-main.json --run-id NEW_RUN_ID --output local_runtime/dram-see-v4/continuous/device/gradient-mesh-r4-r1/projects/NEW_RUN_ID
```

只准备一个新输入，不调度原生。显式策略 `dram-see-v4-gradient-mesh-r4` 由独立 `mesh_policy_v4.py`、定义与假设文件生成；旧 r1/r2/r3 文件保留。`variant=mesh` 生成对应 h/2 producer 声明，全部新旧尺寸减半，物理窗口不动。

本版只将三段原 4w α 柱的横向 max 改为 10 nm，并加入同原轴心 2w 核心保持 5 nm。源轴、w 和原 4w 边界互相核对，核心不另设中心。原 z 分区/5–20–5 nm、其它 r3 规则、Delaunizer 请求、物理四文件、求解器和全部测量判据保留。完整依据和未验证项见 [实现前声明](MESH-GRADIENT-R4-ASSUMPTIONS.md)。

新 policy 分别保存 `delaunizer.explicit_parameters.maxPoints=2147483647` 与 `previous_native_delaunizer_serialization`：后者是 r6 已实际观察的 `2.14748e+09`（2147480000，差 −3647），精确匹配为 false，而且不是当前新运行测量。没有修写原 SDE 输出或旧 r3。

5 项新定向检查已 exit 0：三段外框/核心与保留规则、源几何派生及错配拒绝、全尺寸 h/2、物理/148 测量/旧 r3 原档兼容、两 bit A0 在 main/mesh 的 policy 继承。没有重跑旧套件。数学 fixture 不提供 native 成功资格；真实 A0 仍须原成功 D3 archive。

该策略是当前正入射 α 柱候选，未证明 30 nm 质子核任意次级或斜射源的覆盖。未裁尾或重归一，最终留出不参与选择；仍须真实网格/场/ROI/时钟/响应和 h/2 结果判定。
