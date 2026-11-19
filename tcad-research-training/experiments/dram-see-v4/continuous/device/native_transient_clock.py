"""Versioned 2D mixed-mode PLT/BE association; Python 3.6 standard library.

Raw rows and zero-duration states remain evidence. Positive-time circuit end
states are identified by exact four-port device-current correspondence, never
by a favorable value. High-precision times come only from original PLT tokens.
"""
from decimal import Decimal
import hashlib
import json
import math
import re

SCHEMA = 'dram-see-v4-native-transient-clock-r2'
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
BE = re.compile(r'^Computing BE-step from ('+NUMBER+r') s to ('+NUMBER+r') s \(Stepsize: ('+NUMBER+r') s\)')
WRITE = re.compile(r"^\s*Writing plot '([^']+)' \(TDR format\) \.\.\. done\.")
PORTS = {'sn':'source', 'bl':'drain', 'wl':'gate', '0':'body'}


def require(ok,message):
    if not ok: raise ValueError('Native transient clock: '+message)


def _text(value):
    return value.decode('utf-8') if isinstance(value,bytes) else value


def _digest(value):
    return hashlib.sha256(value if isinstance(value,bytes) else value.encode('utf-8')).hexdigest()


def half_unit(token):
    return Decimal(5).scaleb(Decimal(token).as_tuple().exponent-1)


def printed(value,token):
    return abs(value-Decimal(token)) <= half_unit(token)


def parse_plt(raw):
    text=_text(raw)
    names=re.search(r'datasets\s*=\s*\[(.*?)\]',text,re.S)
    functions=re.search(r'functions\s*=\s*\[(.*?)\]',text,re.S)
    data=re.search(r'\bData\s*\{(.*?)\}',text,re.S)
    require(names is not None and functions is not None and data is not None,'Incomplete original DF-ISE table')
    names=re.findall(r'"([^"]+)"',names.group(1)); functions=functions.group(1).split()
    tokens=list(re.finditer(r'\S+',data.group(1)))
    require(names and names[0]=='time' and len(set(names))==len(names) and len(functions)==len(names)
            and tokens and len(tokens)%len(names)==0,'Malformed original PLT columns/rows')
    rows=[]
    for offset in range(0,len(tokens),len(names)):
        values=tokens[offset:offset+len(names)]
        original={name:v.group(0) for name,v in zip(names,values)}
        require(all(re.fullmatch(NUMBER,v) and Decimal(v).is_finite() and math.isfinite(float(v)) for v in original.values()),
                'Nonfinite or malformed original PLT value')
        rows.append(dict(row_1based=len(rows)+1, tokens=original, values={k:float(v) for k,v in original.items()},
            line_first=text.count('\n',0,data.start(1)+values[0].start())+1,
            line_last=text.count('\n',0,data.start(1)+values[-1].end())+1))
    units={'Time':'s','Voltage':'V','Current':'A','Charge':'C','OuterVoltage':'V','TotalCurrent':'A'}
    return dict(columns=names,functions=functions,units={n:units.get(f,f) for n,f in zip(names,functions)},
                raw_rows=rows,sha256=_digest(raw))


def _groups(table):
    groups=[]
    for row in table['raw_rows']:
        time=Decimal(row['tokens']['time'])
        require(time>=0,'Negative original transient time')
        if groups and time==Decimal(groups[-1][0]['tokens']['time']):groups[-1].append(row)
        else:
            require(not groups or time>Decimal(groups[-1][0]['tokens']['time']),'Original PLT time moved backwards')
            groups.append([row])
    require(groups and Decimal(groups[0][0]['tokens']['time'])==0,'Original transient has no zero-time initialization')
    return groups


