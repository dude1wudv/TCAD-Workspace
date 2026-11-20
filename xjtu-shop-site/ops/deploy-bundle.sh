#!/usr/bin/env bash
# Deploy only the public static site and read-only projectors.
set -euo pipefail
revision="${1:?full commit SHA required}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
short="${revision:0:8}"
site=/srv/xjtu-shop-site
backup="/srv/xjtu-shop-site-releases/pre-$short"
bundle="/tmp/xjtu-shop-web-$short.bundle"
test -d "$site/.git"
test -f "$bundle"
git -C "$site" diff --quiet -- src ops status-checker package.json package-lock.json public
test -z "$(git -C "$site" diff --cached --name-only)"
test -z "$(git -C "$site" ls-files --others --exclude-standard -- src ops status-checker public)"
mkdir -p "$backup"
if [ ! -f "$backup/revision" ]; then
    cp -a "$site/dist" "$backup/dist"
    cp -a "$site/status-checker" "$backup/status-checker"
    git -C "$site" rev-parse HEAD > "$backup/revision"
fi
# Keep the last public samples visible while the collectors are stopped.
cp -a "$site/dist/status.json" "$backup/status.json" 2>/dev/null || true
cp -a "$site/dist/live.json" "$backup/live.json" 2>/dev/null || true
git -C "$site" fetch "$bundle" HEAD
test "$(git -C "$site" rev-parse FETCH_HEAD)" = "$revision"
systemctl stop xjtu-shop-status.timer xjtu-shop-research.timer 2>/dev/null || true
systemctl stop xjtu-shop-status.service xjtu-shop-research.service 2>/dev/null || true
trap 'systemctl start xjtu-shop-status.timer xjtu-shop-research.timer 2>/dev/null || true' EXIT
git -C "$site" merge --ff-only FETCH_HEAD
test "$(git -C "$site" rev-parse HEAD)" = "$revision"
for name in status.json live.json; do
    if [ -f "$backup/$name" ]; then
        cp -a "$backup/$name" "$site/dist/$name"
    fi
done
if [ -d "$backup/dist/assets" ]; then
    cp -an "$backup/dist/assets/." "$site/dist/assets/"
fi
restorecon -R "$site/dist"
cd "$site/status-checker"
python3 -B -m unittest -q \
    test_status_checker.StatusCheckerTests.test_full_r06_payload_keeps_p0_separate_and_filters_holdout_and_private_metadata
cd "$site"
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
install -d -m 0750 -o tcad -g tcad /var/lib/xjtu-shop-status
runuser -u tcad -- python3 -B "$site/status-checker/progress_store.py" init
install -m 0644 \
    "$site/ops/systemd/xjtu-shop-status.timer" \
    "$site/ops/systemd/xjtu-shop-status.service" \
    "$site/ops/systemd/xjtu-shop-research.timer" \
    "$site/ops/systemd/xjtu-shop-research.service" \
    /etc/systemd/system/
install -d -m 0755 /etc/systemd/system/xjtu-shop-status.service.d
install -m 0644 "$site/ops/systemd/xjtu-shop-status.service.d/20-scheduler-observation.conf" \
    /etc/systemd/system/xjtu-shop-status.service.d/
systemctl daemon-reload
started_at="$(date +%s)"
systemctl start xjtu-shop-research.service
systemctl start xjtu-shop-status.service
restorecon "$site/dist/status.json" "$site/dist/live.json"
restorecon -R "$site/dist-status"
PYTHONPATH="$site/status-checker" python3 -B - "$site" "$started_at" <<'PY'
import datetime as dt
import json
import re
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path

from status_checker import check_public_payload

site = Path(sys.argv[1])
root = site / 'dist'
files, documents = {}, {}
for directory in ('dist', 'dist-status'):
    for name in ('status.json', 'live.json'):
        path = site / directory / name
        assert stat.S_IMODE(path.stat().st_mode) == 0o644, str(path)
        content = path.read_bytes()
        document = json.loads(content)
        assert document['schema_version'] == 2, str(path)
        check_public_payload(document)
        serialized = unicodedata.normalize('NFKC', json.dumps(document, ensure_ascii=False, allow_nan=False))
        assert not re.search(r'/root/|/etc/|r04-l08|127\.0\.0\.1|\bcommand\b', serialized, re.I), str(path)
        assert not re.search(r'r06-(?:hr|hp)-|holdout_evaluation', serialized, re.I), str(path)
        files[directory, name] = content
        documents[directory, name] = document

for name in ('status.json', 'live.json'):
    assert files['dist', name] == files['dist-status', name], f'{name} mirror differs'

payload = documents['dist', 'status.json']
live = documents['dist', 'live.json']
assert 'research' not in live
assert len(payload['services']) == 3
assert all(item['state'] in {'operational', 'degraded', 'maintenance', 'offline'} for item in payload['services'])

