from __future__ import annotations
import csv, hashlib, json, re
from pathlib import Path
import fitz
ROOT=Path(r'E:\TCAD-Workspace\tcad-research-training')
BASE=ROOT/'reports/final-r4'
DOCS=ROOT/'reports/mentor-rewrite-r5/documents'
OUT=ROOT/'reports/mentor-rewrite-r5/qa/validation'
EXPECTED={'course-report.pdf':('6184305978bca9c56a6e044c5710a7ee0cde96f66743a62311dbdaf64a3a241f',14),'research-paper.pdf':('114d51e022c814c72cb132528cc4d0253a99c03ba5f39f56fc23af44b8250ace',9)}
checks=[]; failures=[]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def ck(label,ok,detail=None):
 checks.append({'check':label,'passed':bool(ok),'detail':detail})
 if not ok: failures.append(label)
def j(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
texts={}; pdf_info={}
for name,(want,pages) in EXPECTED.items():
 p=DOCS/name; d=fitz.open(p); text='\n'.join(page.get_text() for page in d); digest=sha(p)
 texts[name]=text; pdf_info[name]={'sha256':digest,'pages':d.page_count}
 ck(name+'_hash_and_page_count',digest==want and d.page_count==pages,pdf_info[name])
 ck(name+'_no_unresolved_question_mark_refs','??' not in text)
render=j(DOCS/'qa/r5/render-manifest.json'); page_hashes=[]
for entry in render['documents']:
 p=DOCS/entry['pdf']; digest=sha(p); pages=fitz.open(p).page_count
 ck(entry['pdf']+'_r5_render_binding',digest==entry['sha256'] and pages==entry['pages'],{'sha256':digest,'pages':pages})
 for rel,expected in entry['images'].items():
  q=DOCS/rel; actual=sha(q) if q.is_file() else None
  page_hashes.append({'path':rel,'expected':expected,'actual':actual,'matches':expected==actual})
ck('r5_rendered_pages_match_manifest',len(page_hashes)==23 and all(x['matches'] for x in page_hashes),{'count':len(page_hashes),'mismatches':[x['path'] for x in page_hashes if not x['matches']]})
course=texts['course-report.pdf']; paper=texts['research-paper.pdf']
course_tex=(DOCS/'course-report.tex').read_text(encoding='utf-8'); paper_tex=(DOCS/'research-paper.tex').read_text(encoding='utf-8'); score=(DOCS/'score-table.tex').read_text(encoding='utf-8')
brief_path=ROOT/'reports/mentor-brief-r4/visual-v3/project-brief.tex'; brief_tex=brief_path.read_text(encoding='utf-8'); materials_path=ROOT/'reports/mentor-rewrite-r5/materials/course-materials.tex'; materials_tex=materials_path.read_text(encoding='utf-8')
responses=rows(BASE/'data/snapshot/responses.csv'); scores=rows(BASE/'data/snapshot/prediction-scores.csv'); extensions=rows(BASE/'data/snapshot/extension-cases.csv'); summary=j(BASE/'data/snapshot/summary.json'); models=j(BASE/'data/frozen-models.json')
events={r['event_label'] for r in responses}; paired=all({r['stored_bit'] for r in responses if r['event_label']==e}=={'0','1'} for e in events)
ck('64_independent_events_128_paired_responses',len(events)==64 and len(responses)==128 and paired,{'events':len(events),'responses':len(responses),'paired':paired})
counts=summary['main_threshold_counts']; expected_counts={'correct':96,'criterion_error':20,'critical':8,'numerically_uncertain':4}
ck('source_5mV_counts_96_20_8_4',all(counts.get(k)==v for k,v in expected_counts.items()),{k:counts.get(k) for k in expected_counts})
for name,text in [('course',course),('paper',paper),('brief',brief_tex),('materials',materials_tex)]:ck(name+'_threshold_counts_96_20_8_4',all(x in text for x in ('96','20','8','4')))
model_records=models['models']; config=models['configuration']; features=['Qdep_fC','Qdep_fC/L_um','Qdep_fC*sin(theta)']
ck('64_train_responses_four_models_32_each_lambda_01',models.get('train_paired_responses')==64 and len(model_records)==4 and all(v.get('training_response_n')==32 and v.get('selected_alpha')==.1 for v in model_records.values()),{'train_responses':models.get('train_paired_responses'),'models':{k:{'n':v.get('training_response_n'),'lambda':v.get('selected_alpha')} for k,v in model_records.items()}})
ck('three_features_and_train_holdout_extrapolation',models.get('feature_names')==features and config.get('train_lengths_um')==[.18,.35] and config.get('holdout_lengths_um')==[.25] and config.get('extrapolation_lengths_um')==[.45],models.get('feature_names'))
folds={k:[(len(f.get('training_event_labels',[])),len(f.get('validation_event_labels',[]))) for f in v.get('cv_folds',[])] for k,v in model_records.items()}
ck('four_models_each_8_loco_folds_28_plus_4',all(len(v)==8 and all(a==28 and b==4 for a,b in v) for v in folds.values()),folds)
rmse={ (r['target'],r['stored_bit'],r['split']):f"{float(r['RMSE']):.4f}" for r in scores if r['model']=='ridge' and r['split'] in {'holdout','extrapolation'} }
vals=sorted(rmse.values()); ck('eight_test_rmse_values_in_score_data',len(vals)==8,vals)
for name,text in [('score_table',score),('course_pdf',course),('paper_pdf',paper)]:ck(name+'_all_eight_rmse',all(v in text for v in vals),vals)
ck('both_tex_sources_include_shared_score_table',r'\scoretable' in course_tex and r'\scoretable' in paper_tex)
oxide=[r for r in extensions if r['stage']=='oxide']; b_rows=[r for r in extensions if r['stage']=='boundary' and r['role']=='event']; b_objects={re.sub(r'-s(?:0p5-m1|1-m0p7)$','',r['tag']) for r in b_rows}; crossings=[x for x in summary['numerical_boundary']['comparisons'] if not x['classification_stable']]
ck('14_oxide_rows_2_boundary_objects_1_crossing',len(oxide)==14 and len(b_objects)==2 and len(crossings)==1,{'oxide':len(oxide),'boundary_objects':sorted(b_objects),'crossing_events':[x['event']['label'] for x in crossings]})
for name,text in [('course',course),('paper',paper),('materials',materials_tex)]:ck(name+'_extension_facts_including_crossing',('14' in text and '边界' in text and '跨界' in text))
ck('brief_extension_counts_without_overclaiming_crossing_detail','14' in brief_tex and '边界' in brief_tex and '2' in brief_tex and '响应' in brief_tex)
aliases=j(BASE/'data/snapshot/original-failures.json')['alias_originals']; alias_evidence={k:{'state':v.get('state'),'runner_exit_code':v.get('runner_exit_code')} for k,v in aliases.items()}
ck('four_original_aliases_failed_null',len(aliases)==4 and all(v['state']=='FAILED' and v['runner_exit_code'] is None for v in alias_evidence.values()),alias_evidence)
for name,text in [('course',course),('paper',paper),('course_source',course_tex),('paper_source',paper_tex)]:ck(name+'_unknown_failure_codes_preserved','FAILED' in text and 'null' in text)
refs={}
for name,pdftext,source in [('course-report',course,course_tex),('research-paper',paper,paper_tex)]:
 bbl=(DOCS/'qa/r5'/f'{name}.bbl').read_text(encoding='utf-8',errors='replace'); log=(DOCS/'qa/r5'/f'{name}.log').read_text(encoding='utf-8',errors='replace')
 n=len(re.findall(r'\\bibitem\b',bbl)); cites=re.findall(r'\\cite\{([^}]+)\}',source); undefined=bool(re.search(r'undefined references|Citation .* undefined|There were undefined',log,re.I))
 refs[name]={'bibitem_count':n,'cite_commands':cites,'undefined_warnings':undefined}; ck(name+'_bibliography_nonempty_refs_resolved',n>0 and bool(cites) and not undefined and '参考文献' in pdftext,refs[name])
ck('brief_current_hash',sha(brief_path)=='0033a73c8d0ebe9f42355b68b3b6e7aac90354f1e859793d35a96e880820f1be',sha(brief_path))
ck('materials_source_unchanged',sha(materials_path)=='a279aeedf62ad503817c5fa0ed3889a7165cd238d34258a6044f363b3629678a',sha(materials_path))
ppt=ROOT/'reports/mentor-rewrite-r5/slides/output/dram-see-v3-mentor-r4.pptx'; pptqa=j(ROOT/'reports/mentor-rewrite-r5/slides/qa/r4/content-verification.json'); pptrev=j(ROOT/'reports/mentor-rewrite-r5/slides/qa/r4/revision-comparison.json')
ck('reuse_existing_ppt_content_qa',pptqa.get('state')=='PASS' and pptqa.get('final_sha256')==sha(ppt) and pptrev.get('state')=='PASS',{'ppt_sha256':sha(ppt),'content':pptqa.get('state'),'revision':pptrev.get('state')})
result={'schema':'mentor-rewrite-r5-repository-content-validation-v1','status':'PASS' if not failures else 'FAIL','checks':checks,'failures':failures,'pdfs':pdf_info,'brief_tex_sha256':sha(brief_path),'materials_tex_sha256':sha(materials_path),'pptx_sha256':sha(ppt),'r5_render_manifest_sha256':sha(DOCS/'qa/r5/render-manifest.json'),'page_render_hashes':page_hashes,'facts':{'rmse':{'/'.join(k):v for k,v in rmse.items()},'threshold_counts':{k:counts.get(k) for k in expected_counts},'cv_folds':folds,'boundary_crossing_count':len(crossings),'aliases':alias_evidence,'references':refs},'scope':['Repository-source/PDF/QA text, hash and frozen-snapshot checks only; no reading or writing of the user-edited external package.','No simulations, solver, model fitting, compilation or visual review; root owns the visual checks.','Final-package receipt/hash/copy validation is paused pending root identification of the authoritative user-edited report file.']}
OUT.mkdir(parents=True,exist_ok=True); out=OUT/'repository-content-validation.json'; out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':result['status'],'checks':len(checks),'failures':failures,'pdfs':pdf_info,'output':str(out.relative_to(ROOT))},ensure_ascii=False,indent=2)); raise SystemExit(1 if failures else 0)
