# 梯度网格 r3 输入

```powershell
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request experiments/dram-see-v4/continuous/device/request-d3-gradient-r3-main.json --run-id NEW_RUN_ID --output local_runtime/dram-see-v4/continuous/device/gradient-mesh-r3-r1/projects/NEW_RUN_ID
```

命令只冻结一个新输入，不调度原生。请求明确选择 `dram-see-v4-gradient-mesh-r3`。旧 r1/r2 策略与二维路径保留；未知策略拒绝。gate=70/80/90、SN=82/87/92 沿用既有受控参数，默认示例为 S2=80/87，任何最终留出身份不由本层重标。

新策略只替换整个 `GateOxide` 的等向体积细化与 `InterfacesActive` 的标量界面细化。前 11 个方向窗口族从实际几何推导；原接触、掺杂 x/z、全 y 混合带、源柱和远界面原样保留。假设、具体尺寸和未验证项见 [实现前声明](MESH-GRADIENT-R3-ASSUMPTIONS.md)。h/2 对全部尺寸同比减半，不移动物理窗口。

仅 r3 的 mesh block 在 `sdedr:write-cmd-file` 前调用同版手册 p791 的 `(sdesnmesh:delaunizer "maxPoints" 2147483647)`。它是有限原生算法参数；没有更改默认 boxmethod 或其他质量条件，不等于无限资源或质量通过。原 runner 无需新步骤或改写 cell.cmd；首次真实 SDE 后应由主调度者核对原 `cell.cmd` 的实际 Delaunizer 输出。没有新增 runner/operation、SSH 或原生调用。

`mesh_policy_v3.py`、`mesh-policy-gradient-r3.json` 和假设文件独立保存。每个冻结包继续保存三个通用 mesh-policy 文件及各自原 SHA；A0 必须从实际成功 producer 的原归档继承真实 mesh/geometry/policy。当前声明检查不制造成功 producer 或 A0 资格。

新定向检查覆盖精确 11 族与保留规则、九组参数的物理和 148 项测量不变、h/2、SDE 文档接口位置、旧 r1/r2 与 D2 兼容、原文件保留、两 bit A0 policy 继承及假原生拒绝。首轮 6 项通过、1 项因未区分几何合同 SHA 注释更新而失败；原失败源码/日志保留，精确核对唯一注释差异后只重跑该项通过。没有重跑旧套件。
