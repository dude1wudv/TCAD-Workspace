from pathlib import Path
import os, json, subprocess, sys
from datetime import datetime,timezone
from pypdf import PdfReader

here=Path(__file__).resolve().parent
root=here.parents[2]
tag=sys.argv[1] if len(sys.argv)>1 else 'r1'
assert tag.isalnum()
build=here/'qa'/tag
build.mkdir(parents=True,exist_ok=False)
env=dict(os.environ)
env['TEXINPUTS']=str(root/'local_runtime/report-writing-20261010/tex-deps/pgf/base/tex').replace('\\','/')+'//;'+str(here).replace('\\','/')+'//;'
receipts=[]
for i in [1,2]:
    args=['C:/Program Files/MiKTeX/miktex/bin/x64/xelatex.exe','--disable-installer','-no-shell-escape','-interaction=nonstopmode','-halt-on-error',f'-output-directory={build}',str(here/'project-brief.tex')]
    start=datetime.now(timezone.utc).isoformat()
    result=subprocess.run(args,cwd=here,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    log=build/f'pass-{i}.log'; log.write_bytes(result.stdout)
    receipts.append({'argv':args,'started_utc':start,'finished_utc':datetime.now(timezone.utc).isoformat(),'actual_exit_code':result.returncode,'log':str(log)})
    (build/'commands.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if result.returncode:
        print(result.stdout.decode('utf-8',errors='replace')[-5000:]);sys.exit(result.returncode)
pdf=build/'project-brief.pdf'
args=['C:/Users/sun/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe','-r','130','-png',str(pdf),str(build/'page')]
result=subprocess.run(args,cwd=here,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
(build/'render.log').write_bytes(result.stdout)
receipts.append({'argv':args,'finished_utc':datetime.now(timezone.utc).isoformat(),'actual_exit_code':result.returncode})
(build/'commands.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if result.returncode:sys.exit(result.returncode)
reader=PdfReader(pdf)
text=[x.extract_text() for x in reader.pages]
(build/'extracted-pages.json').write_text(json.dumps(text,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'pdf':str(pdf),'pages':len(reader.pages),'page_text_lengths':[len(x) for x in text],'build':str(build)},ensure_ascii=False))
