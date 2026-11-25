from __future__ import annotations
import csv, hashlib, json, re, zipfile
from pathlib import Path
import fitz

ROOT = Path(r'E:\TCAD-Workspace\tcad-research-training')
PACKAGE = Path(r'E:\TCAD-Workspace\导师交付材料_DRAM_SEE_2026-10-11')
OUT = ROOT / 'reports/mentor-rewrite-r5/qa/validation'
RECEIPT = ROOT / 'reports/mentor-rewrite-r5/qa/package-manifest.json'
FINAL = ROOT / 'reports/final-r4'
DOCS = ROOT / 'reports/mentor-rewrite-r5/documents'
checks, failures = [], []
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def ck(name, ok, detail=None):
    checks.append({'check':name,'passed':bool(ok),'detail':detail})
    if not ok: failures.append(name)
def readj(p): return json.loads(p.read_text(encoding='utf-8'))

def csvrows(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

receipt=readj(RECEIPT)
files=receipt['files']
expected_by_path={x['path']:x for x in files}
actual_paths=[]
for p in PACKAGE.rglob('*'):
    if p.is_file(): actual_paths.append(p.relative_to(PACKAGE).as_posix())
actual_set=set(actual_paths); expected_set=set(expected_by_path)
ck('package_file_count_and_byte_total',receipt.get('file_count')==173 and len(actual_paths)==173 and sum(p.stat().st_size for p in PACKAGE.rglob('*') if p.is_file())==receipt.get('bytes'),{'receipt_count':receipt.get('file_count'),'actual_count':len(actual_paths),'receipt_bytes':receipt.get('bytes'),'actual_bytes':sum(p.stat().st_size for p in PACKAGE.rglob('*') if p.is_file())})
ck('package_paths_exactly_match_manifest',actual_set==expected_set,{'missing':sorted(expected_set-actual_set),'unlisted':sorted(actual_set-expected_set)})
file_hashes=[]
for rel,meta in sorted(expected_by_path.items()):
    p=PACKAGE/Path(rel)
    actual=sha(p) if p.is_file() else None
    match=actual==meta.get('sha256') and p.is_file() and p.stat().st_size==meta.get('bytes')
    file_hashes.append({'path':rel,'expected_sha256':meta.get('sha256'),'actual_sha256':actual,'expected_bytes':meta.get('bytes'),'actual_bytes':p.stat().st_size if p.is_file() else None,'matches':match})
ck('all_173_package_hashes_and_lengths',len(file_hashes)==173 and all(x['matches'] for x in file_hashes),{'checked':len(file_hashes),'mismatches':[x['path'] for x in file_hashes if not x['matches']]})

primary={
 '01_项目简报.pdf':ROOT/'reports/mentor-brief-r4/visual-v3/project-brief.pdf',
 '02_课程报告.pdf':DOCS/'course-report.pdf',
 '03_研究论文.pdf':DOCS/'research-paper.pdf',
 '04_汇报演示.pptx':ROOT/'reports/mentor-rewrite-r5/slides/output/dram-see-v3-mentor-r4.pptx',
 '05_课程配套材料.pdf':ROOT/'reports/mentor-rewrite-r5/materials/course-materials.pdf',
}
primary_evidence={}
expected_pages={'01_项目简报.pdf':3,'02_课程报告.pdf':14,'03_研究论文.pdf':9,'04_汇报演示.pptx':14,'05_课程配套材料.pdf':4}
for basename,source in primary.items():
    target=PACKAGE/basename
    src_hash=sha(source) if source.is_file() else None
    dst_hash=sha(target) if target.is_file() else None
    if basename.endswith('.pdf'):
        pages=fitz.open(target).page_count if target.is_file() else None
    else:
        try:
            with zipfile.ZipFile(target) as z:
                pages=sum(1 for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n))
        except Exception: pages=None
    primary_evidence[basename]={'source':str(source),'source_sha256':src_hash,'package_sha256':dst_hash,'pages':pages,'expected_pages':expected_pages[basename]}
    ck('primary_'+basename+'_matches_source_and_pages',src_hash is not None and src_hash==dst_hash and pages==expected_pages[basename],primary_evidence[basename])

