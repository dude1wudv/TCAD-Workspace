from pathlib import Path
import csv, json, hashlib
from collections import Counter
from datetime import datetime, timezone, timedelta

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SNAP=ROOT/'reports/final-r4/data/snapshot'
rows=list(csv.DictReader((SNAP/'responses.csv').open(encoding='utf-8')))
res=list(csv.DictReader((SNAP/'prediction-residuals.csv').open(encoding='utf-8')))
scores=list(csv.DictReader((SNAP/'prediction-scores.csv').open(encoding='utf-8')))
assert len(rows)==128 and len({x['event_label'] for x in rows})==64
counts=Counter(json.loads(x['effective_classification'])['5.0'] for x in rows)
assert counts==dict(correct=96,criterion_error=20,critical=8,numerically_uncertain=4)

def coord(items,x,y):
    return ' '.join(f'({x(r):.10g},{y(r):.10g})' for r in items)

def response_plot(bit):
    plots=[]
    for particle,color in [('alpha','coral'),('proton','blue')]:
        for angle,mark in [(0,'*'),(30,'triangle*')]:
            a=[r for r in rows if int(r['stored_bit'])==bit and r['particle']==particle and int(r['angle_deg'])==angle]
            assert len(a)==16
            pts=coord(a,lambda r:[.18,.25,.35,.45].index(float(r['gate_length_um']))+1,lambda r:float(r['M_mV']))
            plots.append(r'\addplot+[only marks,mark='+mark+',mark size=2.3pt,color='+color+',opacity=.82] coordinates {'+pts+'};')
    return r'''\begin{tikzpicture}
\begin{axis}[width=8.45cm,height=6.6cm,scale only axis=false,
 xmin=.65,xmax=4.35,ymin=-20,ymax=90,xtick={1,2,3,4},xticklabels={0.18,0.25,0.35,0.45},
 ytick={-20,0,20,40,60,80},xlabel={栅长（μm）},ylabel={读出裕量（mV）},
 title={\bfseries 存储'''+str(bit)+r'''},title style={yshift=2pt},
 axis lines=left,axis line style={muted},tick style={muted},tick label style={font=\footnotesize},
 label style={font=\small},grid=major,grid style={soft},clip=true]
\addplot[draw=none,fill=soft] coordinates {(.65,-5)(4.35,-5)(4.35,5)(.65,5)}\closedcycle;
\addplot[dashed,muted,no marks] coordinates {(.65,5)(4.35,5)};
\addplot[dashed,muted,no marks] coordinates {(.65,-5)(4.35,-5)};
'''+ '\n'.join(plots)+r'''
\end{axis}\end{tikzpicture}'''

def prediction_plot(target,lim,ticks,unit,title):
    plots=[]
    for split,color in [('holdout','blue'),('extrapolation','coral')]:
        for bit,mark in [(0,'*'),(1,'triangle*')]:
            a=[r for r in res if r['model']=='ridge' and r['target']==target and r['split']==split and int(r['stored_bit'])==bit]
            assert len(a)==16
            pts=coord(a,lambda r:float(r['observed']),lambda r:float(r['prediction']))
            plots.append(r'\addplot+[only marks,mark='+mark+',mark size=2.2pt,color='+color+',opacity=.8] coordinates {'+pts+'};')
    return r'''\begin{tikzpicture}\begin{axis}[
width=8.35cm,height=6.8cm,axis equal image,
xmin='''+str(lim[0])+',xmax='+str(lim[1])+',ymin='+str(lim[0])+',ymax='+str(lim[1])+r''',
xtick={'''+ticks+r'''},ytick={'''+ticks+r'''},
xlabel={仿真结果（'''+unit+r'''）},ylabel={模型预测（'''+unit+r'''）},
title={\bfseries '''+title+r'''},axis lines=left,axis line style={muted},tick style={muted},
tick label style={font=\footnotesize},label style={font=\small},grid=major,grid style={soft}]
\addplot[dashed,muted,no marks,domain='''+str(lim[0])+':'+str(lim[1])+r'''] {x};
'''+ '\n'.join(plots)+r'''
\end{axis}\end{tikzpicture}'''