health = payload['health']
assert health['services']['state'] in {'operational', 'degraded', 'maintenance', 'offline'}
assert any(item['kind'] == 'daemon' for item in health['services']['items'])
assert health['freshness']['scheduler_threshold_seconds'] >= 30
assert health['simulation']['state'] in {
    'progressing', 'slow_convergence', 'stalled', 'awaiting_collection', 'paused', 'idle', 'unknown'}
feed = payload['activity_feed']
assert feed['mode'] in {'active', 'idle', 'stale'} and isinstance(feed['live_items'], list)

simulation = payload['simulation']
scheduler = simulation['scheduler']
assert scheduler['schema'] == 'tcad-scheduler-observation-v2' and scheduler['observation_stale'] is False
assert scheduler['slot_count'] == scheduler['virtual_machine']['cpu']['cores']
assert len(scheduler['slots']) == scheduler['slot_count']
reserved = scheduler.get('reserved_cpus', [])
assert isinstance(reserved, list) and all(type(cpu) is int for cpu in reserved)
running = [task for task in scheduler['tasks'] if task['state'] == 'running']
active_cpus = {cpu for task in running for cpu in task['cpu_set']}
running_cpus = [slot['cpu'] for slot in scheduler['slots'] if slot['state'] == 'running']
assert scheduler['active_slots'] == len(active_cpus) == len(running_cpus)
assert set(running_cpus) == active_cpus
assert scheduler['active_groups'] == len(running)
for task in scheduler['tasks']:
    if task['kind'] == 'sealed':
        assert set(task) == {'id', 'label', 'kind', 'state', 'cpu_set'}
        assert re.fullmatch(r'ANON-[1-9][0-9]*', task['id']) and task['label'] == '封存留出任务'
        assert task['id'] not in live['history']['tasks']
assert all(task['kind'] not in ('sealed', 'unmatched') for task in simulation['recent_runs'])

research = payload['research']
assert research['schema_version'] == 1
assert research['available'], 'Research owner must deploy the formal plan first'
assert research.get('projection_state') == 'fresh'
assert isinstance(research.get('revision'), str) and research['revision']
blocks = research.get('blocks') or []
counts = research.get('counts') or {}
assert blocks and all(block['id'] in counts for block in blocks)
assert research['totals']['planned'] == sum(count['planned'] for count in counts.values())
assert research['totals']['planned'] == sum(block['planned'] for block in blocks)
for block in blocks:
    count = counts[block['id']]
    for field in ('planned', 'archived', 'solved', 'accepted', 'running', 'failed', 'remaining'):
        assert block[field] == count[field], (block['id'], field)
    if block['sealed']:
        assert not any(case.get('block') == block['id'] or case.get('cohort') == block['id']
                       for case in research['cases'])
for key in ('totals', 'counts', 'blocks', 'budget', 'diagnostics'):
    assert key in live['research_summary'], key
assert live['research_summary']['projection_state'] in {'fresh', 'cached_stale', 'unavailable'}

for host, page in [('tcad.xjtu.shop', 'index.html'), ('status.xjtu.shop', 'status.html')]:
    curl = ['curl', '--noproxy', '*', '--resolve', host + ':443:127.0.0.1', '--max-time', '10', '-fsS']
    for route in ['/'] + re.findall(r'(?:src|href)="(/assets/[^"]+)"', (root / page).read_text(encoding='utf-8')):
        subprocess.run([*curl, 'https://' + host + route, '-o', '/dev/null'], check=True)
    for name in ('status.json', 'live.json'):
        url = f'https://{host}/{name}'
        response = subprocess.check_output([*curl, '--include', url])
        headers, _, body = response.partition(b'\r\n\r\n')
        cache_control = [line for line in headers.lower().splitlines() if line.startswith(b'cache-control:')]
        assert cache_control == [b'cache-control: no-store, max-age=0'], url
        assert body == files['dist', name], url
    response = subprocess.check_output([*curl, '--include', f'https://{host}/'])
    headers, _, _ = response.partition(b'\r\n\r\n')
    cache_control = [line for line in headers.lower().splitlines() if line.startswith(b'cache-control:')]
    assert cache_control == [b'cache-control: no-cache'], host

now = dt.datetime.now(dt.timezone.utc)
for document in documents.values():
    generated_at = dt.datetime.fromisoformat(document['generated_at'].replace('Z', '+00:00'))
    assert int(sys.argv[2]) - 5 <= generated_at.timestamp() <= now.timestamp(), 'Status predates this collection'
    assert (now - generated_at).total_seconds() < 180, 'Status sample is stale'
print(json.dumps({'revision': research['revision'], 'planned': research['totals']['planned'],
                  'observation': payload['simulation']['updated_at'],
                  'health': health['simulation']['state']}, ensure_ascii=False))
PY
systemctl restart xjtu-shop-status.timer xjtu-shop-research.timer
trap - EXIT
for unit in caddy xjtu-shop-status.timer xjtu-shop-research.timer tcad-centos79-vm.service; do
    systemctl is-active --quiet "$unit"
done
git rev-parse HEAD