def _deck(raw):
    text=_text(raw)
    matches=list(re.finditer(r'Transient\(InitialTime=('+NUMBER+r') FinalTime=('+NUMBER+r')[^\n]*',text))
    require(matches,'Missing declared native transient segments')
    segments=[dict(segment_index=i,initial_literal=m.group(1),final_literal=m.group(2),
        deck_line=text.count('\n',0,m.start())+1) for i,m in enumerate(matches,1)]
    require(Decimal(segments[0]['initial_literal'])==0 and all(
        Decimal(a['final_literal'])==Decimal(b['initial_literal']) for a,b in zip(segments,segments[1:])),
        'Declared transient segments are not contiguous')
    require(text.count('Set(sn=0.6)')==1 and text.count('Unset(sn)')==1
            and text.index('Set(sn=0.6)')<text.index('Unset(sn)')<matches[0].start()
            and re.search(r'\bLoad\s*\(',text) is None,'Unknown common-initialization/release program')
    changes=list(re.finditer(r'(?<![A-Za-z])Set\(([^)]*)\)',text))
    require([m.group(1) for m in changes]==['sn=0.6','rdrive."resistance"=1e15'],
            'Unknown zero-duration Set program; explicit version support required')
    update=changes[1]
    next_segment=next((i for i,m in enumerate(matches) if m.start()>update.start()),None)
    require(next_segment is not None and next_segment>0,'Resistor Set is not an internal segment boundary')
    return segments,dict(before_segment_index=next_segment+1,time_literal=segments[next_segment]['initial_literal'],
        deck_line=text.count('\n',0,update.start())+1,old_resistance_ohm=1000,new_resistance_ohm=1e15)


def _log(raw,segments):
    lines=_text(raw).splitlines();starts={};problems=[]
    for i,line in enumerate(lines):
        if line.strip()=='Transient (' and i and lines[i-1].strip()=='Starting solve of next problem:':
            match=re.search(r'Initial time : ('+NUMBER+r') s, Final time : ('+NUMBER+r') s', '\n'.join(lines[i:i+10]))
            require(match is not None,'Native transient block lacks its original time bounds')
            problems.append(dict(log_line=i+1,initial_token=match.group(1),final_token=match.group(2)))
            starts[i+1]=len(problems)
    require(len(problems)==len(segments),'Actual and declared transient segment counts differ')
    for expected,observed in zip(segments,problems):
        require(printed(Decimal(expected['initial_literal']),observed['initial_token'])
                and printed(Decimal(expected['final_literal']),observed['final_token']),
                'Actual transient segment differs at native print precision')
    release=[i+1 for i,v in enumerate(lines) if v.strip()=='Unset sn at value 0.6']
    require(len(release)==1 and release[0]<problems[0]['log_line'],'No original neutral initialization release before first transient')
    setters=[i+1 for i,v in enumerate(lines) if "Setting parameter 'resistance' of device 'rdrive' to 1.0000e+15 (value was 1.0000e+03)." in v]
    require(len(setters)==1,'Original resistor change is missing or ambiguous')
    attempts=[];writes=[];current=None;segment=None
    for lineno,line in enumerate(lines,1):
        if lineno in starts:
            if current is not None: attempts.append(current);current=None
            segment=starts[lineno]
        match=BE.match(line)
        if match:
            require(segment is not None,'BE attempt before native transient block')
            if current is not None:attempts.append(current)
            current=dict(attempt_index=len(attempts)+1,segment_index=segment,BE_log_line=lineno,
                raw_log_tokens=list(match.groups()),success=False,rejected=False,writing_records=[])
        if current is not None:
            if ('Error smaller than 1' in line or 'Rhs smaller than' in line
                or re.fullmatch(r'Finished, because \|RHS\| is less than '+NUMBER+r'\.',line.strip())
                or re.fullmatch(r'\|RHS\| less than '+NUMBER+r'\.',line.strip())):
                current['success']=True;current['convergence_log_line']=lineno
            if any(s in line for s in ("Newton didn't converge",'time step rejected','Time step rejected')):
                current['rejected']=True
        match=WRITE.match(line)
        if match:
            record=dict(source_file=match.group(1),writing_log_line=lineno,segment_index=segment,
                        attempt_index=None if current is None else current['attempt_index'])
            writes.append(record)
            if current is not None:current['writing_records'].append(record)
    if current is not None:attempts.append(current)
    return problems,attempts,writes,dict(release_log_line=release[0],resistor_set_log_line=setters[0])


