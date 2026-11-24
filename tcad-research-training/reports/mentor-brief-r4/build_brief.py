from pathlib import Path
import csv, json, hashlib
from datetime import datetime, timezone, timedelta
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FINAL = ROOT / 'reports/final-r4'
PDF = OUT / 'project-brief.pdf'
if PDF.exists():
    raise FileExistsError('Keep prior artifact; choose a versioned output for revision.')
pdfmetrics.registerFont(TTFont('YaHei', 'C:/Windows/Fonts/msyh.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('YaHeiBold', 'C:/Windows/Fonts/msyhbd.ttc', subfontIndex=0))
pdfmetrics.registerFontFamily('YaHei', normal='YaHei', bold='YaHeiBold')
S = {
    'title': ParagraphStyle('Title', fontName='YaHeiBold', fontSize=19, leading=28, spaceAfter=6),
    'subtitle': ParagraphStyle('Subtitle', fontName='YaHei', fontSize=9, leading=15, textColor=colors.HexColor('#555555'), spaceAfter=14),
    'h': ParagraphStyle('Heading', fontName='YaHeiBold', fontSize=12.5, leading=20, spaceBefore=12, spaceAfter=6, keepWithNext=True),
    'p': ParagraphStyle('Body', fontName='YaHei', fontSize=10.5, leading=18, spaceAfter=7, wordWrap='CJK'),
    'small': ParagraphStyle('Small', fontName='YaHei', fontSize=8.6, leading=14, spaceAfter=5, wordWrap='CJK', textColor=colors.HexColor('#555555')),
    'cell': ParagraphStyle('Cell', fontName='YaHei', fontSize=9.5, leading=16, wordWrap='CJK'),
}
story = []
def p(text, sty='p'):
    story.append(Paragraph(text, S[sty]))
def heading(text): p(text, 'h')
def table(rows, widths):
    t=Table([[Paragraph(str(v),S['cell']) for v in row] for row in rows], colWidths=widths, hAlign='LEFT', repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E9EEF2')),
        ('LINEBELOW',(0,0),(-1,0),0.6,colors.HexColor('#8596A3')),
        ('LINEBELOW',(0,1),(-1,-1),0.3,colors.HexColor('#D8DEE3')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
    ]))
    story.append(t)
    story.append(Spacer(1,7))

date = datetime.now(timezone(timedelta(hours=-8))).strftime('%Y年%m月%d日')
p('DRAM单粒子效应仿真与机器学习项目简报','title')
p(f'导师汇报用　｜　DRAM SEE v3 R50　｜　{date}','subtitle')
p('<b>阶段结论</b>　本项目已完成从粒子沉积、器件仿真到指标提取和机器学习预测的实际运行流程。项目利用自行生成的仿真数据训练了4个岭回归模型，并在预测冻结后完成独立测试。原始输出、失败记录、数值验证和报告均已归档。')

heading('研究目标与实际执行')
p('研究5 MeV的α粒子和质子在不同入射角度、访问晶体管栅长及存储位值下，对简化1T1C DRAM单元电荷和读出裕量的影响，并检验轻量预测模型对未参与训练尺寸的预测能力。')
p('<b>粒子与器件仿真</b>　调用已有Geant4进行粒子输运，将电离沉积换算为等效电荷源；调用已安装的Sentaurus SDE、网格工具和SDevice完成器件与电路瞬态求解。求解采用串行单线程，保存日志和实际退出状态。')
p('<b>结果收集与分析</b>　固定脚本从原始输出提取存储节点、位线、电荷和读出裕量，匹配无粒子对照及中性参考，生成统计表与曲线；Sentaurus Visual原生图和实际窗口截图另行留证。')
p('<b>AI的参与</b>　现成AI助手协助工况组织、脚本编写、调度、排障、证据核对及材料草拟。项目自行训练的岭回归模型负责数值响应预测；自然语言交互和文件解析不由这4个模型承担。')

heading('已完成的实验规模')
table([
    ['范围','实际完成情况'],
    ['主实验矩阵','4种栅长 × 2种粒子 × 2种角度 × 4个种子，共64个独立事件；每个事件配对存储0和1，共128个响应。'],
    ['训练与测试','训练32事件／64响应；测试32事件／64响应。模型和64条测试响应预测在测试TCAD提交前冻结。'],
    ['扩展验证','14个氧化层case；从全部128响应中按规则选择2个近边界响应，进行半步长与网格细化。共22个扩展角色，其中18次新求解、4项精确复用。'],
    ['运行与审计','保留全部7条历史失败及4项工程重试的原始失败记录。累计登记求解时间100022.07秒，约27.78小时，含旧版本、失败、重试及扩展。'],
], [89,416])
p('同一事件的0/1配对、工程重试和确定性细化均不增加独立事件数。已完成全量评分、原始来源核验和逐图检查。','small')

story.append(PageBreak())
p('预测结果与交付说明','title')
p('数据口径　固定r4完整快照及已验收交付包','subtitle')
heading('自行训练了什么模型')
p('以本项目TCAD输出作为监督标签，按存储0／1和两个预测量分别拟合，共4个<b>岭回归预测模型</b>；同时保留训练均值基线作比较。预测量为电荷扰动ΔQ（fC）和读出裕量变化ΔM（mV）。这是小样本监督回归，没有训练或微调大语言模型。')
p('输入特征为沉积电荷Qdep、Qdep／栅长L、Qdep×sinθ。训练使用0.18和0.35 μm；0.25 μm作为域内留出，0.45 μm作为尺寸外推。正则化参数仅在8个训练物理工况的分组交叉验证中选择；同事件的配对和重复保持同组，测试阶段不重新拟合。')
p('预测仍以真实Geant4沉积信息及已知无辐照基线为条件。它能估计本项目范围内的TCAD响应，尚不能从任意一句自然语言或任意粒子条件直接替代完整物理仿真。')

scores=list(csv.DictReader((FINAL/'data/snapshot/prediction-scores.csv').open(encoding='utf-8')))
rows=[['独立测试条件','ΔQ RMSE　fC','ΔM RMSE　mV']]
for split,label in [('holdout','0.25 μm 域内留出'),('extrapolation','0.45 μm 尺寸外推')]:
    ranges=[]
    for target in ['deltaQ_fC','deltaM_mV']:
        vals=[float(r['RMSE']) for r in scores if r['split']==split and r['target']==target and r['model']=='ridge']
        assert len(vals)==2
        ranges.append(f'{min(vals):.4f} 至 {max(vals):.4f}')
    rows.append([label,*ranges])
table(rows,[215,145,145])
p('范围为存储0和1两个模型的结果，不是置信区间。每个尺寸含16个独立事件、32个配对响应，每个“位值×预测量”评分使用16条响应；全部8项RMSE均低于相应训练均值基线。完整MAE、RMSE及最大误差见评分表。','small')

heading('主要结果与适用边界')
p('在5 mV主阈值下，128个响应为<b>96个正确、20个判据误读、8个临界、4个数值不确定</b>。这里的“正确”是仿真读出状态，不是机器学习预测准确率。4项边界细化的连续量误差满足原容差，但有一项在5 mV跨界，故保留不确定分类。')
p('结论限于未校准二维模型、固定能量与入射位置。当前结果不等同于真实DRAM持久位翻转、器件实测或商业可靠性认证。氧化层实验属于固定硅入口事件的受控敏感性分析，尚无微小效应显著性结论；本项目也未设置人工效率对照，不能报告AI加速倍数。')

heading('交付内容与后续工作')
p('已交付21页课程报告、14页论文、16页可编辑PPT、7份课程支持材料、完整数据与证据索引。报告与PPT共51页已逐页检查，最终211文件哈希和50个链接独立核验通过。')
p('建议导师重点审阅物理假设、等效源传递和尺寸外推范围，再决定是否推进器件校准、三维结构与更丰富入射条件。学生真实分工与操作、教师审核和正式答辩仍须据实完成并登记；当前材料不代替这些活动。')
p('依据：reports/final-r4/README.md；data/frozen-models.json；data/snapshot/prediction-scores.csv；以及同包课程报告和QA。完整来源哈希随本简报保存在evidence.json。','small')

def footer(c,doc):
    c.setStrokeColor(colors.HexColor('#D8DEE3')); c.setLineWidth(.4)
    c.line(45,36,A4[0]-45,36)
    c.setFont('YaHei',8); c.setFillColor(colors.HexColor('#555555'))
    c.drawString(45,23,'DRAM SEE v3 R50  ·  导师项目简报')
    c.drawRightString(A4[0]-45,23,str(doc.page))

doc=SimpleDocTemplate(str(PDF),pagesize=A4,rightMargin=45,leftMargin=45,topMargin=38,bottomMargin=48,title='DRAM单粒子效应仿真与机器学习项目简报',author='DRAM SEE v3 项目',allowSplitting=1)
doc.build(story,onFirstPage=footer,onLaterPages=footer)
sources=[FINAL/'README.md',FINAL/'data/frozen-models.json',FINAL/'data/snapshot/prediction-scores.csv',FINAL/'sections/course/03-platform.tex',FINAL/'sections/course/04-design.tex',FINAL/'sections/paper/05-prediction-discussion.tex',FINAL/'delivery-manifest.json']
sha=lambda q:hashlib.sha256(q.read_bytes()).hexdigest()
e={'generated_utc':datetime.now(timezone.utc).isoformat(),'purpose':'Advisor project brief derived only from accepted frozen project evidence','source_sha256':{q.relative_to(ROOT).as_posix():sha(q) for q in sources},'output_sha256':sha(PDF),'authoring_source_sha256':sha(Path(__file__)),'original_package_modified':False,'new_simulation_or_training':False,'human_activity_claimed':False,'pending':'Visual review of the newly rendered brief'}
(OUT/'evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'pdf':str(PDF),'sha256':sha(PDF)},ensure_ascii=False))
