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
\newcommand{\bigtitle}[1]{{\fontsize{25}{33}\selectfont\bfseries #1}\par\vspace{6pt}}
\newcommand{\sect}[1]{\par\vspace{9pt}{\large\bfseries #1}\par\vspace{4pt}}
\newcommand{\note}[1]{\par{\footnotesize\color{muted}#1}\par}
\newcommand{\metric}[2]{\begin{minipage}[t]{.31\textwidth}{\fontsize{29}{34}\selectfont\bfseries\color{blue}#1}\par\small #2\end{minipage}}
\hypersetup{pdftitle={AI辅助下的多特征尺寸存储器单粒子效应评估 项目简报},pdfauthor={DRAM SEE v3 项目}}
\begin{document}
\kicker{01\quad 项目做了什么\hfill @DATE@}
\bigtitle{AI辅助下的多特征尺寸\\存储器单粒子效应评估}
比较不同尺寸的DRAM在粒子入射后的变化，\textbf{完成仿真、整理数据，并训练模型预测新尺寸的结果。}

\vspace{9pt}
\metric{4}{种栅长尺寸}\hfill\metric{64}{个独立粒子事件}\hfill\metric{128}{次存储0／1配对响应}
\vspace{12pt}

\sect{把粒子入射到读出结果的过程连接起来}
\begin{center}
\begin{tikzpicture}[>=Stealth,
box/.style={rounded corners=3pt,draw=none,fill=soft,text width=3.05cm,minimum height=1.6cm,align=center,inner sep=7pt},
arr/.style={->,line width=1.1pt,blue}]
\node[box] (a) {\textbf{设置条件}\\[4pt]\small 尺寸、粒子、角度};
\node[box,right=6mm of a] (b) {\textbf{计算粒子沉积}\\[4pt]\small Geant4};
\node[box,right=6mm of b] (c) {\textbf{计算存储器响应}\\[4pt]\small Sentaurus TCAD};
\node[box,right=6mm of c] (d) {\textbf{整理与预测}\\[4pt]\small 数据图与机器学习};
\draw[arr] (a)--(b);\draw[arr] (b)--(c);\draw[arr] (c)--(d);
\end{tikzpicture}
\end{center}
\note{流程示意。AI助手参与条件整理、脚本编写、运行调度和结果分析。}

\sect{这次比较了哪些条件}
\renewcommand{\arraystretch}{1.65}
\begin{tabularx}{\textwidth}{@{}>{\bfseries}p{2.2cm}X@{}}
\toprule
栅长尺寸 & 0.18、0.25、0.35、0.45 μm \\
入射粒子 & α粒子、质子；能量均为5 MeV \\
入射方向 & 0°、30° \\
存储状态 & 同一个粒子事件，分别计算存储0和存储1的响应 \\
重复设置 & 每组尺寸、粒子和角度组合，使用4个独立种子 \\
\bottomrule
\end{tabularx}\par

\sect{实际运行并留下可查看的结果}
\begin{minipage}[t]{.48\textwidth}
\textbf{仿真侧}\par
建立存储单元与粒子模型，完成批量运行，保存原始输出与运行记录。
\end{minipage}\hfill
\begin{minipage}[t]{.48\textwidth}
\textbf{分析侧}\par
提取电荷和读出变化，形成数据图、预测结果及报告材料。
\end{minipage}\par
\vfill
\note{研究对象：1T1C DRAM单元。数据版本：DRAM SEE v3 R50完整结果。}

\newpage
\kicker{02\quad 仿真得到了什么}
\bigtitle{把不同条件下的响应放在一起比较}
所有主实验响应均已完成。下图汇总4种尺寸在两种存储状态下的读出结果。

\vspace{7pt}
\begin{center}
\begin{minipage}{.49\textwidth}\centering @RESPONSE0@\end{minipage}\hfill
\begin{minipage}{.49\textwidth}\centering @RESPONSE1@\end{minipage}
\end{center}
\note{橙色：α粒子；蓝色：质子。圆点：0°；三角：30°。每个点对应一次仿真响应，灰色带为$\pm5$ mV判定区间。}

\sect{128次响应的读出结果}
\note{按5 mV判据汇总；这里统计的是存储单元的读出状态。}
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
\sect{围绕关键条件继续做验证}
\begin{minipage}[t]{.48\textwidth}
{\fontsize{24}{29}\selectfont\bfseries\color{blue}14}\quad\textbf{项氧化层试验}\par
对比4、5、6 nm条件，整理电荷与读出变化。
\end{minipage}\hfill
\begin{minipage}[t]{.48\textwidth}
{\fontsize{24}{29}\selectfont\bfseries\color{blue}2}\quad\textbf{个近边界响应}\par
分别减小时间步和网格尺寸，检查结果的稳定性。
\end{minipage}\par
\vspace{12pt}
\textbf{结果已归档：}电荷变化、读出曲线、原生场图与每次运行记录可以相互对应。
\vfill
\note{图中包含全部128次主实验响应；读出裕量用于判断存储值能否正确读出。}

\newpage
\kicker{03\quad 用数据训练预测模型}
\bigtitle{先预测新尺寸，再用仿真检验}
训练4个岭回归模型，分别学习存储0／1两种状态下的\textbf{电荷变化}和\textbf{读出裕量变化}。

\vspace{5pt}
\begin{center}
\begin{tikzpicture}[>=Stealth,
box/.style={fill=soft,rounded corners=3pt,text width=4.4cm,minimum height=1.15cm,align=center,inner sep=6pt}]
\node[box] (a) {\textbf{64次响应用于训练}\\\small 0.18、0.35 μm};
\node[box,right=7mm of a] (b) {\textbf{固定模型和预测}\\\small 4个模型，先给出预测值};
\node[box,right=7mm of b] (c) {\textbf{64次新响应用于检验}\\\small 0.25、0.45 μm};
\draw[->,blue,line width=1pt] (a)--(b);\draw[->,blue,line width=1pt] (b)--(c);
\end{tikzpicture}
\end{center}

\begin{center}
\begin{minipage}{.49\textwidth}\centering @PREDQ@\end{minipage}\hfill
\begin{minipage}{.49\textwidth}\centering @PREDM@\end{minipage}
\end{center}
\note{点越靠近虚线，预测与仿真越接近。蓝色：0.25 μm；橙色：0.45 μm。圆点／三角：存储0／1。}

\sect{新尺寸上的预测误差}
\note{均方根误差，数值越小越好。两种尺寸均使用预先固定的预测进行比对。}
\renewcommand{\arraystretch}{1.4}
\begin{tabularx}{\textwidth}{@{}Xlrr@{}}
\toprule
预测内容 & 存储状态 & 0.25 μm & 0.45 μm \\
\midrule
@SCORES@
\bottomrule
\end{tabularx}\par
\vspace{9pt}
4个模型在两种测试尺寸上的误差，均低于直接使用训练均值的参考方法。

\vfill
\textbf{已形成交付材料}\quad 课程报告、论文、演示PPT、完整数据与证据索引。
\note{图表数据取自本项目冻结仿真结果与测试评分表。}
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
