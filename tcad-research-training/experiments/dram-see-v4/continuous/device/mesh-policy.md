# 显式三维网格策略

准备梯度候选使用单独的 request-r3；原 request-r1 继续产生旧 S2 网格，request-r2 仍是 α v2 瞬态入口。

```powershell
python -B experiments/dram-see-v4/continuous/device/prepare_case.py --request experiments/dram-see-v4/continuous/device/request-d3-gradient-main.json --run-id NEW_RUN_ID
```

此命令只生成一个新目录，不提交原生作业。`mesh_policy` 必须是 `dram-see-v4-gradient-mesh-r1`，dimension 必须为 3；variant 只允许 main 或 mesh。mesh 使所有 max/min/界面首步同比减半，分区物理边界不变。2D 不接受新策略。

[实现前假设](MESH-GRADIENT-R1-ASSUMPTIONS.md)说明原数值假设改变、r3 真实 OOM 和 r5 掺杂误差依据。`mesh-policy-gradient-r1.json` 固定定义，`mesh_policy.py` 实例化为 `mesh-policy.json`；项目保存定义和假设原字节，并在 geometry-contract、measurement-plan、controlled-parameters、role-contract 和 provenance 中绑定。实际 SDE 网格块另有 SHA，使用已运行过的 SDE 命令形式。

策略保留物理 model、DC deck、物理四文件及原测量坐标/期望/容差。原 model.numerics 不改；实际界面、掺杂与源柱分区全部由独立 mesh policy 声明。生成成功或资源减少不能证明源场、器件电学或 h/2 收敛通过。

A0 请求仍使用原瞬态入口，只提供真实成功 D3 原目录。preparer 从该原档复制精确 policy、定义、假设和实际网格，不按当前生成器重建。旧 producer 没有独立 policy 时继续按原档语义核验，不强加新 policy；失败或缺失的原 D3 不能成为 A0 网格来源。同一信号与 A0 必须使用相同原 policy 字节和真实网格。