score_lines=[]
for target,label in [('deltaQ_fC','电荷变化（fC）'),('deltaM_mV','读出裕量变化（mV）')]:
    for bit in [0,1]:
        values=[]
        for split in ['holdout','extrapolation']:
            r=next(r for r in scores if r['model']=='ridge' and r['target']==target and int(r['stored_bit'])==bit and r['split']==split)
            assert r['valid_n']=='16'
            values.append(f"{float(r['RMSE']):.4f}")
        score_lines.append(f'{label} & 存储{bit} & '+ ' & '.join(values)+r' \\')

tex=r'''\documentclass[UTF8,fontset=fandol,10pt,a4paper]{ctexart}
\usepackage[left=18mm,right=18mm,top=16mm,bottom=17mm,headheight=12pt]{geometry}
\usepackage{amsmath,booktabs,tabularx,array,xcolor,tikz,pgfplots,fancyhdr}
\usetikzlibrary{arrows.meta,positioning,calc}
\pgfplotsset{compat=1.18}
\usepackage[hidelinks,unicode]{hyperref}
\renewcommand{\familydefault}{\sfdefault}
\renewcommand{\CJKfamilydefault}{\CJKsfdefault}
\definecolor{ink}{HTML}{172E3A}
\definecolor{blue}{HTML}{287A9A}
\definecolor{coral}{HTML}{CC7053}
\definecolor{green}{HTML}{367C70}
\definecolor{gold}{HTML}{D5A34A}
\definecolor{muted}{HTML}{677A83}
\definecolor{soft}{HTML}{EDF2F4}
\definecolor{purple}{HTML}{83749E}
\color{ink}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\linespread{1.23}
\setlength{\emergencystretch}{2em}
\pagestyle{fancy}\fancyhf{}
\fancyfoot[L]{\scriptsize\color{muted}DRAM SEE v3\quad 项目简报}
\fancyfoot[R]{\scriptsize\color{muted}\thepage\,/\,3}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{.3pt}
\newcommand{\kicker}[1]{{\small\bfseries\color{blue}#1}\par\vspace{4pt}}
\newcommand{\bigtitle}[1]{{\fontsize{22}{30}\selectfont\bfseries #1}\par\vspace{6pt}}
\newcommand{\sect}[1]{\par\vspace{9pt}{\large\bfseries #1}\par\vspace{4pt}}
\newcommand{\note}[1]{\par{\footnotesize\color{muted}#1}\par}
\newcommand{\metric}[2]{\begin{minipage}[t]{.31\textwidth}{\fontsize{29}{34}\selectfont\bfseries\color{blue}#1}\par\small #2\end{minipage}}
\hypersetup{pdftitle={AI辅助下的多特征尺寸存储器单粒子效应评估 项目简报},pdfauthor={DRAM SEE v3 项目}}
\begin{document}
\kicker{项目简报\hfill @DATE@}
\bigtitle{AI辅助下的多特征尺寸\\存储器单粒子效应评估}
本项目研究不同栅长DRAM在α粒子和质子入射后的变化。已完成4种栅长的仿真，整理了电荷与读出数据，并训练、验证了4个预测模型。存储单元采用1T1C结构。

\vspace{9pt}
\metric{4}{种栅长}\hfill\metric{64}{个独立粒子事件}\hfill\metric{128}{次响应，包含存储0和1}
\vspace{12pt}

\sect{仿真流程}
\begin{center}
\begin{tikzpicture}[>=Stealth,
box/.style={rounded corners=3pt,draw=none,fill=soft,text width=3.05cm,minimum height=1.6cm,align=center,inner sep=7pt},
arr/.style={->,line width=1.1pt,blue}]
\node[box] (a) {\textbf{设置仿真条件}\\[4pt]\small 栅长、粒子、角度};
\node[box,right=6mm of a] (b) {\textbf{计算能量沉积}\\[4pt]\small Geant4};
\node[box,right=6mm of b] (c) {\textbf{计算存储器响应}\\[4pt]\small Sentaurus TCAD};
\node[box,right=6mm of c] (d) {\textbf{分析数据}\\[4pt]\small 绘图、训练预测模型};
\draw[arr] (a)--(b);\draw[arr] (b)--(c);\draw[arr] (c)--(d);
\end{tikzpicture}
\end{center}
\note{Geant4计算粒子在材料中的能量沉积，Sentaurus TCAD据此计算存储单元的响应。}

\sect{参数设置}
\renewcommand{\arraystretch}{1.65}
\begin{tabularx}{\textwidth}{@{}>{\bfseries}p{2.2cm}X@{}}
\toprule
栅长 & 0.18、0.25、0.35、0.45 μm \\
入射粒子 & α粒子、质子；能量均为5 MeV \\
入射方向 & 0°、30° \\
存储状态 & 每个粒子事件均计算存储0和存储1两种状态 \\
随机种子 & 每组栅长、粒子和角度组合使用4个独立种子 \\
\bottomrule
\end{tabularx}\par

\sect{已完成工作}
已建立存储单元和粒子模型，完成批量仿真，整理了电荷变化数据、读出曲线和场分布图。原始输出与运行记录均已保存。

AI助手用于整理条件、编写脚本和分析结果，也参与批量仿真的运行管理。4个预测模型使用本项目的数据训练，训练和测试结果见第3页。
\vfill
\note{数据版本：DRAM SEE v3 R50。}

\newpage
\kicker{项目简报\hfill DRAM SEE v3}
\bigtitle{仿真结果}
128次主实验响应已完成。读出裕量用于判断存储值能否正确读出，两个图分别对应存储0和存储1。

\vspace{7pt}
\begin{center}
\begin{minipage}{.49\textwidth}\centering @RESPONSE0@\end{minipage}\hfill
\begin{minipage}{.49\textwidth}\centering @RESPONSE1@\end{minipage}
\end{center}
\note{橙色为α粒子，蓝色为质子；圆点为0°入射，三角为30°入射。每个点表示一次响应，灰色带标出$\pm5$ mV判定区间。}

\sect{读出状态统计}
\note{128次响应按5 mV判据分类。}
\begin{center}
\begin{tikzpicture}[x=.129cm,y=1cm]
\fill[green] (0,0) rectangle (96,.62);
\fill[coral] (96,0) rectangle (116,.62);
\fill[gold] (116,0) rectangle (124,.62);
\fill[purple] (124,0) rectangle (128,.62);
\node[white,font=\bfseries] at (48,.31) {96};
\node[white,font=\bfseries] at (106,.31) {20};
\node[ink,font=\bfseries] at (120,.31) {8};
\node[white,font=\bfseries] at (126,.31) {4};
\end{tikzpicture}
\end{center}
\begin{tabularx}{\textwidth}{@{}XXXX@{}}
\textcolor{green}{\textbf{96 正确读出}} & \textcolor{coral}{\textbf{20 判据误读}} & \textcolor{gold}{\textbf{8 临界}} & \textcolor{purple}{\textbf{4 数值不确定}}
\end{tabularx}\par

\vspace{12pt}
\sect{补充验证}
\begin{minipage}[t]{.48\textwidth}
{\fontsize{24}{29}\selectfont\bfseries\color{blue}14}\quad\textbf{项氧化层试验}\par
比较4、5、6 nm氧化层厚度下的电荷与读出变化。
\end{minipage}\hfill
\begin{minipage}[t]{.48\textwidth}
{\fontsize{24}{29}\selectfont\bfseries\color{blue}2}\quad\textbf{个近边界响应}\par
从全部主实验结果中选取，分别用更小的时间步和更细的网格复核。
\end{minipage}\par
\vspace{12pt}
补充计算已完成。各项结果均保留了对应的原始输出，便于与主实验比较。
\vfill
\note{数据来源：主实验响应表及氧化层、边界验证记录。}

\newpage
\kicker{项目简报\hfill DRAM SEE v3}
\bigtitle{模型训练与验证}
采用岭回归训练了4个模型：存储0和存储1各有两个，分别预测电荷变化和读出裕量变化。训练使用0.18、0.35~μm的数据，测试使用0.25、0.45~μm的数据。

\vspace{5pt}
\begin{center}
\begin{tikzpicture}[>=Stealth,
box/.style={fill=soft,rounded corners=3pt,text width=4.4cm,minimum height=1.15cm,align=center,inner sep=6pt}]
\node[box] (a) {\textbf{训练}\\\small 使用64次仿真响应};
\node[box,right=7mm of a] (b) {\textbf{预测}\\\small 固定模型，保存64条预测};
\node[box,right=7mm of b] (c) {\textbf{测试}\\\small 与64次新仿真响应比对};
\draw[->,blue,line width=1pt] (a)--(b);\draw[->,blue,line width=1pt] (b)--(c);
\end{tikzpicture}
\end{center}

\begin{center}
\begin{minipage}{.49\textwidth}\centering @PREDQ@\end{minipage}\hfill
\begin{minipage}{.49\textwidth}\centering @PREDM@\end{minipage}
\end{center}
\note{虚线表示预测值与仿真值相等。蓝色为0.25 μm，橙色为0.45 μm；圆点为存储0，三角为存储1。}

\sect{测试误差}
\note{表中为均方根误差，用于衡量预测值与仿真值的差距，数值越小，预测越接近仿真。}
\renewcommand{\arraystretch}{1.4}
\begin{tabularx}{\textwidth}{@{}Xlrr@{}}
\toprule
预测内容 & 存储状态 & 0.25 μm & 0.45 μm \\
\midrule
@SCORES@
\bottomrule
\end{tabularx}\par
\vspace{9pt}
与直接用训练数据的平均值预测相比，4个模型在两种测试尺寸上的误差都更小。

\vfill
\sect{现有材料}
已整理课程报告、论文和汇报PPT，并附数据表、图件和来源索引。
\note{图表数据取自已固定的模型预测、仿真结果与测试评分表。}
\end{document}
'''
tex=tex.replace('@DATE@',datetime.now(timezone(timedelta(hours=-8))).strftime('%Y年%m月%d日'))
for k,v in {'@RESPONSE0@':response_plot(0),'@RESPONSE1@':response_plot(1),'@PREDQ@':prediction_plot('deltaQ_fC',[-5.7,0],'-5,-4,-3,-2,-1,0','fC','电荷变化'),'@PREDM@':prediction_plot('deltaM_mV',[-52,55],'-40,-20,0,20,40','mV','读出裕量变化'),'@SCORES@':'\n'.join(score_lines)}.items():
    tex=tex.replace(k,v)
