"""Bind original successful BE logs, precise PLT times and actual archived TDRs.

No expected time is written to a PMI or native field. A clock index alone never
qualifies the source. The CLI reads the original solver archive without extraction.
"""
from __future__ import annotations
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path,PurePosixPath
import re
import tarfile
from source_reference import require,digest,read_json,write_new

NUMBER=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
BE=re.compile(r'^Computing BE-step from ('+NUMBER+r') s to ('+NUMBER+r') s \(Stepsize: ('+NUMBER+r') s\)')
WRITING=re.compile(r"^\s*Writing plot '([^']+)' \(TDR format\) \.\.\. done\.")
ZERO_ITERATION=re.compile(r'^Finished, because \|RHS\| is less than '+NUMBER+r'\.$')


def parse_plt(text):
    # Same DF-ISE grammar as the existing parser, no simulation-specific times.
    info=re.search(r'datasets\s*=\s*\[(.*?)\]',text,re.S)
    data=re.search(r'\bData\s*\{(.*?)\}',text,re.S)
    require(info is not None and data is not None,'Missing complete DF-ISE data')
    names=re.findall(r'"([^"]+)"',info.group(1));values=list(map(float,data.group(1).split()))
    require(names and len(names)==len(set(names)) and values and len(values)%len(names)==0
            and all(math.isfinite(v) for v in values),'Malformed/truncated/nonfinite DF-ISE values')
    require('time' in names,'PLT lacks native time dataset')
    return [dict(zip(names,values[i:i+len(names)])) for i in range(0,len(values),len(names))]


def half_printed_unit(token):
    mantissa,_,exponent=token.lower().partition('e')
    return .500001*10**(int(exponent or '0')-len(mantissa.partition('.')[2]))


def printed_match(value,token):
    return abs(value-float(token))<=half_printed_unit(token)


def index(log,raw_rows,files,generation_field='HeavyIonGeneration',window=None,source_present=True):
    require(raw_rows and all('time' in row for row in raw_rows),'Missing actual PLT times')
    require(len(files)==len(set(files)),'Duplicate native TDR inventory')
    columns=[key for key in raw_rows[0] if key.endswith(generation_field)]
    require(bool(columns)==source_present,'Native generation field presence differs from explicit source role')
    rows=[];duplicates=0
    for row in raw_rows:
        require(set(row)==set(raw_rows[0]) and all(math.isfinite(v) for v in row.values()),'Nonfinite/inconsistent native PLT')
        require(not rows or row['time']>=rows[-1]['time'],'PLT time rollback')
        if rows and row['time']==rows[-1]['time']:
            require(all(row[key]==rows[-1][key] for key in columns),'Generation changes at repeated PLT timestamp')
            duplicates+=1;continue
        rows.append(row)
    require(len(rows)>=2,'Insufficient complete PLT rows')
    intervals=[dict(accepted_index=i,start_s=a['time'],end_s=b['time'],dt_s=b['time']-a['time'])
               for i,(a,b) in enumerate(zip(rows,rows[1:]),1)]
    require(all(v['dt_s']>0 for v in intervals),'PLT intervals not strictly increasing')
    ends=[v['end_s'] for v in intervals]
    attempts=[];step=None
    for lineno,line in enumerate(log.splitlines(),1):
        match=BE.match(line)
        if match:
            if step is not None:attempts.append(step)
            step=dict(raw_tokens=list(match.groups()),BE_log_line=lineno,success=False,rejected=False,writes=[])
        if step is not None:
            if 'Error smaller than 1' in line or 'Rhs smaller than' in line or ZERO_ITERATION.fullmatch(line.strip()):step['success']=True
            if any(token in line for token in ("Newton didn't converge",'time step rejected','Time step rejected')):step['rejected']=True
        match=WRITING.match(line)
        if match and match[1] in files:
            require(step is not None,'Native source TDR write precedes any BE interval')
            step['writes'].append(dict(source_file=match[1],writing_log_line=lineno))
    if step is not None:attempts.append(step)
    accepted={};rejected=[];frames={}
    for attempt in attempts:
        if not attempt['success'] or attempt['rejected']:
            require(not attempt['writes'],'Rejected/unconverged BE attempt wrote a source frame')
            rejected.append(attempt);continue
        start,end,delta=attempt['raw_tokens']
        lo=bisect.bisect_left(ends,float(end)-half_printed_unit(end))
        hi=bisect.bisect_right(ends,float(end)+half_printed_unit(end))
        candidates=[v for v in intervals[lo:hi] if printed_match(v['start_s'],start) and printed_match(v['end_s'],end)
                    and printed_match(v['dt_s'],delta)]
        require(len(candidates)==1,'Successful BE log / precise PLT association is absent or ambiguous')
        interval=dict(candidates[0]);i=interval['accepted_index']
        require(i not in accepted,'Multiple successful BE attempts map to one PLT interval')
        interval.update(BE_log_line=attempt['BE_log_line'],raw_log_tokens=attempt['raw_tokens'])
        accepted[i]=interval
        for write in attempt['writes']:
            name=write['source_file'];require(name not in frames,'Native TDR overwritten or written twice')
            frames[name]=dict(interval,**write,direct_TDR_timestamp_verified=False,
                binding='original Writing line + successful BE interval + precise PLT time + original archived TDR hash')
    require(set(accepted)==set(range(1,len(intervals)+1)),'Full native BE/PLT interval coverage is incomplete')
    require(set(frames)==set(files),'Archived source frame has no successful BE Writing record')
    frame_indices=[v['accepted_index'] for v in frames.values()]
    require(len(frame_indices)==len(set(frame_indices)),'Multiple source frames refer to one accepted interval')
    required=[]
    if window is not None:
        require(len(window)==2 and all(math.isfinite(t) for t in window) and window[1]>window[0],'Invalid source observation window')
        require(rows[0]['time']<=window[0] and rows[-1]['time']>=window[1],
                'Actual solver interval does not cover source window; retain late deposits and extend matched solve')
        required=[v['accepted_index'] for v in intervals if v['end_s']>window[0] and v['start_s']<window[1]]
        require(set(required).issubset(frame_indices),'Missing native field frame for an accepted source-window interval')
    return dict(schema='continuous-proton-source-clock-v1',native_qualified=False,pmi_clock_fabricated=False,
        accepted_intervals=[accepted[i] for i in sorted(accepted)],accepted_BE_count=len(accepted),
        rejected_or_unconverged_attempts=rejected,frames=sorted(frames.values(),key=lambda x:x['accepted_index']),
        source_window_s=window,required_source_window_indices=required,
        source_field=generation_field,source_present=source_present,
        generation_columns=columns,source_scalars=[{key:row[key] for key in ['time',*columns]} for row in rows],
        raw_PLT_rows=len(raw_rows),repeated_block_initial_rows=duplicates,
        repeated_time_rule='retain first accepted endpoint only if native generation columns are exactly equal',
        solver_time_bounds_s=[rows[0]['time'],rows[-1]['time']],
        interpretation='Native temporal identity only; no claim that native generation equals the independent reference')


