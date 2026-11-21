"""Read a backed-up gzip object and reproduce both byte streams, without materializing it."""
from datetime import datetime, timezone
import gzip
import hashlib
import re
import urllib.parse
import urllib.request

import result_maintenance as storage


class BoundHash:
    def __init__(self, source, expected_size):
        if type(expected_size) is not int or expected_size <= 0:
            raise ValueError('invalid expected object size')
        self.source, self.limit, self.size = source, expected_size, 0
        self.digest = hashlib.sha256()

    def read(self, n):
        data = self.source.read(min(n, self.limit-self.size+1))
        self.size += len(data)
        if self.size > self.limit:
            raise ValueError('readback exceeds expected length')
        self.digest.update(data)
        return data

    def check(self, expected):
        if self.size != self.limit or self.digest.hexdigest()!=expected:
            raise ValueError('readback size or digest mismatch')


def verify_stream(stream, compressed_size, compressed_sha, original_size, original_sha):
    src = BoundHash(stream, compressed_size)
    with gzip.GzipFile(fileobj=src, mode='rb') as gz:
        out = BoundHash(gz, original_size)
        while out.read(1024*1024):
            pass
        out.check(original_sha)
    src.check(compressed_sha)


def verify_backup(folder, config_path=None):
    """Read-only sample; this report cannot authorize deletion or mark a run ready."""
    folder, m = storage.context(folder)
    names = ('manifest.json','retention.json','gdrive-offload.json')
    before = [storage.sha(folder/n) for n in names if not (folder/n).is_symlink()]
    if len(before)!=len(names):
        raise ValueError('redirected evidence')
    r,p = (storage.readj(folder/n) for n in names[1:]); gd=storage.gdrive()
    cfg = gd.load_config(config_path); raw=r['artifacts']['results.raw.tar.gz']; uploaded=p['artifacts']['results.raw.tar.gz']
    if not (cfg.get('enabled') is True and cfg.get('mode','oauth')=='oauth'
            and p.get('schema')==gd.OFFLOAD_SCHEMA and p.get('verified') is True and p.get('state') in ('BACKED_UP','OFFLOADED')
            and r['run_id']==p['run_id']==m['run_id'] and r['manifest_sha256']==p['manifest_sha256']==before[0]
            and r['original_archive_sha256']==p['original_archive_sha256']==m['results_sha256']==r['raw_backup_uncompressed_sha256']
            and r['raw_backup_verified'] is True and r['original_archive_bytes']==m['collected_bytes']
            and p['drive_parent_folder_id']==cfg['folder_id'] and re.fullmatch(r'[a-zA-Z0-9_-]+',p['drive_file_id'])
            and uploaded['drive_file_id']==p['drive_file_id'] and uploaded['sha256']==p['raw_backup_sha256']==raw['sha256']
            and uploaded['size']==p['raw_backup_bytes']==raw['bytes']):
        raise ValueError('unbound backup evidence or unsupported provider')
    opener=gd._build_opener(cfg.get('proxy')); token=gd._refresh_access_token(cfg,opener)
    req=urllib.request.Request(gd.DRIVE_FILES_URL+'/'+urllib.parse.quote(p['drive_file_id'],safe='')+'?alt=media')
    req.add_unredirected_header('Authorization','Bearer '+token)
    with opener.open(req,timeout=int(cfg.get('timeout_seconds',gd.DEFAULT_TIMEOUT))) as remote:
        verify_stream(remote,raw['bytes'],raw['sha256'],r['original_archive_bytes'],m['results_sha256'])
    if [storage.sha(folder/n) for n in names]!=before:
        raise ValueError('evidence changed during readback')
    return dict(schema='tcad-maintenance-readback-v1',run_id=m['run_id'],observed_at=datetime.now(timezone.utc).isoformat(),
                manifest_sha256=before[0],retention_sha256=before[1],offload_sha256=before[2],
                compressed_bytes=raw['bytes'],compressed_sha256=raw['sha256'],original_bytes=r['original_archive_bytes'],
                original_sha256=m['results_sha256'],cleanup_authorized=False)
