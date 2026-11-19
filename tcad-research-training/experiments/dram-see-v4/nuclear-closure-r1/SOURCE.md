# 有限步源核与原生 PMI 接口

本模块只建立新合同的源映射；旧二维失败及所有原合同保持原样。空间宽度 `w=0.03 um`、时间标准差 `sigma=2e-12 s` 是本次映射假设，不是校准值。所有原始步的端点和相对延迟保持不变。

对一条原始步，令 `r(u)=r0+u(r1-r0)`、`tau(u)=t0+u(t1-t0)`，`0<=u<=1`。定义

```text
S(x,u) = exp(-|x-r(u)|^2/w^2)/(pi^(3/2) w^3)
T(t,u) = exp(-(t-tau(u))^2/(2 sigma^2))/(sqrt(2 pi) sigma)
G(x,t) = (q_fC*1e-15/e_C)*1e12 * integral_0^1 S(x,u) T(t,u) du
```

`x,r,w` 用微米，`t,tau,sigma` 用秒。`1e12` 将每立方微米换成每立方厘米；`G` 单位为 `cm^-3 s^-1`。空间零弦长仍按点核处理，即使其原始时间区间非零。原始记录的输运长度与端点弦长分别保留，不据此人为造短线。`charge_fC` 由 Si 正电离沉积按 `3.6 eV/pair` 与 `e_C=1.602176634e-19 C` 转换；不增加次级出生动能。

`generation` 用四维投影后的一维高斯解析积分；`integrated` 独立计算各空间边界和时间窗的高斯 CDF 与一阶矩，再对 `u` 做自适应 8/16 点 Gauss-Legendre 积分。它不采样 `generation`。边界和时间窗的窄过渡显式分段，失败报错，不重新归一化。返回的误差估计是两阶求积差，不能视为严格数学误差上界；合同中的独立数值交叉检查仍需要执行。

原生求解采用明确的 BE 区间平均源离散：`ReadTime()` 返回 `t`，`ReadTransientStepSize()` 返回实际 `dt`，并使用

```text
G_BE(x; t,dt) = integral_(t-dt)^t G(x,s) ds / dt
R_PMI = -G_BE
```

时间高斯的区间质量用 CDF 计算，空间与原步时间的相关性仍保留。步被回退、拆分后，各区间源质量可加；没有把求解器时间步当作 `sigma`，也没有压缩迟发事件。`Compute_r` 的首个温度参数不参与时间读取。所有对温度、载流子浓度、本征浓度及电场的偏导为零。deck 继续独立启用 SRH/Auger。

PMI 的 `PMI_UndefStepType=0` 表示静态/初始化约定，源显式为零；BE 的初始 `t=dt=0` 也为零。其他非正或无效 BE 步、非 BE 瞬态模式均报错，不替换为虚构步长。原生资格运行必须核对真实接受点的 `t/dt/type`，以及可能发生的回退行为；本地 Python 测试不能证明原生访问器的运行语义。

## 稳定接口

- `validate_source(source)` 校验精确 schema、当前几何绑定、唯一 UID、有限数据、正电荷及固定宽度。
- `canonical_source(source)` 返回规范副本；按物理数值列、再按 UID 排序。输入行顺序不影响 JSON 或原生表字节。
- `generation(source, xyz_um, time_s)` 返回瞬时 `cm^-3 s^-1`。
- `average_generation(source, xyz_um, [lo_s,hi_s])` 返回正时间区间平均 `cm^-3 s^-1`。
- `integrated(source, [[xmin,ymin,zmin],[xmax,ymax,zmax]], [lo_s,hi_s])` 返回 `charge_fC`、`spatial_first_moment_fC_um[3]`、`time_first_moment_fC_s`、`centroid_um`、`time_centroid_s`、逐步电荷及误差估计。允许无穷边界用于总量与分区检查；零电荷的质心为 `None`。
- `native_bytes(source)` 返回 ASCII/LF 数据；`write_native(source,path)` 独占写入，拒绝覆盖。
- `event_source.from_selected(selection_path)` 只读，返回 `{'source': ..., 'ledger': ...}`；调用者负责持久化。它重新绑定 record/audit/raw CSV 的哈希和 10 项严格检查、原生成功退出、几何、完整选中事件、原生核出生链、窗内正电离见证与具体步 ID。原始 CSV 在转换前后复核。

