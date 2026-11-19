# BCAT全事件适配与二维PMI候选：实现前决定

1. 已编译基线为原 `cgoal-bcat-build-20261017t043911z`。只读它的实际原operation/归档/二进制/源文件/geometry/header；不生成替代receipt。未来event operation必须是原v2 `COLLECTED_PENDING_AUDIT`、实际task/remote/collection退出0、collection_verified及归档成员字节一致。断连SSH原码保留，不能拿它伪造远端退出。

2. 当前原请求生成器 `continuous/proton/prepare.py::transport_run` 没有request schema字段；新adapter严格匹配其现有字段、二进制来源、identity坐标与实际元数据。CSV列名/顺序从已编译的BCAT C++原字节提取；units必须等于实际输出的um/ns/MeV/eplus/unit_vector，不由adapter补写。拒绝旧planar geometry、坐标置换、缺列/缺步/缺birth/重复event与不完整分母。只接开发域，保留原最终组合保护。

3. 每个request的所有primary event都保留并分别重建，包括零Si/低沉积、点源和晚源。原始event/track/parent/step、材料、birth token、坐标、y和时间保持完整；不按响应或核事件筛选。分母和原始材料能量表独立重算。当前无真实BCAT event，因此只能检查拒绝分支与纯格式fixture，不能用历史planar通过来声称BCAT适配取得真实资格。

4. 一般投影为 `G2 ∝ ∫du Y_strip(u) gx(x−x(u)) gz(z−z(u)) T(t−t(u))`。当dt不为0时，时间与保留坐标相关，一般不能拆成单个HeavyIon的空间LET乘公共Gaussian时间波形。dy=0也不能解除dt造成的关联。若dt=0，空间可以化为沿投影方向的加权Gaussian卷积LET；有限LUT/截断尾仍是近似，不自动获得精确表示。沿y移动而x/z不动的dt非零步仍可能有非Gaussian时间分布。

5. 本轮不制作无法保证一般适用性的单HeavyIon替代。新增显式二维联合u积分PMI源码候选，复用R12的`PMI_OpticalQuantumYield` ABI和原source表加载器/数值节点，以解析erf积分y与实际BE区间时间。保留physical xyz原表；原生X/Y对应physical x/z，native第三坐标须为0。G2系数是 `Q_C/e * 1e12/(pi*w_um²*W_um*actual_dt_s)`，不是原3D归一常数，也不是1um参考厚度。

6. `ReadTime/ReadTransientStepSize/ReadTransientStepType/ReadRegionMaterial`只读真实API。未定义step type沿用原初始化零源语义并记录原值；不填预期BE，不以已知输入时间替代回调时间。BE必须dt>0且时钟有效，回退/重试每次无状态重算。仅Silicon得到源；读到其他半导体或非零第三坐标报错，不悄用3D路径。

7. 声明的完整电学窗口与实际BE区间取交集，最后仍除实际dt；不将窗内质量重新归一。源窗审计窗口不能当成电学总窗口裁尾。晚沉积仍由原投影账标明需时序处理。候选输入只可绑定已重算的全部BCAT事件和实际D2几何/宽度，不能用格式fixture作为原生输入。

8. 量子产额载体沿用R12 `eta_G=G2/Nref`、`Nref=1e35 cm^-3 s^-1`。这只是表示基；APD/光学基场的实际量、单位和tag、真实BE callback更新、OpticalGeneration是否等于G2、电子/空穴两方程联立、回退语义全部未验证。复用ABI不等于修复这些问题。不会伪造APD文件或完成的TCAD physics deck；仅交源码、编译输入和必要的真实验证合同。

9. 本轮不编译、不SSH、不调度。新的编译task复用原已运行R12的cmi/GCC/runtime hash设置，随后由唯一主代理通过原operation执行。standalone/context/oracle属于数学/编译检查，不是原生BE或双载流子证据。冻结projection2d/kernel.py及其他既有文件一字节不改。
