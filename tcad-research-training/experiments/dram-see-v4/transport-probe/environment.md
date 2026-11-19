# v4 Geant4 环境记录

环境标识：`geant4-10.7.3-v4@8fd8fd92`。规范化规格SHA-256：`8fd8fd9280d08d90e0b1c4914c5827307e1a01e02d43925d240f09a2c9ba7845`。规格见[environment-spec.json](environment-spec.json)，实际运行及边界见[report.md](report.md)。

- 原Geant410.7.3/GCC10.2.0复用；仅新增两个匹配数据包，原包、系统和v3未覆盖。
- 专用环境位于远端`dram-see-v4/software/environment.sh`，仅在本次命令子shell加载；不会全局修改旧项目的环境变量。
- 完整数据表初始化、实际H/E过程检查与22个预先指定的质子记录检查已通过；数据文件在运行前后逐项清单指纹一致。
- 初始化和格式probe经独立复核；余下10个运行因验证员额度不可用由主代理接管。当前环境就绪仅限选择的QGSP_BIC+Opt4与E臂；HP、AllHP、RadioactiveDecay、核次级物理见证、TCAD映射及物理校准不在此结论内。
- 复现必须使用新的冻结请求/attempt目录，已有成功请求拒绝重提。按README-transport.md使用同一程序；已有`init-h-r2`/`init-e-r1`等原目录不能再次执行。
- 已知问题：Windows校验清单必须写LF；可选CLI参数是`miss=0`或`miss=1`，不能只传0/1。两项原失败与修复详见[失败账本](results/failures.json)。
- 独立审计复现为只读命令：`python -B experiments/dram-see-v4/transport-probe/audit_transport.py init local_runtime/dram-see-v4/transport-probe/runs/init-h-r2`。events模式检查完成粒子run，不启动求解。