assert '@RESPONSE' not in tex and '@PRED' not in tex
tex=tex.replace('μm',r'$\mu$m').replace('α',r'$\alpha$')
(HERE/'project-brief.tex').write_text(tex,encoding='utf-8')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
e={'utc':datetime.now(timezone.utc).isoformat(),'scope':'Standalone LaTeX visual brief; all plotted numeric coordinates embedded from existing CSVs','sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in [SNAP/'responses.csv',SNAP/'prediction-residuals.csv',SNAP/'prediction-scores.csv',ROOT/'reports/final-r4/delivery-manifest.json']},'plots':{'readout':{'response_count':128,'independent_events':64,'y_column':'M_mV','x':'four categorical gate-length positions, labelled in micrometers','stored_bits':[0,1]},'predictions':{'each_target_points':64,'targets':['deltaQ_fC','deltaM_mV'],'model':'ridge','x_column':'observed','y_column':'prediction','reference_line':'y=x'}},'main_counts':dict(counts),'source_tex_sha256':sha(HERE/'project-brief.tex'),'no_simulation_or_retraining':True}
(HERE/'data-binding.json').write_text(json.dumps(e,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'tex':str(HERE/'project-brief.tex'),'characters':len(tex),'binding':str(HERE/'data-binding.json')},ensure_ascii=False))
