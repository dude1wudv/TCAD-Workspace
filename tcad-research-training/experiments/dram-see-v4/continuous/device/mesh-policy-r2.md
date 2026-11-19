# 梯度网格 r2 输入

```powershell
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request experiments/dram-see-v4/continuous/device/request-d3-gradient-r2-main.json --run-id NEW_RUN_ID
```

命令只准备一个新输入，不调度原生。request-r3 的 `mesh_policy` 显式选择 `dram-see-v4-gradient-mesh-r2`。原 r1 请求和实现保持；固定 `mesh_policy_registry.py` 按各自版本分发，未知版本拒绝。

r2 仅将全 Junction 改成 x/y/z=20/20/5 nm，并加入 x±20 nm、全 y、z=0–250 nm 的连续 1/20/1 nm 混合带。其余 r1 分区逐项相同。实际依据、bad_alloc 与 OOM 的区别、未验证项见 [实现前声明](MESH-GRADIENT-R2-ASSUMPTIONS.md)。

`mesh_policy_v2.py`、`mesh-policy-gradient-r2.json` 和对应假设文件独立保存。项目内仍用三个通用归档名 `mesh-policy.json`、`mesh-policy-definition.json`、`mesh-policy-assumptions.md`，各自声明实际版本、原字节 SHA 与网格块 SHA。A0 从真实成功 D3 复制这些原文件和实际网格，不用当前定义覆盖旧 producer。

5 项新增定向检查覆盖新增区域、全部 h/2、r1 原字节重建与只读准入、物理/148条测量不变、当前版本 A0 继承。没有重跑旧套件或原生作业；声明构造通过不证明网格、源场、电学或内存需求已通过。
