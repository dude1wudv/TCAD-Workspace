# 强子数据就绪核查

记录时间：2026-10-13 UTC（本地2026-10-12）。结论：**首选 QGSP_BIC + EM Opt4 尚未满足运行条件，质子输运未启动；本轮未安装任何数据或软件。**

实际 `geant4-config --version` 输出10.7.3。现有探针在三个项目相关目录中未找到 PhotonEvaporation5.7 和 G4PARTICLEXS3.1.1，首选候选的核退激和相关强子截面数据尚无可用证据。当前结论限于项目配置和已检查路径，不等于证明整台主机没有安装，也没有实际执行强子初始化。TCAD直接源探针不依赖这些包。

| 数据 | 适用条件 | 本轮观察和判断 |
|---|---|---|
| PhotonEvaporation5.7 / G4LEVELGAMMADATA | 核能级、核退激；不专属于HP | 已检查三处未见，预检shell变量未设；首选候选未就绪 |
| G4PARTICLEXS3.1.1 / G4PARTICLEXSDATA | 相关非HP强子截面，包括次级中子的非弹性和俘获 | 已检查三处未见，变量未设；首选候选未就绪 |
| G4NDL4.6 / G4NEUTRONHPDATA | 低能中子HP分支 | 三处未见；不是普通QGSP_BIC的共同必需项，HP分支须另行补齐 |
| 带电粒子ParticleHP/TENDL数据 | AllHP启用质子等ParticleHP描述 | 未确认数据和同位素覆盖；不是普通BIC分支的共同前提 |
| RadioactiveDecay5.6 / G4RADIOACTIVEDATA | 显式启用放射性衰变构造器/过程 | 三处未见；不能据此笼统否定所有强子模型，不能与一般粒子衰变混同 |
| G4EMLOW7.13、G4ENSDFSTATE2.3 | 电磁及核素属性数据 | 有目录和旧项目环境脚本证据；仅有目录不代表内容完整。预检shell未加载变量不等于包缺失 |

检查路径：

1. `<SIM_USER_HOME>/research-training/dram-see-v1/software/data`
2. `<SIM_USER_HOME>/research-training/dram-see-v1/software/data-complete`
3. `<SIM_USER_HOME>/research-training/dram-see-v1/software/Geant4-10.7.3-Linux/share/Geant4-10.7.3/data`

`before-a4`还在项目`software`下以`maxdepth 4`扫描指定目录名，并读取当时shell中的8个数据环境变量。未做全主机扫描、数据文件内容完整性校验或核模型初始化。CMake中的CERN打包路径只是声明，不能证明本机数据可用。

证据入口：

- [就绪摘要](results/readiness.json)和[阻塞/失败清单](results/failures.json)。摘要中的四项缺失是合并清单，依赖适用条件以本表为准。
- [三路径与参数探针](../../../local_runtime/dram-see-v4/preflight/hadronic-and-parameters/probe.sh)、[原始输出](../../../local_runtime/dram-see-v4/preflight/hadronic-and-parameters/stdout.txt)。
- [A4前只读探针](../../../local_runtime/dram-see-v4/preflight/before-a4/probe.sh)、[原始输出](../../../local_runtime/dram-see-v4/preflight/before-a4/stdout.txt)。
- [旧环境脚本](../../../local_runtime/dram-see-v1/geant4-env.sh)只显式配置EMLOW和ENSDF。
- [10.7.3既有安装包](../../../local_runtime/dram-see-v1/downloads/geant4-10.7.3-centos7.tar.gz)内`include/Geant4/G4NuclearLevelData.hh`、`G4NeutronInelasticXS.hh`、`G4NeutronCaptureXS.hh`分别提供核能级和截面数据依赖证据；`G4ParticleHPInelasticData.hh`、`G4RadioactiveDecayPhysics.hh`用于区分条件依赖。只在内存中读取，没有解压、编译或执行。
- [输运设计](../stage1/transport-design.md)保留候选物理列表、EM模型和cut的一致性要求。

下一步先确认是否存在其他可用安装路径；若确需补包，在取得安装授权后按10.7.3匹配版本配置和核验。之后进行单独的初始化/过程清单检查，再进入已设计的少量初级事件格式探针。本轮不自动替换物理列表或缩减过程来绕过缺失数据。
