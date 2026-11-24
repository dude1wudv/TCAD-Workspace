AI辅助下的多特征尺寸存储器单粒子效应评估
模型依据与物理机制

交付文件
report.tex      可编辑的单文件LaTeX源稿；公式、TikZ示意图和PGFPlots数据图均内嵌。
report.pdf      由同一源稿通过XeLaTeX生成的PDF。
sources.json    引用的本地证据哈希、外部文献来源、图表字段映射与核验范围。
build.ps1       本机可复用构建入口。

范围
本版包含模型依据、物理机制、已完成D1无粒子读出诊断和v3冻结设计的衔接。
正文使用固定已完成证据，不更新或操纵v3运行控制器。
文献支撑原理；项目的几何、电容、掺杂及读出阈值仍属于探索设定，未作工艺校准。
v3最终矩阵、预测精度、氧化层敏感性、真实学生分工及教师审核不在本版完成范围。
本版是通用中文学术排版，没有声称符合尚未提供的学校模板。

编译
推荐XeLaTeX。常规完整TeX Live/MiKTeX中执行两次：
  xelatex -interaction=nonstopmode -halt-on-error report.tex
当前Windows工作区可执行：
  powershell -ExecutionPolicy Bypass -File reports/paper/build.ps1
内嵌参考文献无需BibTeX；Fandol中文字体由ctex字体集提供。
依赖包括ctex、amsmath、booktabs、tabularx、tikz/pgf、pgfplots、caption、float、placeins、hyperref。
为避免改动本机TeX安装，首次导出所缺的pgf/placeins包放在忽略目录local_runtime/report-writing-20261010/tex-deps。
build.ps1只在当前构建进程中加入该目录；不修改系统环境或仿真环境。

修改和溯源
优先修改report.tex。图3的点均来自D1 summary.csv的6个标准字线工况；连线仅用于连接离散点。
添加新结果时需保留实验版本、指标定义、独立事件分母和原始来源，不能把v1/v2结果改标为v3。
源码变化后，sources.json中的report.tex哈希应重新生成；不要将旧哈希解释成新版本验收。
编译日志、页面渲染和编辑核验记录放在local_runtime/report-writing-20261010，不作为论文正文。
