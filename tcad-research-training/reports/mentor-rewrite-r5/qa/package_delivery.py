"""Copy reviewed mentor documents to the user-requested local folder."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import shutil

WORK = Path(__file__).resolve().parents[1]
DEST = Path('E:/TCAD-Workspace/导师交付材料_DRAM_SEE_2026-10-11')
EDIT = DEST / '07_可编辑源文件'
copies = []

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def copy(source, target, expected=None):
    source, target = Path(source), Path(target)
    original = digest(source)
    if expected:
        assert original == expected, str(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert digest(target) == original, f'Refuse different existing file: {target}'
    else:
        shutil.copyfile(source, target)
    assert digest(target) == original
    copies.append({'source': str(source), 'target': str(target), 'sha256': original})

copy(WORK/'documents/course-report.pdf', DEST/'02_课程报告.pdf', '6184305978bca9c56a6e044c5710a7ee0cde96f66743a62311dbdaf64a3a241f')
copy(WORK/'documents/research-paper.pdf', DEST/'03_研究论文.pdf', '114d51e022c814c72cb132528cc4d0253a99c03ba5f39f56fc23af44b8250ace')
copy(WORK/'slides/output/dram-see-v3-mentor-r4.pptx', DEST/'04_汇报演示.pptx', '6ce8d1fd95a1b20b81620bcfa0c869835225ed92c7b72872a73dde0ee9a52025')
for name in ['course-report.tex', 'research-paper.tex', 'style.tex', 'score-table.tex']:
    copy(WORK/'documents'/name, EDIT/'documents'/name)
for name in ['build_deck.mjs', 'source-deck-reference.json', 'qa/verify_delivery.py', 'slides-text-r4.json']:
    copy(WORK/'slides'/name, EDIT/'slides'/name)

(EDIT/'documents/编译说明.txt').write_text('''课程报告与论文源稿

请保留 documents 与 assets 的相邻位置。图、表和参考文献使用相对路径。

在已具备 XeLaTeX、ctex、Fandol 字体和 PGF/TikZ 的环境中，进入 documents 目录，依次执行：
  xelatex -no-shell-escape -interaction=nonstopmode -halt-on-error course-report.tex
  bibtex course-report
  xelatex -no-shell-escape -interaction=nonstopmode -halt-on-error course-report.tex
  xelatex -no-shell-escape -interaction=nonstopmode -halt-on-error course-report.tex

论文将上述 course-report 换成 research-paper。score-table.tex 已附完整评分表。
MiKTeX 可在 xelatex 参数中加入 --disable-installer，以使用现有依赖。
''', encoding='utf-8')
(EDIT/'slides/源文件说明.txt').write_text('''汇报演示源文件

顶层 04_汇报演示.pptx 可直接编辑。此目录保留生成脚本及文字、讲稿清单。
build_deck.mjs 读取相邻 ../assets 目录中的数据和图件；source-deck-reference.json 保存来源记录。
qa/verify_delivery.py 用于生成后的内容核对。

在已有 Codex 文稿运行环境中，使用 Node.js 执行：
  node build_deck.mjs new_revision
new_revision 应替换成尚未使用的版本名。输出写入新建的 output 与 qa 子目录。
运行环境路径改变时，可设置 CODEX_ARTIFACT_RUNTIME 和 PRESENTATIONS_SKILL_DIR。
原版PPT仅用于可选复核，源文件重建使用本文件夹中已附的数据。
''', encoding='utf-8')

guide = DEST/'00_阅读说明.txt'
text = guide.read_text(encoding='utf-8-sig')
assert '用于项目汇报，待完成。' in text
guide.write_text(text.replace('用于项目汇报，待完成。', '14页，包含主要结果、模型训练与验证，以及汇报时可查阅的补充数据。'), encoding='utf-8')

files = [{'path': p.relative_to(DEST).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)}
         for p in sorted(DEST.rglob('*')) if p.is_file()]
receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'destination': str(DEST),
           'file_count': len(files), 'bytes': sum(x['bytes'] for x in files),
           'copies_this_step': copies, 'files': files,
           'prior_copy_receipts': ['data-copy-receipt.json', 'source-assets-copy-receipt.json'],
           'external_upload_performed': False, 'status': 'COPIED_AWAITING_FINAL_CONTENT_VALIDATION'}
(WORK/'qa/package-manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: receipt[k] for k in ['destination', 'file_count', 'bytes', 'status']}, ensure_ascii=False))
