# 小尺寸器件新增证据与校准边界

2026-10-12。完整调查记录：[source-audit.json](../../../local_runtime/dram-see-v4/study-20261012/device-literature/source-audit.json)。当前取得正文证据，未取得可供核验的曲线像素，未生成数字化点。

| 来源 | 新确认的内容 | 设计决定 |
|---|---|---|
| [Shin等，JKPS 43(5)，887–891，2003](https://www.researchgate.net/profile/Soon-Hong/publication/285712995_Data_Retention_Time_and_Electrical_Characteristics_of_Cell_Transistor_According_to_STI_Materials_in_90_nm_DRAM/links/5705b8ee08ae74a08e274f35/Data-Retention-Time-and-Electrical-Characteristics-of-Cell-Transistor-According-to-STI-Materials-in-90-nm-DRAM.pdf)，DOI 10.3938/jkps.43.887 | Fig8/11控制沟道注入剂量相同；Fig12控制Vth相同。 | 将STI分裂与保持比较分开设计，不能当作同一固定掺杂器件的共同校准目标。 |
| [Park等，Highly Manufacturable 90 nm DRAM Technology，IEDM 2002，819–822](https://www.researchgate.net/profile/Soon-Hong/publication/224739434_Highly_manufacturable_90_nm_DRAM_technology/links/5705b97308ae44d70ee34705/Highly-manufacturable-90-nm-DRAM-technology.pdf)，DOI 10.1109/IEDM.2002.1175963 | 正文给出平面单元，T形凸有源区与弯曲栅；存储电容23 fF/cell；高温下关态电流0.1 fA、亚阈值摆幅110 mV/dec。 | 作为结构/电路更完整的候选来源；数值尚缺原图中的温度、偏压、频率和归一化条件，不能直接拟合。 |

两文作者/机构、节点与容量相关，但没有证明是同一晶圆或工艺分裂。暂保留两个来源分支：Shin分支研究STI/漏电/保持的控制条件；Park分支优先补结构和电路参数。不把23 fF自动赋给Shin的样本，也不把弯曲三维版图直接当矩形二维MOS。

Park的Table1文本提取混合了90/110 nm两列及4/5 nm数值；本轮不接受任何栅氧厚度值。电容EOT的OCR存在单位歧义，也不用于填栅氧厚度。其余必要参数——宽度、结深、掺杂剖面、绝对Cbl、VDD、字线/板极偏压——继续留空。

## 校准顺序

1. 取得Park Table1、Fig10/13以及Shin Fig8/11/12的可核验原图，建立图—条件—器件分支对应表。
2. 先选择一个主结构；有实际偏压/温度后，同一转移曲线检查Vth、亚阈值摆幅与Ioff，若有数据再增加第二漏偏压和体偏压辨识参数。
3. 结漏、GIDL、亚阈值漏电分别对应观测；没有面积/单元数归一化就不能合并电流。
4. 阵列保持分布与单节点Vsn(t)分开。已确认Cstore之后，再完成无粒子的0/1保持、预充电与读出。

## 当前访问边界

Shin旧下载404来自错误的URL拼接；上述正确PDF路径已由搜索工具解析为5页，Park为4页。截图工具本轮未返回可查看像素；本机下载受到网站访问限制，已停止该路径，没有绕过。没有保存两份PDF/PNG，也没有伪造曲线点。此前“未能访问全文”的状态应更新为“正文可读，原图像素与测量条件仍待核验”。

另外检索到SSDM 2004的BCS-TESC结构研究，可提示相同节点的位线电容仍随结构变化；由于本轮仅有检索正文、未核对全文原图，不把其数字纳入参数表。
