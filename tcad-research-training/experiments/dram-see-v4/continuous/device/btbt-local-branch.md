# 代表单元的局部 BTBT 分支

当前分支采用 `Band2Band(Model=Hurkx DensityCorrection=None)`，BTBT 仍参与 Poisson / Electron / Hole 的自洽求解，不使用 postprocessing。假设标识为 `dram-see-v4-physics-local-hurkx-r1`。它用于继续代表单元的 DC、写读及后续粒子耦合；不称为原 NonlocalPath 的等价替换或商业器件校准。

选择来自原生 r7 的外部资源事实：前五个工具真实退出均为 0，105 项几何检查全部通过；SDevice 读入 95993 点后，在迭代前因 `sdevice-pathsearchtun` / `SK_sdevice-pathsearchtun_all` 不存在而退出 255，FlexNet 为 `-5,234`。没有改许可文件、许可环境、工具二进制或许可检查。局部模型的原生可用性与收敛仍由新作业真实退出证明。

采用的显式参数为：

| 参数 | 数值 | 单位 |
|---|---:|---|
| Agen / Arec | 4e14 | cm^-3 s^-1 |
| Bgen / Brec | 1.9e7 | V/cm |
| Pgen / Prec | 2.5 | 1 |
| alpha | 0 | 1 |
| dDist | 0 | cm |
| dPot | 0 | V |
| MinField | 0 | V/cm |

同版 SDevice W-2024.09 手册 p553 给出该模型选择语法，pp556–557 给出上述 Hurkx A/B/P 和 alpha 示例。原安装 `Silicon.par` 的第一条非局部路径为 Apath1=4e14、Bpath1=1.9e7、Ppath1=0.037 eV；p561 说明声子辅助均匀场极限使用指数 2.5。这里只映射该参考极限的参数尺度：Fermi 占据、OldSlotboom 带隙变窄、实际空间场分布和界面会使完整结果不同，不能由系数一致推导实际 DC 或瞬态电荷一致。

没有直接采用安装卡的默认 Hurkx 系数，因为它们实际为 A=3.5e21、B=2.25e7、P=2，属于另一组参考参数。也没有使用 E1/E2 作基线：手册 p558 指出这些简单模型在平衡态也可能给出非零产生率，可能污染保持漏电和读写基线。当前 alpha=0 保留生成/复合的平衡因子。原 Fermi、OldSlotboom、mobility、SRH、Auger、温度和偏压均不变。

局部模型不计算隧穿路径积分，不在路径两端分别产生电子与空穴，也不保留 NonlocalPath 的界面反射机制。手册 pp554–555 特别说明局部场在绝缘层邻域或快速变化处可能错误估计隧穿。dDist/dPot/MinField 均明确保留安装 local 默认 0，未为了通过漏电判据调节；因此埋栅角部的 GIDL、关态漏电、保持状态和收集电荷仍有未量化模型偏差，其方向也不能预称保守。

后续模型敏感性应保持同一真实网格、几何、掺杂、偏压、写读时间线和源电荷归一化，对比已声明的局部模型分支（例如 modifiedHurkx）及有文档依据的局部界面/电势抑制假设。观察平衡净产生、两条 Id–Vg 的关态/GIDL 区、保持漏电和粒子后的电荷；所有不利差异保留。E1/E2 如用于额外结构误差观察，其平衡态缺陷须单独标记，不能充当可靠上下界。最终留出不参与这些选择或调优；缺许可的 NonlocalPath 仍是未完成的模型对照，不能以局部变体冒名替代。

`physics_patch.py` 一致更新 D2、D3、A0-b0、A0-b1 的新副本，安装 Silicon/Oxide 卡和旧冻结包不动。`physics-manifest.json`、`model.proposed.json` 和 provenance 共同记录新假设、原始失败、参考参数和未校准边界。D3→A0 的数据桥还要求 physics.par、physics manifest 和两张安装卡逐字相同，避免把不同物理假设的 DC 和写读混为一条基线。原科学判据、原探针和数值容差保持。

本地文档依据为 `local_runtime/dram-see-v1/sdevice_ug.pdf`，私有页面提取保留在 `local_runtime/dram-see-v4/continuous/device/btbt-license-diagnostic/`；不把厂商手册或 MaterialDB 内容重新发布。新增检查仅验证参数映射、四角色一致传播、非 BTBT 输入不变和异常参考拒绝；日志 `test-physics-mapping-r1.log` 记录 3 项通过，不代表原生许可或科学验证。
