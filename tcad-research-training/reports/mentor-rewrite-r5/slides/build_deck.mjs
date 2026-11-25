// Author from accepted local evidence only. No solver or controller imports.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.resolve(HERE, '../assets');
const ROOT = path.resolve(HERE, '../../..');
const SKILL = process.env.PRESENTATIONS_SKILL_DIR || 'C:/Users/sun/.codex/plugins/cache/openai-primary-runtime/presentations/26.1009.11318/skills/presentations';
const RUNTIME = process.env.CODEX_ARTIFACT_RUNTIME || 'C:/Users/sun/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const PY = path.join(RUNTIME, 'python/python.exe');
process.env.RUNTIME_NODE_MODULES = path.join(RUNTIME, 'node/node_modules');
const { Presentation, PresentationFile, FileBlob } = await import(pathToFileURL(path.join(process.env.RUNTIME_NODE_MODULES, '@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const { finalizePresentation, applyPresentationChartFont, resolvePresentationFont } = await import(pathToFileURL(path.join(SKILL, 'container_tools/artifact_tool_utils.mjs')).href);
const tag = process.argv[2];
if (!tag || !/^[A-Za-z0-9_-]+$/.test(tag)) throw Error('Use a new, safe revision tag');
const out = path.join(HERE, 'qa', tag);
await fs.mkdir(path.join(HERE, 'qa'), { recursive: true });
await fs.mkdir(out, { recursive: false });
const render = path.join(out, 'render'); await fs.mkdir(render);
const finalDir = path.join(HERE, 'output'); await fs.mkdir(finalDir, { recursive: true });
const sourceFiles = new Map();
const digest = data => crypto.createHash('sha256').update(data).digest('hex');
const builderHash = digest(await fs.readFile(fileURLToPath(import.meta.url)));
async function source(relative) {
  const file = path.join(ASSETS, relative); const bytes = await fs.readFile(file);
  sourceFiles.set(file, digest(bytes)); return bytes;
}
const summary = JSON.parse(await source('data/snapshot/summary.json'));
const results = JSON.parse(await source('data/writing-results.json'));
const failures = JSON.parse(await source('data/snapshot/original-failures.json'));
const binding = JSON.parse(await source('data/snapshot-binding.json'));
const referencePath = path.join(HERE, 'source-deck-reference.json');
const referenceBytes = await fs.readFile(referencePath); const reference = JSON.parse(referenceBytes);
sourceFiles.set(referencePath, digest(referenceBytes));
const sourceDeckPath = process.env.MENTOR_SOURCE_DECK || path.join(ROOT, 'reports/final-r4/dram-see-v3-r4-r4.pptx');
let sourceInspection;
let sourceDeckBytes;
try { sourceDeckBytes = await fs.readFile(sourceDeckPath); }
catch (error) { if(error.code!=='ENOENT') throw error; }
if(sourceDeckBytes) {
  if(digest(sourceDeckBytes)!==reference.sha256) throw Error('Original deck differs from the inspected reference');
  const original = await PresentationFile.importPptx(await FileBlob.load(sourceDeckPath));
  sourceInspection={path:sourceDeckPath,sha256:digest(sourceDeckBytes),slides:original.slides.items.length,inspected_now:true,inspection:await original.inspect({kind:'slide,layout',maxChars:16000})};
} else {
  sourceInspection={...reference,inspected_now:false,reason:'Packaged rebuild uses copied assets and the recorded source reference. Original PPTX is optional.'};
}
await fs.writeFile(path.join(out, 'source-inspection.json'), JSON.stringify(sourceInspection,null,2));
if(summary.measured_main_responses!==128 || summary.planned_independent_events!==64 || sourceInspection.slides!==16) throw Error('Unexpected source inventory');
if(JSON.stringify(results.main_threshold_counts)!==JSON.stringify({correct:96,criterion_error:20,critical:8,numerically_uncertain:4,failed:0,missing:0})) throw Error('Main classification differs');
if(failures.failure_log.length!==7) throw Error('Original failure inventory differs');
const p = Presentation.create({slideSize:{width:1280,height:720}});
const F = 'Microsoft YaHei';
await resolvePresentationFont({fontFamily:F});
const C = {ink:'#172E3A', blue:'#287A9A', coral:'#CC7053', green:'#367C70', gold:'#D5A34A', purple:'#83749E', muted:'#677A83', soft:'#EDF2F4', white:'#FFFFFF'};
const meta=[]; const tableOwners=[]; const chartOwners=[];
function text(slide,value,x,y,w,h,size=28,color=C.ink,bold=false) {
  const q=slide.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  q.text=value; q.text.style={fontSize:size,typeface:F,bold,color,alignment:'left',verticalAlignment:'top',insets:0,wrap:'word',autoFit:'none'};
  meta.at(-1).text.push(value); return q;
}
function slide(title,subtitle,notes,sourceRefs,backup=false) {
  const s=p.slides.add(); s.background.fill=C.white;
  const n=p.slides.items.length;
  meta.push({slide:n,title,backup,text:[],notes,sourceRefs});
  text(s,title,60,38,1160,74,44,C.ink,true);
  if(subtitle) text(s,subtitle,60,116,1160,55,25,C.muted);
  text(s,backup?'补充资料':'DRAM 单粒子效应研究',60,682,1070,22,15,C.muted);
  text(s,String(n),1165,682,55,22,15,C.muted);
  s.speakerNotes.text=notes+'\n\n来源：'+sourceRefs.join('；')+'。';
  return s;
}
function table(s,values,x,y,w,h,widths,size=25) {
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
  t.borders.assign({style:'solid',fill:'#CED9DE',width:1});
  for(let r=0;r<values.length;r++) for(let c=0;c<values[r].length;c++) {
    const cell=t.getCell(r,c); cell.fill=r===0?C.ink:(r%2?C.white:C.soft);
    cell.text.style={typeface:F,fontSize:size,color:r===0?C.white:C.ink,bold:r===0,alignment:'left',verticalAlignment:'middle',insets:10};
  }
  tableOwners.push(p.slides.items.length); meta.at(-1).tables??=[]; meta.at(-1).tables.push(values); return t;
}
async function image(s,name,x,y,w,h) {
  const b=await source('figures/'+name);
  s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:name,fit:'contain',position:{left:x,top:y,width:w,height:h}});
  meta.at(-1).images??=[]; meta.at(-1).images.push({name,sha256:digest(b),unchanged:true});
}
function chart(s,type,config) {
  // Literal data are complete snapshots, rounded only for native chart compatibility.
  for(const series of config.series) series.values=series.values.map(v=>v===null?null:Number(v.toFixed(6)));
  const c=s.charts.add(type,{chartFill:C.white,plotAreaFill:C.white,...config}); applyPresentationChartFont(c,{fontFamily:F});
  chartOwners.push(p.slides.items.length); meta.at(-1).charts??=[]; meta.at(-1).charts.push({type,config}); return c;
}
const axis={textStyle:{fontSize:22,fill:C.muted},line:{fill:'#CAD6DC',width:1},majorGridlines:null};
const grid={fill:'#E0E7EA',width:1};
const fmt=(n,d=4)=>Number(n).toFixed(d);
const scores=summary.final_numerical_prediction_scores.scores;
const score=(split,bit,target,model='ridge')=>scores.find(r=>r.split===split&&r.stored_bit===bit&&r.target===target&&r.model===model);
const rmseRows=[['电荷变化（fC）',0,'deltaQ_fC'],['电荷变化（fC）',1,'deltaQ_fC'],['裕量变化（mV）',0,'deltaM_mV'],['裕量变化（mV）',1,'deltaM_mV']];

{
  const s=slide('AI辅助下的多特征尺寸\n存储器单粒子效应评估','',
    '研究对象是1T1C DRAM单元。项目比较4种栅长在α粒子和质子入射后的电荷变化与读出结果，并用仿真数据训练预测模型。AI助手参与条件整理、脚本编写、运行调度和结果分析。机器学习预测另由4个岭回归模型完成。',
    ['../assets/data/snapshot/summary.json','../assets/data/frozen-models.json']);
  // Two-line cover title has a dedicated larger frame.
  s.shapes.items[0].position.height=150;
  text(s,'项目汇报',60,223,1160,50,28,C.blue,true);
  text(s,'比较不同栅长的电荷变化和读出结果，\n用仿真数据训练并检验预测模型。',60,304,1160,108,34);
  const labels=[['4','种栅长'],['64','个独立粒子事件'],['128','次存储响应']];
  labels.forEach(([value,label],i)=>{text(s,value,60+i*394,472,340,100,74,C.blue,true);text(s,label,60+i*394,578,340,45,28,C.muted);});
}
{
  const s=slide('研究内容','以1T1C DRAM单元为对象，计算粒子入射后的电荷与读出响应。',
    'Geant4计算粒子在材料中的能量沉积。项目将硅中的电离沉积映射到器件仿真源项，再由Sentaurus TCAD计算存储单元响应。同一事件分别计算存储0和存储1。分析采用同条件对照和中性参考。AI助手支持脚本与数据处理，预测模型使用本项目产生的仿真数据。',
    ['../assets/data/snapshot/report.md','../assets/data/snapshot/summary.json.design']);
  const rows=[['粒子输运','Geant4计算材料中的能量沉积'],['存储单元响应','Sentaurus TCAD计算电荷和读出变化'],['数据分析','比较不同栅长、粒子和入射角度'],['模型预测','用已有尺寸的数据预测测试尺寸的结果']];
  rows.forEach(([label,detail],i)=>{text(s,label,60,209+i*98,285,60,31,C.blue,true);text(s,detail,378,212+i*98,840,70,29);});
  text(s,'AI助手参与条件整理、脚本编写、运行调度和结果分析。',60,622,1160,43,25,C.muted);
}
{
  const s=slide('参数设置','每个粒子事件分别计算存储0和存储1，共64个事件、128次响应。',
    '训练集包含0.18和0.35 μm两个栅长，共32个独立事件、64次响应。0.25 μm用于尺寸区间内测试，0.45 μm用于区间外测试，各16个独立事件、32次响应。每组栅长、粒子与角度有4个独立种子。重试与补充计算不增加独立事件数。名义氧化层厚度为5 nm，位线预充电电阻为50 Ω。',
    ['../assets/data/snapshot/summary.json.design','../assets/data/snapshot/statistics.csv']);
  table(s,[['用途','栅长（μm）','事件','响应'],['训练','0.18、0.35','32','64'],['区间内测试','0.25','16','32'],['区间外测试','0.45','16','32'],['合计','4种','64','128']],60,208,727,360,[220,247,130,130],27);
  text(s,'共同条件',835,208,380,50,31,C.blue,true);
  text(s,'α粒子、质子\n能量均为5 MeV\n入射角度0°、30°\n每组使用4个独立种子\n名义氧化层厚度5 nm',835,282,380,294,28);
}
{
  const s=slide('电荷与读出','电荷变化反映入射影响，读出裕量用于判断存储值能否正确读出。',
    '电荷指标ΔQ=Cs×(SNsig−SNctl)，在2.8 ns计算，Cs=10 fF。读出差D=BLsig−BLneu，裕量M=(2b−1)D，裕量变化ΔM=Mctl−M，在4 ns计算。sig为粒子信号，ctl为同位对照，neu为同条件中性参考。M>ε为正确，M<−ε为判据误读，|M|≤ε为临界，数值不确定独立列出。判据误读指当前读出判据下的结果，不代表实际感放锁存或持久位翻转。',
    ['../assets/data/snapshot/report.md','../assets/tables/thresholds.tex']);
  table(s,[['观察量','计算时刻','比较对象'],['电荷变化','2.8 ns','粒子入射与无粒子对照'],['读出裕量','4 ns','信号位线与中性参考']],60,211,1160,244,[300,235,625],29);
  text(s,'5 mV主判据',60,499,340,51,31,C.blue,true);
  text(s,'高于5 mV：正确读出\n低于−5 mV：判据误读',60,565,565,84,28);
  text(s,'±5 mV以内：临界\n数值不确定另行统计',688,565,532,84,28);
}
{
  const s=slide('仿真结果','全部128次主实验响应完成。主判据取5 mV。',
    '5 mV判据下为96项正确读出、20项判据误读、8项临界及4项数值不确定。图中同时给出2.5和10 mV判据，分别为96/27/4/1与96/5/26/1，顺序为正确、误读、临界、不确定。4项不确定的来源见边界验证页。所有统计均使用同一组128次响应，工程失败保留在历史记录中。',
    ['../assets/data/writing-results.json.threshold_counts','../assets/data/snapshot/responses.csv']);
  const keys=['correct','criterion_error','critical','numerically_uncertain'];
  chart(s,'bar',{position:{left:50,top:205,width:845,height:431},categories:['2.5 mV','5 mV','10 mV'],series:keys.map((key,i)=>({name:['正确读出','判据误读','临界','数值不确定'][i],values:['2.5','5.0','10.0'].map(t=>results.threshold_counts[t][key]||0),fill:[C.green,C.coral,C.gold,C.purple][i]})),barOptions:{direction:'column',grouping:'stacked',gapWidth:90},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:22}},xAxis:axis,yAxis:{...axis,min:0,max:128,majorUnit:32,title:{text:'响应数',textStyle:{fontSize:22}},majorGridlines:grid}});
  text(s,'5 mV统计',935,214,285,55,30,C.blue,true);
  [['96','正确读出',C.green],['20','判据误读',C.coral],['8','临界',C.gold],['4','数值不确定',C.purple]].forEach(([n,label,color],i)=>{text(s,n,935,304+i*75,91,56,36,color,true);text(s,label,1030,313+i*75,195,49,26);});
}
{
  const s=slide('粒子入射后的电场分布','α粒子，30°入射，存储1。图中保留原始变量、单位和色标。',
    '此图为SVisual原生窗口截图，显示0.18 μm单元在4 ns时的电场幅值。事件seed为202610311，存储1。图像为原始native-event-window.png完整窗口，仅按比例置入幻灯片。电场图用于查看空间分布，读出状态由位线曲线和中性参考计算。',
    ['../assets/figures/native-event-window.png','../assets/data/native-visual-review.json']);
  await image(s,'native-event-window.png',122,178,1036,488);
}
{
  const s=slide('模型训练与验证','采用4个岭回归模型，分别预测两种存储状态下的电荷和裕量变化。',
    '四个Ridge模型按存储位与目标分别训练：存储0的ΔQ、存储0的ΔM、存储1的ΔQ、存储1的ΔM。64次训练响应来自0.18和0.35 μm。超参数通过训练集内部按事件分组的交叉验证选择。模型及64条测试响应预测在测试求解前固定。每条响应预测包含电荷与裕量两个目标。测试只读取已固定预测，不重新拟合。',
    ['../assets/data/frozen-models.json','../assets/data/snapshot/original-r4-prediction-scores.json','../assets/tables/training-cv.tex']);
  table(s,[['存储状态','预测目标','模型数'],['存储0','电荷变化、裕量变化','2'],['存储1','电荷变化、裕量变化','2']],60,212,702,262,[200,360,142],28);
  const steps=[['训练','64次响应，0.18和0.35 μm'],['保存预测','固定模型及64条测试预测'],['测试','64次响应，0.25和0.45 μm']];
  steps.forEach(([a,b],i)=>{text(s,a,815,207+i*125,400,48,30,C.blue,true);text(s,b,815,268+i*125,400,73,26);});
  text(s,'测试仿真开始前已保存预测值。',60,547,700,57,31,C.blue,true);
}
{
  const s=slide('预测误差','两种测试栅长上，4个模型的误差均小于训练均值方法的误差。',
    '左图比较裕量变化的均方根误差。训练均值方法对每个目标采用相应训练集目标的平均值。右表为4个模型在两种测试栅长上的RMSE，每个模型、每种测试栅长有16个响应。完整MAE、RMSE和最大绝对误差见补充资料。图表数值由最终评分文件读取，展示舍入不修改原评分。',
    ['../assets/data/snapshot/final-numerical-prediction-scores.json','../assets/data/snapshot/prediction-scores.csv']);
  const groups=[['holdout',0],['holdout',1],['extrapolation',0],['extrapolation',1]];
  chart(s,'bar',{position:{left:45,top:225,width:715,height:405},categories:['0.25 存储0','0.25 存储1','0.45 存储0','0.45 存储1'],series:['training_mean','ridge'].map((model,i)=>({name:i?'岭回归':'训练均值',values:groups.map(([a,b])=>score(a,b,'deltaM_mV',model).RMSE),fill:i?C.blue:'#B8C9D1'})),barOptions:{direction:'column',grouping:'clustered',gapWidth:90},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:22}},xAxis:{...axis,textStyle:{fontSize:19,fill:C.muted}},yAxis:{...axis,min:0,max:25,majorUnit:5,title:{text:'裕量变化RMSE（mV）',textStyle:{fontSize:22}},majorGridlines:grid}});
  text(s,'岭回归的RMSE',800,205,420,45,28,C.blue,true);
  table(s,[['目标／状态','0.25 μm','0.45 μm'],...rmseRows.map(([a,b,t])=>[a+'\n存储'+b,fmt(score('holdout',b,t).RMSE),fmt(score('extrapolation',b,t).RMSE)])],800,277,420,340,[194,113,113],20);
}
{
  const s=slide('氧化层试验','完成14项补充计算，比较4、5、6 nm氧化层厚度。',
    '14项新计算包含8项信号、4项对照和2项中性参考，5 nm基线复用主实验结果。固定0.25 μm、0°入射和硅入口事件，比较4和6 nm相对5 nm的变化。最大绝对裕量变化约0.11256 mV，最大绝对电荷变化约0.005784 fC，分类保持。此比较固定硅入口，不重算各厚度材料堆栈的粒子输运。未逐厚度独立细化，不将微小差异表述为统计显著效应。',
    ['../assets/data/snapshot/summary.json.oxide','../assets/tables/oxide.tex','../assets/data/snapshot/extension-cases.csv']);
  const combos=[['alpha',0],['alpha',1],['proton',0],['proton',1]];
  chart(s,'line',{position:{left:50,top:204,width:815,height:414},categories:['4 nm','5 nm','6 nm'],series:combos.map(([particle,bit],i)=>({name:(particle==='alpha'?'α粒子':'质子')+' 存储'+bit,values:[4,5,6].map(n=>n===5?0:summary.oxide.responses.find(x=>x.event.particle===particle&&x.stored_bit===bit&&x.oxide_nm===n).differences_from_5nm.deltaM_V*1000),line:{fill:[C.blue,C.coral,C.green,C.purple][i],width:3},marker:{symbol:['circle','square','diamond','triangle'][i],size:8,fill:[C.blue,C.coral,C.green,C.purple][i]}})),lineOptions:{smooth:false},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:21}},xAxis:axis,yAxis:{...axis,min:-0.15,max:0.15,majorUnit:0.05,numberFormatCode:'0.00',title:{text:'相对5 nm的裕量变化（mV）',textStyle:{fontSize:22}},majorGridlines:grid}});
  text(s,'最大绝对变化',913,214,307,50,29,C.blue,true);
  text(s,'0.11256 mV',913,302,307,62,35);
  text(s,'0.005784 fC',913,379,307,62,35);
  text(s,'读出分类保持不变',913,495,307,75,28,C.green,true);
  text(s,'比较使用相同的硅入口事件。5 nm沿用主实验结果。',60,630,1160,38,24,C.muted);
}
{
  const s=slide('边界验证','从全部128次响应中选取2个近边界目标，分别减小时间步和网格尺寸。',
    '两目标为seed 202610304与202610313，均为存储1，来自完整128响应的距离排名。各执行半时间步和0.7网格尺度，合计4项补充计算。连续量验收容差为0.5 mV与0.01 fC，4项比较均通过，最大电荷差约0.003490 fC。202610304的半步长结果在5 mV判据处跨界。主实验中，这1项与另外3项近边界响应均列为数值不确定。这里的4项指主实验响应，不是表中的4次细化计算。细化不增加独立事件数。',
    ['../assets/data/snapshot/summary.json.numerical_boundary','../assets/tables/boundary.tex','../assets/tables/numerical-status.tex']);
  table(s,[['目标','细化方式','最大电压差（mV）','连续量检查'],...summary.numerical_boundary.comparisons.map(x=>[String(x.event.seed)+'／存储'+x.stored_bit,x.variation.step===0.5?'时间步减半':'网格尺寸×0.7',fmt(Math.max(...Object.values(x.differences_V).map(Math.abs))*1000,6),x.continuous_passed?'通过':'未通过'])],60,216,1160,326,[329,279,322,230],25);
  text(s,'1项在5 mV判据处跨界。另有3项近界响应尚未细化。',60,580,1160,51,29,C.coral,true);
  text(s,'主实验中，这1项与另外3项近边界响应均列为数值不确定。',60,636,1160,35,24,C.muted);
}
{
  const s=slide('结论与后续工作','',
    '本阶段完成4种栅长、64个独立粒子事件与128次配对存储响应，模型和预测在测试前固定。两种测试尺寸的4个模型误差均低于训练均值方法的误差。后续研究需要实际工艺和电学参数校准、感放模型校准，并扩展能量、位置与样本范围。当前二维仿真用于比较设定条件下的响应，不能直接推断商业DRAM辐射可靠性。',
    ['../assets/data/snapshot/summary.json','../assets/data/snapshot/report.md']);
  text(s,'已完成的研究',60,202,1120,53,32,C.blue,true);
  text(s,'完成4种栅长的仿真比较，获得128次存储响应。\n两种测试栅长上，4个模型的误差均小于训练均值方法的误差。',60,279,1160,143,31);
  text(s,'后续工作',60,456,1120,53,32,C.blue,true);
  text(s,'校准器件电学与感放模型，扩大粒子能量、入射位置和样本范围。',60,531,1160,96,31);
  text(s,'结论限于当前二维模型与入射条件。',60,635,1160,35,24,C.muted);
}
{
  const s=slide('模型误差明细','每行含16个测试响应。误差单位随预测目标列出。',
    '补充表列出4个岭回归模型在区间内和区间外测试上的MAE、RMSE及最大绝对误差。表中的0.25 μm对应holdout，0.45 μm对应extrapolation。均为最终评分原表中的有效样本数与指标。',
    ['../assets/data/snapshot/final-numerical-prediction-scores.json','../assets/data/snapshot/prediction-scores.csv'],true);
  const rows=scores.filter(r=>r.model==='ridge').map(r=>[r.split==='holdout'?'0.25':'0.45','存储'+r.stored_bit,r.target==='deltaQ_fC'?'电荷变化／fC':'裕量变化／mV',fmt(r.MAE),fmt(r.RMSE),fmt(r.max_absolute_error)]);
  table(s,[['栅长（μm）','状态','预测目标','MAE','RMSE','最大误差'],...rows],60,204,1160,436,[190,145,225,190,190,220],24);
}
{
  const s=slide('运行记录','原失败记录和重试记录分别保存，独立事件总数保持64个。',
    '全局历史保留7条FAILED。R50主线4项重试采用明确alias，保留原失败与null退出码，不将未知退出码补为0。原逻辑响应仍只有128项，工程重试与确定性扩展均不增加独立科学样本。全账本包含224条记录，旧206条加扩展18条，累计求解时间包括原失败、重试、旧版本和扩展。来源与实际run映射保存在response-sources.json、sources.json、raw-submission-index.json及original-failures.json。绑定快照的SHA256为'+binding.source_manifest_sha256+'。',
    ['../assets/data/snapshot/original-failures.json','../assets/data/snapshot/ledger-snapshot.json','../assets/data/snapshot/response-sources.json','../assets/data/snapshot/sources.json'],true);
  table(s,[['记录','保留情况'],['历史失败','7条FAILED均保留'],['主实验重试','4项，原失败及未知退出码null保留'],['全账本','224条记录，含18项补充计算'],['累计求解时间',fmt(summary.budget.accounted_solver_s,2)+' s，约'+fmt(summary.budget.accounted_solver_s/3600,2)+' h']],60,220,1160,351,[360,800],28);
  text(s,'累计时间包含失败和重试，用于记录计算资源消耗。',60,614,1160,45,27,C.muted);
}
{
  const s=slide('参考电场分布','0.18 μm单元，存储1，4 ns时的电场幅值。',
    '此图为物理参考计算的SVisual原生完整窗口，来源native-physical-window.png。变量为Abs(ElectricField-V)，单位V/cm，坐标单位μm。它与主报告中的粒子事件电场图属于不同计算，不能仅凭图像色彩推断电荷收集或读出分类。完整参考文献见../assets/references.bib。',
    ['../assets/figures/native-physical-window.png','../assets/data/native-visual-review.json','../assets/references.bib'],true);
  await image(s,'native-physical-window.png',122,178,1036,488);
}
if(p.slides.items.length!==14) throw Error('Unexpected authored slide count');
for(const [file,hash] of sourceFiles) if(digest(await fs.readFile(file))!==hash) throw Error('Source changed while authoring: '+file);
const candidate=path.join(out,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
const final=path.join(finalDir,'dram-see-v3-mentor-'+tag+'.pptx');
await finalizePresentation({workspaceDir:HERE,candidatePath:candidate,finalPath:final,pythonExecutable:PY,
  integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[...new Set(tableOwners)].flatMap(n=>['--require-native-table-slide',String(n)])],
  explicitTotalSlideCount:14,requiredNativeTableOwnerSlides:[...new Set(tableOwners)],requiredNativeChartOwnerSlides:[...new Set(chartOwners)],
  materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[F]},verifyArtifactToolImport:true,
  receiptPath:path.join(out,'validation.json')});
