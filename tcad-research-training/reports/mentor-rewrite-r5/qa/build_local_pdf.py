from pathlib import Path
from datetime import datetime,timezone
import os,subprocess,json,sys
from pypdf import PdfReader

source=Path(sys.argv[1]).resolve()
build=Path(sys.argv[2]).resolve()
build.mkdir(parents=True,exist_ok=False)
repo=Path('E:/TCAD-Workspace/tcad-research-training')
runtime=Path('C:/Users/sun/.cache/codex-runtimes/codex-primary-runtime/dependencies')
env=dict(os.environ)
env['TEXINPUTS']=(repo/'local_runtime/report-writing-20261010/tex-deps/pgf/base/tex').as_posix()+'//;'+source.parent.as_posix()+'//;'
records=[]
for i in (1,2):
    args=['C:/Program Files/MiKTeX/miktex/bin/x64/xelatex.exe','--disable-installer','-no-shell-escape','-interaction=nonstopmode','-halt-on-error',f'-output-directory={build}',str(source)]
    start=datetime.now(timezone.utc).isoformat()
    r=subprocess.run(args,cwd=source.parent,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (build/f'pass-{i}.log').write_bytes(r.stdout)
    records.append({'argv':args,'start':start,'end':datetime.now(timezone.utc).isoformat(),'actual_exit_code':r.returncode})
    (build/'commands.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    if r.returncode:
        print(r.stdout.decode('utf-8',errors='replace')[-4000:]);sys.exit(r.returncode)
pdf=build/(source.stem+'.pdf')
args=[str(runtime/'native/poppler/Library/bin/pdftoppm.exe'),'-r','110','-png',str(pdf),str(build/'page')]
r=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
(build/'render.log').write_bytes(r.stdout)
records.append({'argv':args,'end':datetime.now(timezone.utc).isoformat(),'actual_exit_code':r.returncode})
(build/'commands.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
if r.returncode:sys.exit(r.returncode)
pages=[p.extract_text() for p in PdfReader(pdf).pages]
(build/'extracted-pages.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pdf':str(pdf),'pages':len(pages),'rendered':len(list(build.glob('page-*.png')))},ensure_ascii=False))