readme=PACKAGE/'00_阅读说明.txt'
readme_text=readme.read_text(encoding='utf-8')
ck('reading_guide_no_pending_placeholders',not re.search(r'待完成|待补充|TODO|TBD|PENDING|placeholder|尚待',readme_text,re.I),{'text':readme_text})
main_names=sorted(p.name for p in PACKAGE.iterdir() if p.is_file() and p.suffix.lower() in {'.pdf','.pptx'})
expected_main_names=sorted(expected_pages)
ck('no_superseded_main_deliverables',main_names==expected_main_names,{'actual':main_names,'expected':expected_main_names})

# Resolve TeX references from the package's actual editable-source layout.
srcroot=PACKAGE/'07_可编辑源文件'
tex_paths=[srcroot/'brief/project-brief.tex',srcroot/'documents/course-report.tex',srcroot/'documents/research-paper.tex',srcroot/'materials/course-materials.tex']
resolved=[]; unresolved=[]
for tex in tex_paths:
    s=tex.read_text(encoding='utf-8')
    for cmd,arg in re.findall(r'\\(input|include|includegraphics|bibliography)\s*\{([^}]+)\}',s):
        names=[arg]
        if cmd in {'input','include'} and not Path(arg).suffix: names += [arg+'.tex']
        elif cmd=='includegraphics' and not Path(arg).suffix: names += [arg+'.pdf',arg+'.png',arg+'.jpg']
        elif cmd=='bibliography' and not Path(arg).suffix: names += [arg+'.bib']
        candidates=[]
        for name in names:
            q=Path(name)
            candidates.extend([tex.parent/q,srcroot/q])
        match=next((p for p in candidates if p.is_file()),None)
        record={'source':str(tex.relative_to(PACKAGE)),'command':cmd,'reference':arg,'resolved':str(match.relative_to(PACKAGE)) if match else None}
        (resolved if match else unresolved).append(record)
# Our source package uses TEX inputs relative to each document source and assets as siblings.
ck('editable_tex_relative_dependencies_resolve',bool(resolved) and not unresolved,{'resolved_count':len(resolved),'unresolved':unresolved,'resolved_examples':resolved[:12]})
source_guide=(srcroot/'源文件说明.txt').read_text(encoding='utf-8')
ck('editable_source_readme_present_and_describes_assets',(srcroot/'源文件说明.txt').is_file() and 'assets' in source_guide.lower() and 'LaTeX' in source_guide,{'guide':source_guide})