源 JSON 精确顶层字段为 `schema='nuclear-closure-source-r1'`、`geometry_sha256`、`steps`、`provenance`。每步字段为 `uid,r0_um,r1_um,t0_s,t1_s,charge_fC,w_um,sigma_s,kind,provenance`；`kind` 为 `point` 或 `segment`。源包括选中事件所有正 Si 沉积，包含主粒子、电磁后代与晚沉积；见证筛选只使用原始时间，不使用高斯尾。

账本保留全部原始事件步，分别标记零电离与非 Si 沉积；列出源总电荷、原始窗内电离及互斥的“Si 内/外 × 时间窗内/外”四区间。有限高斯空间尾和晚源不会被丢弃或重新归一化。步/出生关系检查不是完整的核反应静质量与激发能守恒证明。

## 原生数据与编译约定

PMI 固定从求解工作目录读取 `sources.dat`，无动态脚本和自定义 Filename 参数。首行为 `NUCLEAR_CLOSURE_SOURCE_V1 <count>`；随后每行 11 个 `.17g` 数值：

```text
x0_um y0_um z0_um x1_um y1_um z1_um t0_s t1_s charge_fC w_um sigma_s
```

表不携带来源字符串；来源由绑定的 source JSON 与文件哈希保存。空表合法，代表 A0/zero 资格。

原生模型名 `pmi_nuclear_source`。主代理应将 `pmi_source.C` 原字节复制成编译输入 `pmi_nuclear_source.C`，通过既有 operation 桥及同版本环境执行：

```text
/usr/synopsys/sentaurus/W-2024.09/bin/cmi -O -v pmi_nuclear_source.C
```

预期产物为 `pmi_nuclear_source.so.linux64`。导出为 `new_PMI_Recombination` 与 `PMI_Recombination_ElectricField`；后者返回 0。`nm -D` 与 `ldd` 仅验证符号与库依赖，不能替代 SDevice 原生加载/符号/单位资格。

可在根代理的编译操作中用 `-DNUCLEAR_SOURCE_STANDALONE` 构建同源离线算术探针；它不依赖 PMI 头文件，不调用求解器，命令参数为 `sources.dat x_um y_um z_um lo_s hi_s`，输出同一 C++ BE 核平均值。Python 预期向量位于 runtime 的 `source-dev/native-oracle-vectors-r1/`。该模式验证 C++ 算术与输入解析，不证明原生 ABI。

原生场输出：`PMIRecombination=-G_BE`；`PMIUserField0=+G_BE`、`PMIUserField1=t(s)`、`PMIUserField2=dt(s)`、`PMIUserField3=step_type`。必须从真实接受步保存这些字段，并用对应实际 BE 区间的独立空间积分核验。

## ABI 依据与验证边界

只读检查了安装版本 `W-2024.09` 的 `lib/sdevice/include/PMIModels.h`：`ReadCoordinate` 第 764 行，`ReadTime` 第 797 行，随后为 `ReadTransientStepSize/Type`；`PMI_StepType` 第 480 行，BE 值为 3；`PMI_Recombination` 第 1698 行。官方例子是 `Applications_Library/GettingStarted/sdevice/pmi/pmi_recomb/pmi_recomb.C`。温度参数与运行时读取方法来自同版本声明，未复制厂商实现入仓库。

头文件 SHA256：`PMIModels.h=6ceb8b7df42801c970b48c07a89013a4b1278702ec5403e9427fcd8901bc1514`，`PMI.h=991ec9fb842f692342fca9c30193e9fc43cc77e26abc09f02ae970ad9c1876c8`。官方示例 SHA256：`d352564cac722152fb27790f78d5fe3fbcab6ae5916f76fc451567c9eae4e7ba`。读取原档在 `local_runtime/dram-see-v4/nuclear-closure-r1/source-dev/abi-readonly-r1` 至 `r6`。

`cmi` 参数通过其安装 ELF 的内置 usage 字符串只读核查，未运行该工具；证据为 `source-dev/cmi-readonly-r3` 与 `r4`。默认编译选项含 C++14。`r2` 曾将 ELF 头作为文本读取，SSH 结果已保存，但本地控制台编码失败；这不是编译或软件故障，也不作为参数依据。

本地定向测试覆盖归一化/单位、点源、相关有限段、分段等价、迟发窄窗、边界质量分配、BE 回退分区可加、规范排序、完整事件保留及来源反例。实际命令和结果见 `source-dev/python-tests-r1/receipt.json` 与日志。这里只执行了 Python 测试及只读头文件/命令用法检查；原生编译、离线 C++ 探针、原生加载与两次资格均留给主代理串行执行，未经其证据不得宣称 PMI 已验收。
