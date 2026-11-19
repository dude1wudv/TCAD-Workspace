import csv
import hashlib
import json
import math
import sys
from decimal import Decimal
from pathlib import Path


source = Path(sys.argv[1])
digest = hashlib.sha256(source.read_bytes()).hexdigest()
if digest != 'de7494aaa3747a211c24aca350b95181c8d0459a39895867c6149825c72193b5':
    raise ValueError('WHR-01: unexpected source revision')
samples = []
with source.open(newline='', encoding='utf-8') as handle:
    for row in csv.DictReader(handle):
        time_ns = float(Decimal(row['time']) * Decimal('1e9'))
        point = [time_ns, *(float(row[key]) for key in ('v(bl)', 'v(sn1)', 'v(sn2)'))]
        if not all(map(math.isfinite, point)) or (samples and time_ns <= samples[-1][0]):
            raise ValueError('invalid canonical sample')
        samples.append(point)
if len(samples) != 620 or [point[1] for point in samples if point[0] == 31.9] != [0.556458126540221]:
    raise ValueError('WHR-01: read point or waveform count differs')
public = {'alias': 'WHR-01', 'samples': samples}
Path(__file__).with_name('waveform.js').write_text(
    'window.WHR_TRACE=' + json.dumps(public, separators=(',', ':'), allow_nan=False) + ';\n',
    encoding='utf-8',
)