def audit(circuit_raw,device_plt_raw,log_raw,deck_raw):
    circuit,device=parse_plt(circuit_raw),parse_plt(device_plt_raw)
    cg,dg=_groups(circuit),_groups(device)
    required=['time','v(sn)','v(bl)','v(wl)','v(plate)','v(drive)']+['i(access,'+p+')' for p in PORTS]+['i(cstore,sn)','i(cbl,bl)','i(rdrive,bl)']
    require(circuit['columns']==required,'Unsupported actual circuit column order/schema')
    require(all(circuit['units'][n]==('s' if n=='time' else 'V' if n.startswith('v(') else 'A') for n in required),
            'Actual circuit physical units differ')
    require(all(device['units'].get(contact+' TotalCurrent')=='A'
                and device['units'].get(contact+' OuterVoltage')=='V' for contact in PORTS.values()),
            'Actual device terminal quantity functions differ')
    require(len(cg)==len(dg) and all(Decimal(c[0]['tokens']['time'])==Decimal(d[0]['tokens']['time']) for c,d in zip(cg,dg)),
            'Complete circuit/device PLT time sets differ')
    require(len(cg[0])==3 and len(dg[0])==2 and all(len(g)==1 for g in dg[1:]),
            'Unknown initialization or positive-time device duplicate; preserve and investigate')
    voltage=[n for n in circuit['columns'] if n.startswith('v(')]
    require(all(Decimal(cg[0][1]['tokens'][n])==Decimal(cg[0][2]['tokens'][n]) for n in voltage),
            'Post-initialization zero-time node voltages differ')
    require(Decimal(cg[0][-1]['tokens']['v(sn)'])==Decimal('.6') and Decimal(cg[0][-1]['tokens']['v(wl)'])==Decimal('-.5')
            and Decimal(cg[0][-1]['tokens']['v(plate)'])==Decimal('.6'), 'Initial physical state is not the released neutral state')
    for port,contact in PORTS.items():
        require(Decimal(cg[0][1]['tokens']['i(access,'+port+')']) == -Decimal(dg[0][-1]['tokens'][contact+' TotalCurrent']),
                'Full mixed-mode initialization does not match original device terminal currents')
        node=Decimal('0') if port=='0' else Decimal(cg[0][-1]['tokens']['v('+port+')'])
        require(node==Decimal(dg[0][-1]['tokens'][contact+' OuterVoltage']), 'Initial circuit/device node state differs')
    segments,change=_deck(deck_raw);problems,attempts,writes,initial_log=_log(log_raw,segments)
    success=[v for v in attempts if v['success'] and not v['rejected']]
    require(len(success)==len(dg)-1,'Successful BE count differs from all positive-time PLT points')
    accepted=[]
    for i,(attempt,previous,endpoint) in enumerate(zip(success,dg,dg[1:]),1):
        a,b=Decimal(previous[0]['tokens']['time']),Decimal(endpoint[0]['tokens']['time'])
        require(all(printed(v,t) for v,t in zip((a,b,b-a),attempt['raw_log_tokens'])),
                'Ordered BE / original PLT start, end or dt disagrees at printed precision')
        accepted.append(dict(accepted_index=i,attempt_index=attempt['attempt_index'],segment_index=attempt['segment_index'],
            start_s=float(a),end_s=float(b),dt_s=float(b)-float(a),start_time_token=str(a),end_time_token=str(b),
            BE_log_line=attempt['BE_log_line'],raw_log_tokens=attempt['raw_log_tokens'],
            convergence_log_line=attempt['convergence_log_line'],device_row_1based=endpoint[0]['row_1based'],
            circuit_start_row_1based=cg[i-1][-1]['row_1based'],circuit_end_row_1based=cg[i][0]['row_1based']))
    require([v['segment_index'] for v in accepted]==sorted(v['segment_index'] for v in accepted),'Native BE segment order changed')
    boundary={}
    for segment,problem in zip(segments,problems):
        subset=[v for v in accepted if v['segment_index']==segment['segment_index']]
        require(subset,'Native transient segment has no accepted BE interval')
        first,last=subset[0],subset[-1]
        require(printed(Decimal(segment['initial_literal']),first['start_time_token'])
                and printed(Decimal(segment['final_literal']),last['end_time_token']),
                'Actual accepted segment endpoints differ from original deck')
        segment.update(start_actual_s=first['start_s'],end_actual_s=last['end_s'],log_line=problem['log_line'],
                       first_accepted_index=first['accepted_index'],last_accepted_index=last['accepted_index'])
        if segment['segment_index']>1:boundary[Decimal(first['start_time_token'])]=segment['segment_index']
    change_segment=segments[change['before_segment_index']-1]
    require(segments[change['before_segment_index']-2]['log_line']<initial_log['resistor_set_log_line']<change_segment['log_line'],
            'Original resistor Set occurs at a different segment')
    events=[];canonical=[cg[0][-1]]
    for group,target in zip(cg[1:],dg[1:]):
        time=Decimal(group[0]['tokens']['time']);expected_count=2 if time in boundary else 1
        require(len(group)==expected_count,'Unexpected circuit rows at a non-boundary or missing restart row')
        for port,contact in PORTS.items():
            require(Decimal(group[0]['tokens']['i(access,'+port+')']) == -Decimal(target[0]['tokens'][contact+' TotalCurrent']),
                    'Circuit BE endpoint does not exactly match the original device terminal current')
        canonical.append(group[0])
        if len(group)==2:
            changed=[n for n in circuit['columns'] if Decimal(group[0]['tokens'][n])!=Decimal(group[1]['tokens'][n])]
            allowed={'i(access,'+p+')' for p in PORTS}
            is_set=boundary[time]==change['before_segment_index']
            if is_set:allowed.add('i(rdrive,bl)')
            require(set(changed)<=allowed,'Unknown zero-duration circuit state conflict')
            if is_set:
                for row,resistance in zip(group,(Decimal(1000),Decimal('1e15'))):
                    # Mixed-mode i(instance,node) is delivered into the node.
                    token=row['tokens'];left=Decimal(token['v(drive)'])-Decimal(token['v(bl)'])
                    right=Decimal(token['i(rdrive,bl)'])*resistance
                    uncertainty=half_unit(token['v(bl)'])+half_unit(token['v(drive)'])+resistance*half_unit(token['i(rdrive,bl)'])
                    require(abs(left-right)<=uncertainty,'Original resistor sides do not match their declared resistance at print precision')
            events.append(dict(time_s=float(time),circuit_rows=group,preceding_BE_endpoint_row=group[0]['row_1based'],
                next_segment_initial_row=group[1]['row_1based'],next_segment_index=boundary[time],changed_columns=changed,
                resistor_set=is_set,elapsed_s=0.,contributes_to_BE_integral=False))
    canonical_device=[dg[0][-1]]+[g[0] for g in dg[1:]]
    trace={key:[row['values'][name] for row in canonical] for key,name in
           (('time_s','time'),('v_sn_V','v(sn)'),('v_bl_V','v(bl)'))}
    # UG W-2024.09 p1797/Table366 defines System i(device,node) as exiting
    # the device. The fixed metric requires the opposite, into-device current.
    # Use the actual device column, after the exact four-port association above.
    trace['i_sn_A']=[row['values']['source TotalCurrent'] for row in canonical_device]
    current_mapping=dict(schema='dram-see-v4-2d-terminal-current-mapping-r1',target='i_sn_A',
        target_direction='total terminal current into access device through source at SN',unit='A',
        actual_input_file='access_device.plt',actual_input_column='source TotalCurrent',
        actual_input_multiplier=1,postprocessing_width_multiplier=1,
        raw_system_file='circuit.plt',raw_system_column='i(access,sn)',
        raw_system_direction='current that exits access device through node sn',
        raw_system_to_target_multiplier=-1,
        raw_system_current_A=[row['values']['i(access,sn)'] for row in canonical],
        positive_endpoint_exact_opposite_count=len(canonical)-1,checked_device_ports=PORTS,
        initial_device_row_1based=canonical_device[0]['row_1based'],
        initial_current_integrated=False,
        initial_note='Current comes from full-coupled device initialization; final zero-time circuit reevaluation is preserved separately and never integrated',
        direction_reference=dict(document='Sentaurus Device User Guide W-2024.09',
            printed_and_pdf_page=1797,section='Appendix G / System / Table 366',
            metric_contract='Original fixed metrics i_sn_A is total terminal current into device at SN'),
        sign_chosen_from='Official System direction and original metric semantics, not metric outcome')
    require(all(b>a for a,b in zip(trace['time_s'],trace['time_s'][1:])),'Canonical actual times are not strictly increasing')
    return dict(schema=SCHEMA,trace=trace,current_mapping=current_mapping,circuit=circuit,device=device,accepted_intervals=accepted,
        attempts=attempts,rejected_or_unconverged_attempts=[v for v in attempts if not v['success'] or v['rejected']],
        writing_records=writes,segments=segments,zero_duration_events=events,
        initialization=dict(circuit_rows=cg[0],device_rows=dg[0],selected_circuit_row_1based=cg[0][-1]['row_1based'],
            selected_device_row_1based=dg[0][-1]['row_1based'],elapsed_s=0.,initial_current_integrated=False,
            physical_start='Final original zero-time circuit state after full initialization/release; node voltages equal the verified full-coupled state',**initial_log),
        canonical_circuit_row_indices=[v['row_1based'] for v in canonical],
        canonical_device_row_indices=[r['row_1based'] for r in canonical_device],
        provenance=dict(circuit_plt_sha256=_digest(circuit_raw),device_plt_sha256=_digest(device_plt_raw),
            native_log_sha256=_digest(log_raw),device_cmd_sha256=_digest(deck_raw)),
        association='Full successful BE order and complete original PLT sequence; every from/to/dt print interval and declared/native segment checked',
        endpoint_rule='Positive circuit first row, proven by exact opposite four-port device TotalCurrent; never chosen by magnitude or metric',
        native_qualified=False,is_tcad_result=False)