# Content facts against the frozen source records and the PDFs already accepted by root.
summary=readj(FINAL/'data/snapshot/summary.json')
models=readj(FINAL/'data/frozen-models.json')
responses=csvrows(FINAL/'data/snapshot/responses.csv')
scores=csvrows(FINAL/'data/snapshot/prediction-scores.csv')
extensions=csvrows(FINAL/'data/snapshot/extension-cases.csv')
events={r['event_label'] for r in responses}
paired=all({r['stored_bit'] for r in responses if r['event_label']==e}=={'0','1'} for e in events)
ck('source_64_events_128_paired_responses',len(events)==64 and len(responses)==128 and paired,{'events':len(events),'responses':len(responses),'paired':paired})
counts=summary['main_threshold_counts']; expected_counts={'correct':96,'criterion_error':20,'critical':8,'numerically_uncertain':4}
ck('source_5mV_counts_96_20_8_4',all(counts.get(k)==v for k,v in expected_counts.items()),{k:counts.get(k) for k in expected_counts})
model_records=models['models']; config=models['configuration']
ck('models_training_64_each_32_four_lambda_01',models.get('train_paired_responses')==64 and len(model_records)==4 and all(v.get('training_response_n')==32 and v.get('selected_alpha')==.1 for v in model_records.values()),{'training_responses':models.get('train_paired_responses'),'models':{k:{'n':v.get('training_response_n'),'lambda':v.get('selected_alpha')} for k,v in model_records.items()}})
folds={k:[(len(f.get('training_event_labels',[])),len(f.get('validation_event_labels',[]))) for f in v.get('cv_folds',[])] for k,v in model_records.items()}
ck('four_models_loco_8_folds_28_plus_4',all(len(v)==8 and all(a==28 and b==4 for a,b in v) for v in folds.values()),folds)
oxide=[r for r in extensions if r['stage']=='oxide']
boundary=[r for r in extensions if r['stage']=='boundary' and r['role']=='event']
objects={re.sub(r'-s(?:0p5-m1|1-m0p7)$','',r['tag']) for r in boundary}
comparisons=summary['numerical_boundary']['comparisons']; crossings=[c for c in comparisons if not c['classification_stable']]
ck('source_14_oxide_2_boundary_1_crossing',len(oxide)==14 and len(objects)==2 and len(crossings)==1,{'oxide':len(oxide),'boundary_objects':sorted(objects),'crossing_events':[c['event']['label'] for c in crossings]})
failures=readj(FINAL/'data/snapshot/original-failures.json')['alias_originals']
ck('source_four_aliases_FAILED_null',len(failures)==4 and all(v.get('state')=='FAILED' and v.get('runner_exit_code') is None for v in failures.values()),{k:{'state':v.get('state'),'exit_code':v.get('runner_exit_code')} for k,v in failures.items()})

# Reuse previous independent content check; confirm current two revised TeX sources still have expected hashes.
brief_source=ROOT/'reports/mentor-brief-r4/visual-v3/project-brief.tex'
material_source=ROOT/'reports/mentor-rewrite-r5/materials/course-materials.tex'
ck('brief_current_source_hash',sha(brief_source)=='0033a73c8d0ebe9f42355b68b3b6e7aac90354f1e859793d35a96e880820f1be',sha(brief_source))
ck('course_material_source_hash_unchanged',sha(material_source)=='a279aeedf62ad503817c5fa0ed3889a7165cd238d34258a6044f363b3629678a',sha(material_source))

ppt_qa=readj(ROOT/'reports/mentor-rewrite-r5/slides/qa/r4/content-verification.json')
rev_qa=readj(ROOT/'reports/mentor-rewrite-r5/slides/qa/r4/revision-comparison.json')
ck('ppt_existing_content_qa_reused',ppt_qa.get('state')=='PASS' and ppt_qa.get('final_sha256')==sha(primary['04_汇报演示.pptx']) and rev_qa.get('state')=='PASS',{'content_state':ppt_qa.get('state'),'revision_state':rev_qa.get('state'),'ppt_sha256':sha(primary['04_汇报演示.pptx'])})

result={
 'schema':'mentor-rewrite-r5-final-package-independent-validation-v1',
 'status':'PASS' if not failures else 'FAIL',
 'package':{'path':str(PACKAGE),'receipt':str(RECEIPT),'receipt_sha256':sha(RECEIPT),'file_count':len(files),'bytes':receipt.get('bytes')},
 'checks':checks,'failures':failures,'primary_artifacts':primary_evidence,'package_hashes':file_hashes,'relative_dependencies_resolved':resolved,'unresolved_dependencies':unresolved,
 'scope':['Read-only package/hash and content validation; no simulations, solver, model fitting, installation, Git, compilation, or visual inspection.','PPT content QA was reused. Root performed page-by-page visual acceptance.','Scientific facts were checked against the already frozen final-r4 snapshot; original archives were not re-audited.']
}
OUT.mkdir(parents=True,exist_ok=True)
out=OUT/'final-package-validation.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':result['status'],'checks':len(checks),'failures':failures,'package_files_checked':len(file_hashes),'primary':primary_evidence,'output':str(out)},ensure_ascii=False,indent=2))
raise SystemExit(1 if failures else 0)
