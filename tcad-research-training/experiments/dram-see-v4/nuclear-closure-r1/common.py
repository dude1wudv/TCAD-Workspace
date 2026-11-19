"""Shared evidence primitives for the independently authorized nuclear closure.

Importing this module never writes state or starts work. Scientific contracts are
immutable inputs; mutable runtime records are a separate, explicitly named tree.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RT = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1'
OLD_OPS = ROOT / 'local_runtime/dram-see-v4/transport-probe'
GEOMETRY = HERE.parent / 'source-interface-3d-r1/geometry-contract.json'


def utc():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def write(path, value, exclusive=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open('xb') as stream:
            stream.write(encoded(value))
    else:
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_bytes(encoded(value))
        tmp.replace(path)
    return path


def ref(path):
    path = Path(path).resolve()
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path)}


def check_ref(item):
    path = (ROOT / item['path']).resolve()
    require(path.is_relative_to(ROOT) and path.is_file(), 'Evidence outside repository or missing')
    require(sha(path) == item['sha256'], 'Evidence hash changed: ' + item['path'])
    return path


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


def contract():
    return read(HERE / 'contract.json')


def check_release(stage):
    require(stage in ('transport', 'source', 'device'), 'Unknown release stage')
    path = HERE / ('release-' + stage + '.json')
    release = read(path)
    require(release['stage'] == stage and release['execution_enabled'] is True, 'Stage not released')
    require(release['contract_sha256'] == sha(HERE/'contract.json'), 'Campaign contract changed')
    for item in release['files']:
        check_ref(item)
    return ref(path)
