"""Read-only readiness inventory using the existing pinned SSH connection."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    args = parser.parse_args()
    if not args.label or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.label):
        raise ValueError('Use a unique lowercase label')
    folder = ROOT / 'local_runtime/dram-see-v4/preflight' / args.label
    folder.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'dram-see-v4-live-readiness-v1', 'utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Connection, process, lock and physics-data inventory; no license probe',
              'ssh_exit_code': None, 'connection_ok': False, 'solver_started': False,
              'installed_anything': False, 'stdout': 'stdout.txt', 'stderr': 'stderr.txt'}
    try:
        path = ROOT / 'scripts/tcad.py'
        spec = importlib.util.spec_from_file_location('_v4_existing_runner', path)
        runner = importlib.util.module_from_spec(spec)
        exec(compile(path.read_bytes(), str(path), 'exec'), runner.__dict__)
        cfg, ssh, _ip = runner.connection()
        record['connection_ok'] = True
        script = '''set -eu
root=__ROOT__
export PATH=__TOOLBIN__:"$PATH"
printf 'READINESS_UTC '; date -u +%Y-%m-%dT%H:%M:%SZ
printf 'TOOLS_BEGIN\n'
for tool in sde snmesh sdevice flock taskset tar; do command -v "$tool" || true; done
printf 'TOOLS_END\nSOLVERS_BEGIN\n'
for proc in /proc/[0-9]*; do
  comm=$(cat "$proc/comm" 2>/dev/null || true)
  case "$comm" in
    sdevice*|snmesh*|sde|transport*) printf 'PID %s COMM %s CWD ' "${proc##*/}" "$comm"; readlink "$proc/cwd" || true ;;
  esac
done
printf 'SOLVERS_END\nLOCK_BEGIN\n'
if [ -f "$root/.solver.lock" ]; then
  if flock -n "$root/.solver.lock" true; then echo SOLVER_LOCK_FREE; else echo SOLVER_LOCK_BUSY; fi
else echo SOLVER_LOCK_NOT_CREATED; fi
printf 'LOCK_END\nDATA_ENV_BEGIN\n'
for key in G4LEDATA G4ENSDFSTATEDATA G4LEVELGAMMADATA G4PARTICLEXSDATA G4NEUTRONHPDATA G4RADIOACTIVEDATA G4PARTICLEHPDATA G4PROTONHPDATA; do
  value=$(printenv "$key" || true)
  if [ -n "$value" ]; then if [ -d "$value" ]; then printf '%s PRESENT %s\n' "$key" "$value"; else printf '%s MISSING_PATH %s\n' "$key" "$value"; fi
  else printf '%s UNSET\n' "$key"; fi
done
printf 'DATA_ENV_END\nPROJECT_DATA_BEGIN\n'
if [ -d "$root/dram-see-v1/software" ]; then
  find "$root/dram-see-v1/software" -maxdepth 4 -type d \\( -name 'G4EMLOW*' -o -name 'G4ENSDFSTATE*' -o -name 'PhotonEvaporation*' -o -name 'G4PARTICLEXS*' -o -name 'G4NDL*' -o -name 'RadioactiveDecay*' -o -name 'G4TENDL*' \\) -print
fi
printf 'PROJECT_DATA_END\nDEFAULT_DATA_CONFIG_BEGIN\n'
g4="$root/dram-see-v1/software/Geant4-10.7.3-Linux"
if [ -x "$g4/bin/geant4-config" ]; then "$g4/bin/geant4-config" --version; fi
if [ -d "$g4/lib64/Geant4-10.7.3" ]; then
  grep -E 'G4DATASET|PhotonEvaporation|PARTICLEXS|G4NDL|RadioactiveDecay|ENSDF' "$g4/lib64/Geant4-10.7.3/Geant4Config.cmake" | head -n 20 || true
fi
printf 'DEFAULT_DATA_CONFIG_END\nREADINESS_FINISHED\n'
'''.replace('__ROOT__', shlex.quote(cfg['remote_root'].rstrip('/'))).replace('__TOOLBIN__', shlex.quote(cfg['tool_bin']))
        (folder / 'probe.sh').write_text(script, encoding='utf-8', newline='\n')
        record['probe_sha256'] = hashlib.sha256(script.encode()).hexdigest()
        result = subprocess.run(ssh + ['bash -lc ' + shlex.quote(script)], capture_output=True, timeout=90)
        (folder / 'stdout.txt').write_bytes(result.stdout)
        (folder / 'stderr.txt').write_bytes(result.stderr)
        record['ssh_exit_code'] = result.returncode
        record['finished_marker'] = b'READINESS_FINISHED' in result.stdout
    except Exception as exc:
        record['error_type'] = type(exc).__name__
        record['error'] = str(exc)
    finally:
        (folder / 'record.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'folder': str(folder), 'connection_ok': record['connection_ok'],
                      'ssh_exit_code': record['ssh_exit_code'], 'error_type': record.get('error_type')}))
    return 0 if record['ssh_exit_code'] == 0 and record.get('finished_marker') else 1


if __name__ == '__main__':
    raise SystemExit(main())