def source_index(audit_result,files,generation_field,window,source_present):
    require(audit_result.get('schema')==SCHEMA,'Unknown audited actual clock')
    table=audit_result['device'];by_row={r['row_1based']:r for r in table['raw_rows']}
    rows=[by_row[i]['values'] for i in audit_result['canonical_device_row_indices']]
    columns=[n for n in table['columns'] if n.endswith(generation_field)]
    require(bool(columns)==source_present,'Actual PLT source presence differs from explicit source role')
    require(files and len(files)==len(set(files)),'Missing or duplicate original field inventory')
    require(len(window)==2 and rows[0]['time']<=window[0]<window[1]<=rows[-1]['time'],'Native source window is not covered')
    selected=[w for w in audit_result['writing_records'] if w['source_file'] in files]
    require(len(selected)==len(files) and {w['source_file'] for w in selected}==set(files),'Source files do not map once to actual Writing records')
    accepted={v['attempt_index']:v for v in audit_result['accepted_intervals']}
    segments={v['segment_index']:v for v in audit_result['segments']}
    frames=[]
    for record in selected:
        attempt=record['attempt_index']
        if attempt is None:
            require(record['segment_index'] in segments,'Source frame has no native transient phase')
            time=segments[record['segment_index']]['start_actual_s']
            item=dict(accepted_index=None,start_s=time,end_s=time,dt_s=0.,BE_log_line=None,
                frame_kind='segment_initial_state',contributes_to_BE_integral=False)
        else:
            require(attempt in accepted,'Rejected/unconverged BE attempt wrote a source field')
            item=dict(accepted[attempt],frame_kind='accepted_BE_endpoint',contributes_to_BE_integral=True)
        item.update(record,direct_TDR_timestamp_verified=False,
            binding='Original Writing line + declared/native segment or successful BE order + original precise PLT time; field metadata still required')
        frames.append(item)
    positive=[f['accepted_index'] for f in frames if f['contributes_to_BE_integral']]
    require(len(positive)==len(set(positive)),'Multiple field files for one BE endpoint; preserve before choosing any integration weight')
    required=[v['accepted_index'] for v in audit_result['accepted_intervals'] if v['end_s']>window[0] and v['start_s']<window[1]]
    require(set(required)<=set(positive),'Missing actual field frame for an accepted source-window interval')
    return dict(schema='dram-see-v4-native-source-clock-2d-r2',native_qualified=False,pmi_clock_fabricated=False,
        accepted_intervals=audit_result['accepted_intervals'],accepted_BE_count=len(audit_result['accepted_intervals']),
        rejected_or_unconverged_attempts=audit_result['rejected_or_unconverged_attempts'],frames=frames,
        boundary_frames=[f for f in frames if not f['contributes_to_BE_integral']],source_window_s=list(window),
        required_source_window_indices=required,source_field=generation_field,source_present=source_present,
        generation_columns=columns,source_scalars=[{key:row[key] for key in ['time']+columns} for row in rows],
        raw_PLT_rows=len(table['raw_rows']),repeated_block_initial_rows=len(table['raw_rows'])-len(rows),
        preserved_device_initialization=audit_result['initialization']['device_rows'],
        zero_duration_circuit_events=audit_result['zero_duration_events'],
        solver_time_bounds_s=[rows[0]['time'],rows[-1]['time']],
        temporal_audit_provenance=audit_result['provenance'],
        interpretation='All original rows preserved in audited clock; boundary frames have zero duration and are not integrated as preceding BE endpoints')
