"""Download only the explicitly frozen CERN datasets; verify before use."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def main():
    spec = json.loads((HERE / 'environment-spec.json').read_text(encoding='utf-8'))
    folder = ROOT / 'local_runtime/dram-see-v4/transport-probe/downloads/r1'
    folder.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'dram-see-v4-data-download-v1', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'environment_spec_sha256': hashlib.sha256((HERE / 'environment-spec.json').read_bytes()).hexdigest(),
              'state': 'STARTED', 'datasets': []}
    try:
        for item in spec['datasets_to_add']:
            entry = {'archive': item['archive'], 'url': item['url'], 'state': 'STARTED'}
            record['datasets'].append(entry)
            path = folder / item['archive']
            with urllib.request.urlopen(item['url'], timeout=45) as response, path.open('xb') as dest:
                entry['final_url'] = response.url
                entry['content_length'] = response.headers.get('Content-Length')
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    dest.write(chunk)
            raw = path.read_bytes()
            entry.update(bytes=len(raw), md5=hashlib.md5(raw).hexdigest(), sha256=hashlib.sha256(raw).hexdigest())
            if entry['md5'] != item['md5_from_distribution']:
                raise ValueError('Official distribution MD5 mismatch: ' + item['archive'])
            count = total = 0
            with tarfile.open(path, 'r:gz') as archive:
                for member in archive:
                    name = PurePosixPath(member.name)
                    if name.is_absolute() or '..' in name.parts or name.parts[0] != item['directory'] or not (member.isdir() or member.isfile()):
                        raise ValueError('Unsafe/unexpected dataset member: ' + member.name)
                    if member.isfile():
                        count += 1
                        payload = archive.extractfile(member).read()
                        if len(payload) != member.size:
                            raise ValueError('Incomplete archive file')
                        total += len(payload)
            entry.update(state='VERIFIED', files=count, expanded_bytes=total)
            print(json.dumps(entry), flush=True)
        record['state'] = 'VERIFIED'
    except Exception as exc:
        record.update(state='FAILED', error=repr(exc))
        raise
    finally:
        record['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (folder / 'download-record.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
