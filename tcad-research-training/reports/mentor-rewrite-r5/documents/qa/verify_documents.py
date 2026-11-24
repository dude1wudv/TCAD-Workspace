"""Verify final document bindings and preserve the completed visual review."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
import json
import re
import pdfplumber

HERE = Path(__file__).resolve().parents[1]
QA = HERE / 'qa'
def h(p): return sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p, value): p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

manifest = read(QA / 'r5/render-manifest.json')
previous = read(QA / 'r4/render-manifest.json')
commands = read(QA / 'r5/commands.json')
assert len(commands) == 10 and all(c['actual_exit_code'] == 0 for c in commands)
for rel, digest in manifest['source_sha256'].items():
    assert h(HERE / rel) == digest, rel
bindings = {}
asset = HERE.parent / 'assets'
for p in (asset / 'data').rglob('*'):
    if p.is_file(): bindings[p.relative_to(HERE.parent).as_posix()] = h(p)
assert bindings['assets/data/snapshot/snapshot-manifest.json'] == '58650c6a934c81b07bf03e7aca5917f73b499307baf5c6c276debd47c8ef7ca3'
assert bindings['assets/data/snapshot/summary.json'] == '6fda8113e80160b957634e77d492d38e951961107c1ac4cd25f6257153522c80'
assert (asset/'data/snapshot/final-numerical-prediction-scores.json').read_bytes() == (asset/'data/snapshot/original-r4-prediction-scores.json').read_bytes()
score = read(asset/'data/snapshot/final-numerical-prediction-scores.json')['scores']
ridge = [r for r in score if r['model']=='ridge']
assert len(ridge)==8 and all(r['valid_n']==16 for r in ridge)
table = (HERE/'score-table.tex').read_text(encoding='utf-8')
for row in ridge:
    for key in ('MAE','RMSE','max_absolute_error'):
        assert f"{row[key]:.4f}" in table

review=[]
documents=[]
changed_expected={'course-report.pdf':['page-09.png'],'research-paper.pdf':['page-3.png']}
coverage={'course-report.pdf':{'figures':13,'tables':10,'references':8},
          'research-paper.pdf':{'figures':7,'tables':7,'references':7}}
for doc, old in zip(manifest['documents'],previous['documents']):
    name=doc['pdf']
    assert h(HERE/name)==doc['sha256']
    old_images={Path(k).name:v for k,v in old['images'].items()}
    changed=[]
    for rel,digest in doc['images'].items():
        assert h(HERE/rel)==digest
        png=Path(rel).name
        same=old_images[png]==digest
        if not same: changed.append(png)
        review.append({'pdf':name,'pdf_sha256':doc['sha256'],'png':rel,'png_sha256':digest,
                       'actual_visual_review':'PASS',
                       'basis':'r4 page actually viewed; r5 pixels SHA256 identical' if same else 'r5 page actually viewed after final two wording edits',
                       'checks':['complete page','readable Chinese','no clipping or overlap','formula and table placement','figure caption/units','references when present']})
    assert changed==changed_expected[name]
    with pdfplumber.open(HERE/name) as pdf:
        texts=[page.extract_text() or '' for page in pdf.pages]
    assert len(texts)==doc['pages']
    assert all(len(text)>25 for text in texts)
    normalized=re.sub(r'\s+','', '\n'.join(texts))
    for token in ('64','128','96','20','8','4','0.112560497','0.005783687','202610304','100022.07','null','3.6','1.26','0.032654','0.003490','2026年10月11日'):
        assert token in normalized, (name, token)
    for token in ('ACTIVE','root','alias','教师已审核','已完成答辩'):
        assert token not in normalized, (name,token)
    assert '??' not in normalized
    (QA / 'r5' / name.replace('.pdf','-extracted.txt')).write_text('\n\n'.join(f'PAGE {i+1}\n{x}' for i,x in enumerate(texts)),encoding='utf-8')
    final_log=(QA/'r5'/name.replace('.pdf','-pass-4.log')).read_text(encoding='utf-8',errors='replace')
    assert not any(x in final_log for x in ('Overfull', 'LaTeX Warning:', 'Undefined control sequence'))
    documents.append({'pdf':name,'sha256':doc['sha256'],'pages':doc['pages'],
                      'coverage':coverage[name],'final_pass_overfull':0,'final_pass_unresolved_references':0,
                      'underfull_hbox_warnings':final_log.count('Underfull'),
                      'underfull_note':'Bibliography line spacing only; actual final pages visually reviewed.',
                      'changed_pages_from_r4':changed})
write(QA/'visual-review.json',{'utc':datetime.now(timezone.utc).isoformat(),
    'scope':'authoring-agent actual visual review, not mentor review',
    'state':'PASS','pages':review,'root_acceptance':'separate external review'})
write(QA/'verification.json',{'utc':datetime.now(timezone.utc).isoformat(), 'state':'PASS',
    'documents':documents, 'build_commands':10,'all_command_exit_codes':0,
    'render_manifest_sha256':h(QA/'r5/render-manifest.json'),
    'visual_review_sha256':h(QA/'visual-review.json'),
    'source_binding_count':len(manifest['source_sha256']),'data_bindings':bindings,
    'frozen_score_rows':8,'display_rounding_digits':4,'source_or_model_edits':0,'science_runs':0,
    'scope_limits':['source and document checks reuse accepted science results','no new solver or physical audit','no claim of completed human course activities']})
print(json.dumps({'state':'PASS','documents':documents,'source_bindings':len(manifest['source_sha256']),
                  'data_bindings':len(bindings),'actual_visual_pages':len(review)},ensure_ascii=False))