class Archive:
    def __init__(self,path):
        self.tf=tarfile.open(path);self.members={}
        try:
            for member in self.tf:
                name=member.name.removeprefix('./');p=PurePosixPath(name)
                require(not p.is_absolute() and '..' not in p.parts and '\\' not in name,'Unsafe original archive member')
                require(member.isfile() or member.isdir(),'Original archive contains links/special members')
                if member.isdir():continue
                require(name not in self.members,'Duplicate archive member')
                self.members[name]=member
        except Exception:self.tf.close();raise
    def read(self,name):
        require(name in self.members,'Missing original archive member '+name)
        return self.tf.extractfile(self.members[name]).read()
    def hash(self,name):
        require(name in self.members,'Missing original archive member '+name)
        h=hashlib.sha256();stream=self.tf.extractfile(self.members[name])
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
        return h.hexdigest()
    def close(self):self.tf.close()


def from_solver_run(run,output,log_member='transient_des.log',plt_member='access_device.plt',
                    frame_pattern=r'source_window[A-Za-z0-9_.-]*\.tdr',generation_field='HeavyIonGeneration',
                    window=None,source_present=True):
    run=Path(run).resolve();manifest=read_json(run/'manifest.json');path=run/'results.tar'
    require(manifest.get('state')=='COLLECTED','Original solver run is not collected')
    require(manifest.get('results_sha256')==digest(path),'Original solver archive identity mismatch')
    current=manifest.get('schema')=='tcad-native-run-r2'
    if current:
        require(manifest.get('origin')=='native_pipeline' and manifest.get('synthetic') is False and
                manifest.get('collection_verified') is True,'Current solver lacks original collection provenance')
        keys=('remote_exit_code','collection_exit_code','version_probe_exit_code')
        require(all(type(manifest.get(k)) is int and manifest[k]==0 for k in keys),'Actual current solver exit is not zero')
        require(manifest.get('tool_exit_codes') and all(type(v) is int and v==0 for v in manifest['tool_exit_codes'].values()),'Actual tool exit is missing/failed')
    else:
        require('schema' not in manifest,'Unknown solver schema cannot inherit legacy completion semantics')
        require(type(manifest.get('ssh_exit_code')) is int and manifest['ssh_exit_code']==0,'Legacy SSH execution exit unavailable/failed')
    archive=Archive(path)
    try:
        require(archive.read('exit-code.txt').strip()==b'0','Original remote solver exit failed')
        if current:
            require(archive.read('metadata-sdevice-version-exit-code.txt').strip()==b'0','Original version probe exit failed')
            for evidence in manifest['tool_evidence'].values():
                require(archive.read(evidence['raw_exit_file']).strip()==b'0','Original raw tool exit failed')
        pattern=re.compile(frame_pattern)
        files=sorted(name for name in archive.members if pattern.fullmatch(name))
        log=archive.read(log_member);plt=archive.read(plt_member)
        result=index(log.decode('utf-8'),parse_plt(plt.decode('utf-8')),files,generation_field,window,source_present)
        for frame in result['frames']:frame['source_sha256']=archive.hash(frame['source_file'])
        result['provenance']=dict(run_id=manifest['run_id'],archive_path=str(path),archive_sha256=manifest['results_sha256'],
            manifest_sha256=digest(run/'manifest.json'),log_member=log_member,log_sha256=hashlib.sha256(log).hexdigest(),
            plt_member=plt_member,plt_sha256=hashlib.sha256(plt).hexdigest(),original_ssh_exit_code=manifest['ssh_exit_code'],
            individual_tool_exits_available=current,original_wrapper_exit_code=0,
            current_schema=current,origin='native_original_solver_archive',implementation_sha256=digest(__file__))
    finally:archive.close()
    write_new(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--log-member',default='transient_des.log');p.add_argument('--plt-member',default='access_device.plt')
    p.add_argument('--frame-pattern',default=r'source_window[A-Za-z0-9_.-]*\.tdr')
    p.add_argument('--generation-field',default='HeavyIonGeneration');p.add_argument('--window',nargs=2,type=float)
    p.add_argument('--structural-no-source',action='store_true')
    args=vars(p.parse_args());args['source_present']=not args.pop('structural_no_source')
    result=from_solver_run(**args)
    print(json.dumps(dict(accepted_BE_count=result['accepted_BE_count'],frames=len(result['frames']),native_qualified=False)))
