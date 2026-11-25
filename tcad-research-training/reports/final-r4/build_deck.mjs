// Read-only authoring from the accepted r4 snapshot. No controller imports.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { Presentation, PresentationFile, FileBlob } from '@oai/artifact-tool';
const ROOT = process.env.TCAD_REPORT_ROOT || 'E:/TCAD-Workspace/tcad-research-training';
const HERE = path.join(ROOT, 'reports/final-r4');
const SKILL = 'C:/Users/sun/.codex/plugins/cache/openai-primary-runtime/presentations/26.1009.11318/skills/presentations';
const PY = 'C:/Users/sun/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
process.env.RUNTIME_NODE_MODULES = 'C:/Users/sun/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { finalizePresentation, applyPresentationChartFont } = await import(pathToFileURL(path.join(SKILL, 'container_tools/artifact_tool_utils.mjs')).href);
const tag = process.argv[2];
if (!tag || !/^[A-Za-z0-9_-]+$/.test(tag)) throw Error('Provide a unique build tag');
const out = path.join(ROOT, 'local_runtime/dram-see-v3/final-r4-document-build', 'deck-' + tag);
await fs.mkdir(out, { recursive: false });
const render = path.join(out, 'slides'); await fs.mkdir(render);
const summary = JSON.parse(await fs.readFile(path.join(HERE, 'data/snapshot/summary.json'), 'utf8'));
const results = JSON.parse(await fs.readFile(path.join(HERE, 'data/writing-results.json'), 'utf8'));
const binding = JSON.parse(await fs.readFile(path.join(HERE, 'data/snapshot-binding.json'), 'utf8'));
if (summary.measured_main_responses !== 128 || summary.planned_independent_events !== 64) throw Error('Wrong evidence snapshot');
const p = Presentation.create({ slideSize: {width:1280,height:720} });
const F='Microsoft YaHei', C={ink:'#172D45',blue:'#205A87',teal:'#177F79',orange:'#B85B27',muted:'#52677A',red:'#AF3D3D',gray:'#EDF2F5',white:'#FFFFFF'};
const meta=[];
function text(slide,value,x,y,w,h,size=28,color=C.ink,bold=false){
 const q=slide.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 q.text=value;q.text.style={fontSize:size,typeface:F,bold,color,alignment:'left',verticalAlignment:'top',insets:0,wrap:'word',autoFit:'none'};return q;
}
function slide(title,subtitle,source){
 const s=p.slides.add();s.background.fill=C.white;
 const n=p.slides.items.length;text(s,title,60,37,1160,76,44,C.ink,true);
 if(subtitle)text(s,subtitle,60,111,1160,48,24,C.muted);
 text(s,'DRAM SEE v3 · R50 / frozen r4 · 64 events / 128 responses',60,679,1110,23,16,C.muted);
 text(s,String(n).padStart(2,'0')+(n>12?' / 备份':''),1120,679,110,23,16,C.muted);
 s.speakerNotes.text='来源：'+source+'\n冻结快照 SHA256: '+binding.source_manifest_sha256+'\n原生图表数值为展示兼容按6位小数舍入，全精度数值保持在原快照。外部最终数据验收见data/delivery-root-acceptance.json，采集时PENDING标签不回写。\n本材料不声称学生现场操作、教师审核或答辩已完成。';
 meta.push({slide:n,title,source});return s;
}
function tbl(s,values,x,y,w,h,widths,size=24){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
 t.borders.assign({style:'solid',fill:'#D1DAE1',width:1});
 for(let r=0;r<values.length;r++)for(let c=0;c<values[r].length;c++){
   const cell=t.getCell(r,c);cell.fill=r===0?C.ink:(r%2?C.white:C.gray);
   cell.text.style={typeface:F,fontSize:size,color:r===0?C.white:C.ink,bold:r===0,alignment:'left',verticalAlignment:'middle',insets:10};
 }
 return t;
}
async function img(s,name,x,y,w,h){const b=await fs.readFile(path.join(HERE,'figures',name));s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:name,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
function chart(s,type,cfg){
 // Native embedded Excel charts intentionally carry presentation-scale values.
 // Full precision is retained in the immutable snapshot and score JSON.
 for(const series of cfg.series)series.values=series.values.map(v=>v===null?null:Number(v.toFixed(6)));
 const c=s.charts.add(type,{chartFill:C.white,plotAreaFill:C.white,...cfg});applyPresentationChartFont(c,{fontFamily:F});return c;
}
const axis={textStyle:{fontSize:23,fill:C.muted},line:{fill:'#CBD5DF',width:1},majorGridlines:null};
const fmt=(v,d=4)=>Number(v).toFixed(d);
const scores=summary.final_numerical_prediction_scores.scores;
const sc=(split,bit,target,model='ridge')=>scores.find(x=>x.split===split&&x.stored_bit===bit&&x.target===target&&x.model===model);

{
 const s=slide('从粒子沉积到读出判据','DRAM 单粒子效应跨工具仿真与冻结预测 · 完整 r4 证据', 'summary.json; responses.csv; final-numerical-prediction-scores.json');
 text(s,'固定样本已完成，分类不确定仍保留',60,191,1130,95,52,C.blue,true);
 const values=[['64','独立事件'],['128','配对响应'],['64','冻结测试预测'],['4','5 mV 数值不确定']];
 values.forEach((v,i)=>{text(s,v[0],60+i*300,327,270,100,72,C.ink,true);text(s,v[1],60+i*300,433,280,60,27,C.muted);});
 text(s,'96 正确 · 20 判据误读 · 8 临界 · 4 数值不确定',60,545,1160,58,32,C.teal,true);
 text(s,'限定于未校准二维模型；不推断商业 DRAM 可靠性或持久位翻转。',60,611,1160,44,25,C.muted);
}
{
 const s=slide('研究问题：沉积电荷怎样改变读出裕量？','以同条件中性参考消除模型共模偏移，再讨论判据与误差。','sections/paper/02-model-transfer.tex; sections/paper/03-workflow-metrics.tex; summary.json');
 text(s,'电荷响应',60,189,510,55,32,C.blue,true);text(s,'ΔQ = Cs × (SNsig − SNctl)\n在 2.8 ns 计算；Cs = 10 fF\nsig：粒子信号；ctl：同位对照',60,257,560,180,29);
 text(s,'读出判据',680,189,520,55,32,C.blue,true);text(s,'D = BLsig − BLneu\nM = (2b − 1)D；ΔM = Mctl − M\n在 4 ns 计算；neu：中性参考',680,257,540,180,28);
 text(s,'M > ε：正确     M < −ε：判据误读     |M| ≤ ε：临界',60,475,1150,62,30,C.teal,true);
 text(s,'数值不确定单独报告；“判据误读”不等同于真实感放锁存或持久 SEU。',60,571,1150,70,28,C.muted);
}
{
 const s=slide('证据链：从输入约束到独立评分','每个逻辑响应都能追溯实际 owner、case-freeze、原档与 SHA256。','summary.json.provenance_prerequisites; response-sources.json; sources.json; original-r4-prediction-scores.json');
 const lines=[['01  请求约束','预览、审计与定位；越界和不支持动作拒绝'],['02  事件输运','5 MeV α / proton，0° / 30°；硅中电离沉积'],['03  源项映射','有限轨迹、源积分审计；匹配 control / neutral'],['04  训练冻结','32 事件 → 64 响应；四模型与 64 预测预先冻结'],['05  实证审查','64 测试响应、14 氧化层 case、4 边界比较与原生图']];
 lines.forEach((a,i)=>{text(s,a[0],60,178+i*90,285,65,30,C.blue,true);text(s,a[1],365,181+i*90,845,67,27);});
}
{
 const s=slide('实验矩阵保持原分母','每个粒子事件配对运行存储 0 / 1；工程重试与扩展不增加 N。','design.json; summary.json.responses; statistics.csv');
 tbl(s,[['数据分区','栅长 / μm','事件','响应'],['训练','0.18，0.35','32','64'],['域内留出','0.25','16','32'],['尺寸外推','0.45','16','32'],['合计','四种栅长','64','128']],60,191,720,363,[180,240,150,150]);
 text(s,'共同条件',837,188,370,53,32,C.blue,true);
 text(s,'α / proton × 0° / 30°\n每工况 4 个独立事件\n5 nm 名义氧化层\n50 Ω 预充 → 释放\n串行、单线程执行',837,259,380,300,27);
 text(s,'每层 N = 4：区间较宽；配对位、重试、数值细化均不作为额外独立样本。',60,596,1160,65,27,C.muted);
}
{
 const s=slide('初始化与读出必须有匹配参照','准静态夹持用于受控初态；历史校准失败仍保留。','summary.json.stages; historical d1-reference-comparison.sources.json; r50-precharge.sources.json; matched-metrics schema');
 text(s,'时序约定',60,184,530,55,32,C.blue,true);
 text(s,'0.6 ns 释放初态夹持\n0.95 ns 检查，1 ns 入射\n2.8 ns 电荷响应\n2.8–2.9 ns 位线预充\n3 ns 释放，4 ns 读出',60,255,535,330,29);
 text(s,'两项历史诊断',675,184,540,55,32,C.blue,true);
 text(s,'理想 0.5 V 参考可能改变类别\n应使用同条件 neutral 曲线\n\n100 Ω 残差未通过 10 μV 门槛\n50 Ω probe 支持版本化主线\n历史记录不混入新事件统计',675,255,545,340,28);
 text(s,'初态受控 ≠ 实际写入、保持、感放和恢复均已验证。',60,603,1160,54,29,C.orange,true);
}
{
 const s=slide('真实 SVisual 场图：保留完整原生窗口','无改动 own-window.png · 变量、色标、单位与 run 标题共同构成证据。','data/native-visual-review.json; native physical own-window source SHA 3c488a1571a23b36fa456db88639fb8c30d181c7d2c0d465c85176b79a454a98');
 await img(s,'native-physical-window.png',155,173,970,486);
}
{
 const s=slide('全 128 响应：结果依赖判据阈值','三阈值均保留数值不确定，不能把未定项算作正确。','responses.csv; summary.json.main_threshold_counts; numerical_boundary.main_threshold_status');
 const keys=['correct','criterion_error','critical','numerically_uncertain'];
 chart(s,'bar',{position:{left:60,top:190,width:805,height:435},categories:['2.5 mV','5 mV','10 mV'],series:keys.map((k,i)=>({name:['正确','判据误读','临界','数值不确定'][i],values:['2.5','5.0','10.0'].map(t=>results.threshold_counts[t][k]||0),fill:[C.blue,C.orange,'#AEBCC8',C.red][i]})),barOptions:{direction:'column',grouping:'stacked',gapWidth:90},hasLegend:true,legend:{position:'bottom',overlay:false,textStyle:{fontSize:23}},xAxis:axis,yAxis:{...axis,min:0,max:128,majorUnit:32,title:{text:'响应数',textStyle:{fontSize:23}},majorGridlines:{fill:'#E1E7EC',width:1}}});
 text(s,'5 mV 主阈值',901,204,320,55,30,C.blue,true);
 text(s,'96  正确\n20  判据误读\n  8  临界\n  4  数值不确定',901,282,320,275,32);
 text(s,'逻辑槽失败 / 缺失均为 0；完整历史 7 条 FAILED 仍在账本保留。',60,632,1160,36,23,C.muted);
}
{
 const s=slide('冻结模型在独立测试上优于均值基线','预测前冻结；每个 split / bit 的有效样本 n = 16，不进行测试后拟合。','final-numerical-prediction-scores.json.scores; original-r4-prediction-scores.json; data/frozen-models.json');
 const groups=[['holdout',0],['holdout',1],['extrapolation',0],['extrapolation',1]];
 chart(s,'bar',{position:{left:50,top:190,width:770,height:428},categories:['留出 b0','留出 b1','外推 b0','外推 b1'],series:['training_mean','ridge'].map((m,i)=>({name:i?'岭回归':'训练均值',values:groups.map(([a,b])=>sc(a,b,'deltaM_mV',m).RMSE),fill:i?C.teal:C.blue})),barOptions:{direction:'column',grouping:'clustered',gapWidth:90},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:23}},xAxis:axis,yAxis:{...axis,min:0,max:25,majorUnit:5,title:{text:'裕量损失 RMSE / mV',textStyle:{fontSize:23}},majorGridlines:{fill:'#E1E7EC',width:1}}});
 tbl(s,[['电荷 RMSE / fC','b0','b1'],['域内留出',fmt(sc('holdout',0,'deltaQ_fC').RMSE),fmt(sc('holdout',1,'deltaQ_fC').RMSE)],['尺寸外推',fmt(sc('extrapolation',0,'deltaQ_fC').RMSE),fmt(sc('extrapolation',1,'deltaQ_fC').RMSE)]],858,232,370,222,[174,98,98],23);
 text(s,'原 r4 与最终评分分文件保留；\n本次内容相同。\n残差图为 pooled 展示，\n分区结论以评分表为准。',858,492,368,149,24,C.muted);
}
{
 const s=slide('氧化层敏感性：固定入口下幅度较小','14 个新 case，4 / 6 nm；5 nm 复用主线响应，事件本身不变。','summary.json.oxide.responses; oxide-sensitivity.sources.json; extension-cases.csv');
 const combos=[['alpha',0],['alpha',1],['proton',0],['proton',1]];
 chart(s,'line',{position:{left:60,top:185,width:805,height:405},categories:['4 nm','5 nm','6 nm'],series:combos.map(([particle,bit],i)=>({name:(particle==='alpha'?'α':'proton')+' b'+bit,values:[4,5,6].map(n=>n===5?0:summary.oxide.responses.find(x=>x.event.particle===particle&&x.stored_bit===bit&&x.oxide_nm===n).differences_from_5nm.deltaM_V*1000),line:{fill:[C.blue,C.orange,C.teal,C.red][i],width:3},marker:{symbol:['circle','square','diamond','triangle'][i],size:8,fill:[C.blue,C.orange,C.teal,C.red][i]}})),lineOptions:{smooth:false},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:23}},xAxis:axis,yAxis:{...axis,min:-0.15,max:0.15,majorUnit:0.05,numberFormatCode:'0.00',title:{text:'ΔM 相对 5 nm 的变化 / mV',textStyle:{fontSize:23}},majorGridlines:{fill:'#E1E7EC',width:1}}});
 text(s,'最大绝对变化',905,199,310,58,30,C.blue,true);text(s,'0.11256 mV\n0.005784 fC',905,286,310,146,32);text(s,'分类保持\n固定硅入口事件\n不重算材料栈输运',905,463,310,146,26,C.muted);
 text(s,'小于验收容差，但容差不是误差条；未逐厚度独立细化或统计校准，不作微小效应显著性主张。',60,610,1160,60,23,C.muted);
}
{
 const s=slide('连续量通过，跨界类别仍不确定','完整 128 响应选定边界目标；两目标 × 半步长 / 0.7 网格。','summary.json.numerical_boundary.comparisons; numerical-status table; root-acceptance.json');
 tbl(s,[['目标 seed / 位','变化','最大读出差 / mV','连续门槛','类别'],...summary.numerical_boundary.comparisons.map(x=>[String(x.event.seed)+' / b'+x.stored_bit,x.variation.step===0.5?'半步长':'0.7 网格',fmt(Math.max(...Object.values(x.differences_V).map(Math.abs))*1000,6),x.continuous_passed?'通过':'失败',x.classification_stable?'稳定':'5 mV 跨界'])],60,197,1160,315,[268,190,292,180,230],24);
 text(s,'5 mV：1 项跨界 + 3 项未选近界 = 4 项数值不确定',60,541,1160,55,31,C.orange,true);
 text(s,'最大 |ΔQ 差| = 0.003490 fC；容差 0.5 mV / 0.01 fC。细化不增加独立 N。',60,616,1160,44,25,C.muted);
}
{
 const s=slide('失败、重试与成本完整保全','实际退出码未知保持 null；不将工程恢复改写为新的科学样本。','ledger-snapshot.json; original-failures.json; response-sources.json; raw-submission-index.json; summary.json.budget');
 tbl(s,[['审计对象','最终证据'],['全局历史 FAILED','7 条均保留'],['R50 主线别名恢复','4 项原逻辑槽，保留实际 owner / case-freeze'],['全部账本项目','224 tags；旧 206 项 + 新扩展 18 项'],['累计求解成本',fmt(summary.budget.accounted_solver_s,2)+' s ≈ '+fmt(summary.budget.accounted_solver_s/3600,4)+' h'],['当前授权 / 未结算','预算无上限；0 项未结算、0 项费用缺口']],60,193,1160,385,[370,790],25);
 text(s,'累计成本包含旧版本、probe、失败、重试和扩展，不是学生时长或 AI 效率对照。',60,613,1160,53,26,C.muted);
}
{
 const s=slide('结论与课程交付边界','技术证据完成；真实人类参与、审核和答辩据实登记。','course-report.tex; research-paper.tex; materials/index.md; docs/course-project-syllabus.md');
 text(s,'可以支持',60,188,540,57,34,C.blue,true);
 text(s,'一致的输入—源项—读出证据链\n完整矩阵与独立冻结预测评分\n保留不确定的数值边界审查\n可编辑报告、PPT 和只读演示',60,267,547,280,29);
 text(s,'仍需完成',680,188,540,57,34,C.orange,true);
 text(s,'真实工艺 / 电学与感放校准\n扩大能量、位置和样本范围\n2–3 名学生真实贡献与现场演示\n教师审核、试讲、答辩与考核',680,267,540,280,29);
 text(s,'研究结论止于固定输入与未校准二维模型；不替代真实 DRAM 辐射可靠性评价。',60,605,1160,60,27,C.muted);
}
{
 const s=slide('备份：冻结岭回归的分区误差','每行 n = 16；MAE / RMSE / 最大绝对误差来自最终评分原表。','final-numerical-prediction-scores.json.scores; prediction-scores.csv');
 const rows=scores.filter(x=>x.model==='ridge').map(x=>[x.split==='holdout'?'留出':'外推','b'+x.stored_bit,x.target==='deltaQ_fC'?'ΔQ / fC':'ΔM / mV',String(x.valid_n),fmt(x.MAE),fmt(x.RMSE),fmt(x.max_absolute_error)]);
 tbl(s,[['分区','位','目标','n','MAE','RMSE','最大误差'],...rows],60,185,1160,450,[120,90,200,80,218,218,234],24);
}
{
 const s=slide('备份：真实事件场图的完整窗口','α / 30° / seed 202610311 / bit 1 · 原始 own-window.png，不改像素。','data/native-visual-review.json; native event own-window source SHA b561a9c81fa63fc69b1956bcfaf667f0026c790d8cb5d46aafa910a707f8c846');
 await img(s,'native-event-window.png',155,173,970,486);
}
{
 const s=slide('备份：适用范围与可核查文献','文献提供方法背景，不等于本二维模型已经实验校准。','references.bib; reference-verification.json; reference-metadata.json; sections/paper/05-prediction-discussion.tex');
 text(s,'模型范围',60,187,520,50,32,C.blue,true);
 text(s,'二维等效深度与理想电容\n受控准静态初态\n5 MeV、两角度、固定入射位置\n所选 EM 物理不覆盖质子核反应\n每层 N = 4，有限外推范围',60,262,530,319,27);
 text(s,'引用入口',680,187,540,50,32,C.blue,true);
 text(s,'陈善强、师立勤（2011）\nTCAD / Geant4 SRAM 联合研究\nXu 等（2021），TED 68:5758–5764\nRyder 等（2021），TNS 68:626–633\nKeeth 与 Baker（2001），DRAM 设计\nGeant4 10.7 官方物理表文档',680,262,540,333,25);
 text(s,'完整 DOI、元数据与核查范围见 references.bib / reference-verification.json。',60,622,1160,43,24,C.muted);
}
{
 const s=slide('备份：只读演示与人工活动登记','使用已归档真实仿真，明确标注预先运行；本演示步骤不启动求解。','materials/demonstration.md; materials/handoff.md; evidence-index.csv; docs/course-project-syllabus.md');
 tbl(s,[['演示步骤','证据入口'],['1  请求预览 / 审计 / 定位','受约束自然语言请求及拒绝记录'],['2  原始来源','逻辑槽 → actual tag → owner → freeze → run'],['3  原始数据与指标','信号 / control / neutral，电荷与裕量定义'],['4  独立预测与边界','冻结时间、分区评分、跨界与未定状态'],['5  图件、失败与费用','DATA PLOT、原生窗口、原 FAILED / null、全账本']],60,181,1160,390,[420,740],24);
 text(s,'待人工：成员姓名 / 学号 / 真实分工、教师审核、资源交接、试讲、答辩、考核。',60,603,1160,60,26,C.orange,true);
}
if(p.slides.items.length!==16) throw Error('Slide count changed');
const candidate=path.join(out,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
await fs.writeFile(path.join(out,'authored-slides.json'),JSON.stringify(meta,null,2));
const final=path.join(HERE,'dram-see-v3-r4-'+tag+'.pptx');
await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath:final,pythonExecutable:PY,
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[4,8,10,11,13,16].flatMap(n=>['--require-native-table-slide',String(n)])],
 explicitTotalSlideCount:16,requiredNativeTableOwnerSlides:[4,8,10,11,13,16],requiredNativeChartOwnerSlides:[7,8,9],
 materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[F]},verifyArtifactToolImport:true,
 receiptPath:path.join(out,'validation.json')});
// Render the finalized file, not only the in-memory pre-finalizer candidate.
const finalPresentation=await PresentationFile.importPptx(await FileBlob.load(final));
for(let i=0;i<finalPresentation.slides.items.length;i++){
 const png=await finalPresentation.export({slide:finalPresentation.slides.items[i],format:'png',scale:1.5});
 await fs.writeFile(path.join(render,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
}
await fs.writeFile(path.join(out,'build-result.json'),JSON.stringify({state:'FINALIZED_AND_RENDERED_VISUAL_REVIEW_PENDING',final,render,slides:16,core_slides:12,backup_slides:4,new_solver_calls:0},null,2));
console.log(JSON.stringify({final,render,slides:16}));