const finalized=await PresentationFile.importPptx(await FileBlob.load(final));
for(let i=0;i<finalized.slides.items.length;i++) {
  const png=await finalized.export({slide:finalized.slides.items[i],format:'png',scale:1.5});
  await fs.writeFile(path.join(render,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
}
await fs.writeFile(path.join(HERE,'slides-text-'+tag+'.json'),JSON.stringify(meta,null,2));
await fs.writeFile(path.join(HERE,'slides-text-'+tag+'.md'),meta.map(r=>'## '+r.slide+' '+r.title.replaceAll('\n',' ')+'\n\n'+r.text.filter(t=>![r.title,String(r.slide),'DRAM 单粒子效应研究','补充资料'].includes(t)).join('\n\n')+(r.tables?'\n\n'+r.tables.map(t=>t.map(row=>row.join(' / ')).join('\n')).join('\n\n'):'')+'\n\n备注：'+r.notes+'\n\n来源：'+r.sourceRefs.join('；')).join('\n\n'));
if(digest(await fs.readFile(fileURLToPath(import.meta.url)))!==builderHash) throw Error('Builder changed while executing');
await fs.writeFile(path.join(out,'source-manifest.json'),JSON.stringify({builder_sha256:builderHash,source_deck:{path:sourceDeckPath,sha256:reference.sha256,inspected_now:sourceInspection.inspected_now},files:Object.fromEntries(sourceFiles),native_table_slides:[...new Set(tableOwners)],native_chart_slides:[...new Set(chartOwners)]},null,2));
await fs.writeFile(path.join(out,'build-result.json'),JSON.stringify({state:'FINALIZED_AND_RENDERED_AWAITING_VISUAL_REVIEW',final,render,slides:14,main_slides:11,backup_slides:3,new_solver_calls:0},null,2));
console.log(JSON.stringify({final,render,slides:14}));
