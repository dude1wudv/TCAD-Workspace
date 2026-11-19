"""Fixed source-feature version dispatch. Never select executable paths from packets.

Original source versions and paths stay unchanged. Backups are byte-preservation
evidence, not relocated executable fallbacks. Each verification still calls the
registered original input-only recomputation and requires the complete packet.
Historical bindings validate their own saved dispatcher/registry identities;
the current dispatcher identity is only used for a new binding.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
REGISTRY_PATH=HERE/'source-feature-versions.json'
REGISTRY_SHA256='e4a9ffd7bad7fb618527534f1fc41aec3c6e2d4f4e62d644bf4615bc88c87289'


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def read_json(raw):
    return json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))


def checked_bytes(path,expected,description):
    raw=Path(path).read_bytes()
    require(sha(raw)==expected,description+' identity changed')
    return raw


def rooted(relative):
    require(isinstance(relative,str) and not Path(relative).is_absolute(),'Registered path must be repository-relative')
    result=(ROOT/relative).resolve()
    require(result.is_relative_to(ROOT.resolve()),'Registered path leaves the repository')
    return result


def registry():
    result=read_json(checked_bytes(REGISTRY_PATH,REGISTRY_SHA256,'Fixed verifier registry'))
    require(result['schema']=='continuous-source-feature-verifier-registry-v1','Unknown verifier registry schema')
    ids=[entry['version_id'] for entry in result['versions']]
    require(len(ids)==len(set(ids)) and result['default_version'] in ids,'Ambiguous verifier registration')
    return result


def _packet_matches(entry,packet):
    implementations=packet.get('implementations',{})
    if not isinstance(implementations,dict):return False
    keys=[key for key,dependency in entry['packet_implementation_dependencies']['common'].items()
          if dependency==entry['verifier_dependency_id']]
    require(len(keys)==1,'Registered verifier implementation key is ambiguous')
    implementation=implementations.get(keys[0],{})
    if not isinstance(implementation,dict):return False
    version=packet.get('version_id')
    version_matches=(version==entry['version_id'] if entry.get('packet_version_id_required',False)
                     else version in (None,entry['version_id']))
    return (entry['packet_schema']==packet.get('schema') and version_matches
            and entry['feature_contract_sha256']==packet.get('feature_contract_sha256')
            and entry['verifier_sha256']==implementation.get('sha256'))


def checked_registration(packet=None,*,version_id=None,particle=None):
    fixed=registry()
    if packet is not None:
        require(isinstance(packet,dict) and version_id is None and particle is None,'Packet/version selectors cannot be mixed')
        candidates=[entry for entry in fixed['versions'] if _packet_matches(entry,packet)]
        particle=packet.get('particle')
        require(particle in ('alpha','proton'),'Unregistered source-feature particle')
    else:
        version_id=fixed['default_version'] if version_id is None else version_id
        require(particle is None or particle in ('alpha','proton'),'Unregistered source-feature particle')
        candidates=[entry for entry in fixed['versions'] if entry['version_id']==version_id]
    require(len(candidates)==1,'Unregistered or ambiguous source-feature version')
    entry=candidates[0]
    require(particle is None or particle in entry['particle_dependencies'],'Unregistered particle for source-feature version')
    snapshot_ref=entry['dependency_snapshot'];snapshot_path=rooted(snapshot_ref['repository_relative_path'])
    snapshot=read_json(checked_bytes(snapshot_path,snapshot_ref['sha256'],'Fixed dependency manifest'))
    require(snapshot['schema']=='continuous-source-feature-dependency-snapshot-v1' and snapshot['version_id']==entry['version_id'],
            'Registered dependency snapshot differs')
    dependencies=snapshot['dependencies']
    selected=list(entry['common_dependencies'])
    scopes=[particle] if particle is not None else list(entry['particle_dependencies'])
    for scope in scopes:selected.extend(entry['particle_dependencies'][scope])
    require(len(selected)==len(set(selected)),'Duplicated registered dependency')
    references={}
    for name in selected:
        item=dependencies[name];original=rooted(item['repository_relative_path'])
        require(Path(item['original_path']).resolve()==original,'Original dependency path was relocated')
        backup=(snapshot_path.parent/item['backup_relative_path']).resolve()
        require(backup.is_relative_to(snapshot_path.parent.resolve()),'Dependency backup leaves its snapshot')
        live=checked_bytes(original,item['sha256'],'Registered dependency '+name)
        saved=checked_bytes(backup,item['sha256'],'Preserved dependency '+name)
        require(len(live)==item['bytes'] and saved==live,'Dependency byte preservation differs')
        references[name]=dict(path=str(original),sha256=item['sha256'])
    verifier=references[entry['verifier_dependency_id']]
    require(verifier['sha256']==entry['verifier_sha256'] and references['contract']['sha256']==entry['feature_contract_sha256'],
            'Registered verifier/contract does not match dependency snapshot')
    if packet is not None:
        mapping={**entry['packet_implementation_dependencies']['common'],**entry['packet_implementation_dependencies'][particle]}
        expected={name:references[dependency] for name,dependency in mapping.items()}
        require(packet.get('implementations')==expected,'Packet implementation paths or dependency identities are not registered')
        require(packet.get('feature_contract_ref')==references['contract'] and
                packet.get('feature_contract')==read_json(checked_bytes(references['contract']['path'],entry['feature_contract_sha256'],'Registered contract')),
                'Packet contract is not the fixed registered contract')
    return entry,dict(version_id=entry['version_id'],packet_schema=entry['packet_schema'],particle=particle,
        feature_contract_sha256=entry['feature_contract_sha256'],verifier=verifier,
        dispatcher=dict(path=str(Path(__file__).resolve()),sha256=sha(Path(__file__).read_bytes())),
        registry=dict(path=str(REGISTRY_PATH.resolve()),sha256=REGISTRY_SHA256),
        dependency_manifest=dict(path=str(snapshot_path),sha256=snapshot_ref['sha256']),dependencies=references)


def _load_verifier(info):
    identity=info['verifier'];path=Path(identity['path'])
    raw=checked_bytes(path,identity['sha256'],'Registered executable')
    spec=importlib.util.spec_from_file_location('_registered_source_feature_'+info['version_id'].replace('-','_'),path)
    loaded=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),loaded.__dict__)
    require(sha(path.read_bytes())==identity['sha256'],'Registered executable changed while loading')
    return loaded


def resolve_verifier(packet):
    """Return only a fixed registered original module; use verify for packet admission."""
    _,info=checked_registration(packet)
    return _load_verifier(info)


def load_version(version_id,*,particle=None):
    """Explicit registered version for source/A0 inspection without a fake packet."""
    _,info=checked_registration(version_id=version_id,particle=particle)
    return _load_verifier(info)


def version_info(packet=None,*,version_id=None,particle=None):
    """Identity for new bindings; never substitute dispatcher SHA for original v1 SHA."""
    return checked_registration(packet,version_id=version_id,particle=particle)[1]


def semantic_compatibility():
    """Return explicit semantics for downstream review, never automatic admission."""
    reference=registry()['semantic_compatibility']
    result=read_json(checked_bytes(rooted(reference['repository_relative_path']),reference['sha256'],
                                  'Fixed semantic compatibility record'))
    require(result['schema']=='continuous-source-feature-semantic-compatibility-v1'
            and result['automatic_data_or_native_admission'] is False,'Unknown semantic compatibility record')
    return result


def _historical_dispatcher_pair(dispatcher_raw,registry_raw):
    """Validate only a registered saved release; never execute saved bytes."""
    for reference in registry().get('historical_dispatchers',[]):
        path=rooted(reference['repository_relative_path'])
        saved=read_json(checked_bytes(path,reference['sha256'],'Historical dispatcher manifest'))
        require(saved['schema']=='continuous-source-feature-dispatcher-snapshot-v1'
                and saved['executable_fallback'] is False,'Unknown historical dispatcher manifest')
        originals={};snapshots={}
        for name in ('dispatcher','registry'):
            item=saved[name];original=rooted(item['repository_relative_path'])
            require(Path(item['original_path']).resolve()==original,'Historical dispatcher original path differs')
            backup=(path.parent/item['backup_relative_path']).resolve()
            require(backup.is_relative_to(path.parent.resolve()),'Historical dispatcher backup leaves its snapshot')
            raw=checked_bytes(backup,item['sha256'],'Historical '+name+' snapshot')
            require(len(raw)==item['bytes'],'Historical dispatcher snapshot length differs')
            originals[name]=str(original);snapshots[name]=raw
        if snapshots==dict(dispatcher=dispatcher_raw,registry=registry_raw):return originals
    raise ValueError('Unregistered historical dispatcher/registry snapshot pair')


def verify_version_snapshot(info,snapshots,packet=None):
    """Check the original binding's four byte snapshots without executing them.

    ``snapshots`` maps verifier/dispatcher/registry/dependency_manifest to bytes.
    This checks historical identity only. Call ``verify`` separately to recompute
    prescribed source inputs with the same registered immutable source verifier.
    """
    names=('verifier','dispatcher','registry','dependency_manifest')
    require(isinstance(info,dict) and isinstance(snapshots,dict) and set(snapshots)==set(names),
            'Four original version snapshots are required')
    for name in names:
        require(isinstance(snapshots[name],bytes) and isinstance(info.get(name),dict)
                and set(info[name])=={'path','sha256'} and sha(snapshots[name])==info[name]['sha256'],
                'Original '+name+' snapshot differs from binding')
    entry,current=(checked_registration(packet) if packet is not None else
                   checked_registration(version_id=info.get('version_id'),particle=info.get('particle')))
    require(set(info)==set(current) and all(info[key]==current[key] for key in current
            if key not in ('dispatcher','registry')),'Original source version identity differs from fixed registration')
    current_pair=(info['dispatcher']==current['dispatcher'] and info['registry']==current['registry'])
    if current_pair:
        require(snapshots['dispatcher']==checked_bytes(current['dispatcher']['path'],current['dispatcher']['sha256'],
                                                     'Current dispatcher')
                and snapshots['registry']==checked_bytes(current['registry']['path'],current['registry']['sha256'],
                                                         'Current registry'),'Current source version snapshots differ')
    else:
        originals=_historical_dispatcher_pair(snapshots['dispatcher'],snapshots['registry'])
        require(all(info[name]['path']==originals[name] for name in ('dispatcher','registry')),
                'Original dispatcher/registry binding paths differ')
    saved_registry=read_json(snapshots['registry'])
    require(saved_registry.get('schema')=='continuous-source-feature-verifier-registry-v1',
            'Original registry snapshot schema differs')
    entries=[value for value in saved_registry.get('versions',[]) if value.get('version_id')==info['version_id']]
    require(entries==[entry],'Original registry does not bind the exact registered source version')
    require(snapshots['verifier']==checked_bytes(current['verifier']['path'],current['verifier']['sha256'],
                                               'Original source verifier')
            and snapshots['dependency_manifest']==checked_bytes(current['dependency_manifest']['path'],
                current['dependency_manifest']['sha256'],'Original dependency manifest'),
            'Original verifier or dependency snapshot differs')
    return dict(version_id=info['version_id'],particle=info['particle'],
                dispatcher_sha256=info['dispatcher']['sha256'],registry_sha256=info['registry']['sha256'],
                identity_source='current_binding_snapshots' if current_pair else 'historical_binding_snapshots',
                snapshot_code_executed=False,native_source_qualified=False)


def verify(packet_path,input_files=None):
    packet_path=Path(packet_path).resolve();original=packet_path.read_bytes();packet=read_json(original)
    _,before=checked_registration(packet)
    verifier=_load_verifier(before)
    actual=verifier.verify(packet_path,input_files=input_files)
    require(actual==packet,'Registered verifier did not reproduce the complete original packet')
    require(packet_path.read_bytes()==original,'Source-feature packet changed during verification')
    _,after=checked_registration(packet)
    require(after==before,'Registered verifier dependencies changed during verification')
    return actual


def contract_bytes(packet=None):
    _,before=checked_registration(packet)
    verifier=_load_verifier(before);raw=verifier.contract_bytes(packet)
    require(isinstance(raw,bytes) and sha(raw)==before['feature_contract_sha256'],'Registered contract bytes differ')
    _,after=checked_registration(packet)
    require(after==before,'Registered dependencies changed while reading contract')
    return raw


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--packet',type=Path,required=True)
    args=p.parse_args();packet=verify(args.packet)
    print(json.dumps(dict(version=version_info(packet)['version_id'],particle=packet['particle'],
        full_input_recomputation=True,native_source_qualified=packet['native_source_qualified'])))
