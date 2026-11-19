"""Pure continuous DC/write-read templates; no scheduler or historic writer."""
import math
from decimal import Decimal

def validate_model(model):
    from geometry import validate_geometry
    report=validate_geometry(model)
    if not report['passed']:
        raise ValueError('Invalid declared geometry: '+ '; '.join(report['errors']))
    c=model['circuit']
    expected=dict(Cstore_fF=20,Cbl_fF=200,VDD_V=1.2,Vplate_V=.6,Vbl_precharge_V=.6,Vbody_V=0,Vwl_on_V=1.8,Vwl_off_V=-.5,driver_on_resistance_ohm=1000,driver_off_resistance_ohm=1e15,initial_Vsn_V=.6)
    if any(c.get(k)!=v for k,v in expected.items()):
        raise ValueError('Only the established write/hold/read circuit is supported')


PHYSICS = """Fermi EffectiveIntrinsicDensity(OldSlotboom)
 Mobility(DopingDep HighFieldSaturation Enormal)
 Recombination(SRH(DopingDep) Auger Band2Band(Model=NonlocalPath))"""

PLOTS = """eDensity hDensity Potential ElectricField/Vector Doping
 DonorConcentration AcceptorConcentration
 TotalCurrent/Vector eCurrent/Vector hCurrent/Vector
 eBand2BandGeneration hBand2BandGeneration"""

TIMING_NS = [0, 2, 2.1, 6, 6.1, 6.2, 8.1, 14.9984, 15.0016,
             19.9, 20, 20.1, 21.9, 22, 22.1, 25]

def num(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite non-boolean numeric value required")
    return format(value, ".17g")

def electrodes():
    return ('Electrode { {Name="source" Voltage=0} {Name="drain" Voltage=0}\n'
            ' {Name="gate" Voltage=0 WorkFunction=4.6} {Name="body" Voltage=0} }\n')

def math_block(mixed=False):
    return ('Math { CoordinateSystem { AsIs }\n'
            ' RelErrControl Digits=5 ErrRef(electron)=1e7 ErrRef(hole)=1e7\n'
            ' Iterations=30 Notdamped=100 ExitOnFailure\n'
            + (' Transient=BE Method=Blocked SubMethod=ParDiSo\n' if mixed else ' Method=ParDiSo\n')
            + '}\n')

def render_dc(model, dimension=3):
    validate_model(model)
    if dimension not in (2, 3):
        raise ValueError("DC dimension must be 2 or 3")
    area = .02 if dimension == 2 else 1
    text = ('* Offline S2 DC review input; no particle source.\n'
            'File { Grid="cell_msh.tdr" Current="dc" Plot="dc" Output="dc" Parameter="physics.par" }\n'
            + electrodes() + 'Physics { AreaFactor=' + num(area) + ' Temperature=300\n '
            + PHYSICS + '\n}\nPlot { ' + PLOTS + ' }\n' + math_block()
            + 'Solve {\n Coupled(Iterations=100) {Poisson}\n'
            ' Coupled(Iterations=100) {Poisson Electron Hole}\n Save(FilePrefix="equilibrium")\n')
    for label, drain in (("low", .1), ("high", 1.2)):
        text += (' Load(FilePrefix="equilibrium")\n NewCurrentPrefix="settle_' + label + '_"\n'
                 ' Quasistationary(InitialStep=0.001 MinStep=1e-8 MaxStep=0.02 Increment=1.3\n'
                 '  Goal {Name="gate" Voltage=-0.5} Goal {Name="drain" Voltage=' + num(drain) + '})\n'
                 ' { Coupled {Poisson Electron Hole} }\n NewCurrentPrefix="idvg_' + label + '_"\n'
                 ' Quasistationary(InitialStep=0.001 MinStep=1e-8 MaxStep=0.005 Increment=1.3\n'
                 '  Goal {Name="gate" Voltage=1.5}) {\n  Coupled {Poisson Electron Hole}\n'
                 '  CurrentPlot(Time=(Range=(0 1) Intervals=200))\n }\n')
    return text + ' Plot(FilePrefix="dc_final")\n}\n'

def transient_segments(model, time_scale=1, observation_window_s=None, observation_max_step_s=None):
    validate_model(model)
    if time_scale not in (1, .5):
        raise ValueError("Only main or dt/2 is defined")
    if observation_window_s is not None:
        window=observation_window_s
        if (not isinstance(window,(list,tuple)) or len(window)!=2
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in window)
                or not 8.1e-9<window[0]<window[1]<=19.9e-9
                or type(observation_max_step_s) not in (int,float)
                or not math.isfinite(observation_max_step_s) or observation_max_step_s<=0):
            raise ValueError('Complete observation window must fit the existing hold/collection interval; no late clipping')
        points=sorted(set([float(Decimal(str(t))*Decimal('1e-9')) for t in TIMING_NS
                           if t not in (14.9984,15.0016)]+list(window)))
        return [dict(start_s=lo,end_s=hi,
            max_step_s=(observation_max_step_s if lo>=window[0] and hi<=window[1]
                        else 1e-11 if (hi-lo)/1e-9<=.100000001 else 1e-10)*time_scale,
            source_window=lo>=window[0] and hi<=window[1],change_resistance_before=lo==8.1e-9)
            for lo,hi in zip(points,points[1:])]
    segments = []
    for lo, hi in zip(TIMING_NS, TIMING_NS[1:]):
        pulse = lo == 14.9984
        max_step = (4e-14 if pulse else (1e-11 if hi-lo <= .100000001 else 1e-10)) * time_scale
        segments.append({"start_s": lo*1e-9, "end_s": hi*1e-9,
                         "max_step_s": max_step,
                         "source_window": pulse,
                         "change_resistance_before": lo == 8.1})
    return segments

def render_transient(model, bit, source_block="", source_plot="", time_scale=1,
                     observation_window_s=None, observation_max_step_s=None, dimension=3, effective_width_nm=None):
    validate_model(model)
    if type(dimension) is not int or dimension not in (2,3):
        raise ValueError('Transient dimension must be explicit 2 or 3')
    if dimension==2 and (effective_width_nm!=20 or source_block or source_plot):
        raise ValueError('2D branch currently supports only source-free 20nm A0; 3D sources cannot be reused')
    if dimension==3 and effective_width_nm is not None:
        raise ValueError('A 2D effective width cannot reinterpret the original 3D deck')
    if type(bit) is not int or bit not in (0, 1):
        raise ValueError("Stored bit must be integer 0 or 1")
    c = model["circuit"]
    if c["Cstore_fF"] != 20 or c["Cbl_fF"] != 200:
        raise ValueError("S2 circuit changed; new contract required")
    vwrite = 1.2 * bit
    text = ('* Offline S2 actual write/hold/read; common clamped initialization, released before t=0.\n'
            'Device Cell {\n File { Grid="cell_msh.tdr" Current="device.plt" Plot="device.tdr" Parameter="physics.par" }\n'
            + electrodes() + ' Physics { AreaFactor=' + ('0.02' if dimension==2 else '1') + ' Temperature=300\n ' + PHYSICS + '\n' + source_block + '\n }\n}\n'
            'File { Output="transient" }\nPlot { ' + PLOTS + ' ' + source_plot + ' }\n'
            + math_block(True) + 'System {\n'
            ' Cell access ("source"=sn "drain"=bl "gate"=wl "body"=0)\n'
            ' Vsource_pset vwl (wl 0) {pwl=(0 -0.5 2e-9 -0.5 2.1e-9 1.8 6e-9 1.8 6.1e-9 -0.5 '
            '20e-9 -0.5 20.1e-9 1.8 22e-9 1.8 22.1e-9 -0.5 25e-9 -0.5)}\n'
            ' Vsource_pset vdrive (drive 0) {pwl=(0 ' + num(vwrite) + ' 6.1e-9 ' + num(vwrite) + ' 6.2e-9 0.6 25e-9 0.6)}\n'
            ' Vsource_pset vplate (plate 0) {dc=0.6}\n'
            ' Resistor_pset rdrive (bl drive) {resistance=1000}\n'
            ' Capacitor_pset cstore (sn plate) {capacitance=2e-14}\n'
            ' Capacitor_pset cbl (bl 0) {capacitance=2e-13}\n'
            ' Set(sn=0.6)\n'
            ' Plot "circuit.plt" (time() v(sn) v(bl) v(wl) v(plate) v(drive) '
            'i(access,sn) i(access,bl) i(access,wl) i(access,0) i(cstore,sn) i(cbl,bl) i(rdrive,bl))\n}\n'
            'Solve {\n Coupled(Iterations=100) {Poisson}\n'
            ' Coupled(Iterations=100) {Poisson Electron Hole Contact Circuit}\n'
            ' Plot(FilePrefix="initial")\n Unset(sn)\n')
    segments=transient_segments(model,time_scale,observation_window_s,observation_max_step_s)
    for n, seg in enumerate(segments):
        if seg["change_resistance_before"]:
            text += ' Set(rdrive."resistance"=1e15)\n'
        step = seg["max_step_s"]
        text += (' Transient(InitialTime=' + num(seg["start_s"]) + ' FinalTime=' + num(seg["end_s"])
                 + ' InitialStep=' + num(min(step/10, 1e-13)) + ' MinStep=1e-18 MaxStep=' + num(step)
                 + ' Increment=1.3) {\n  Coupled {Poisson Electron Hole Contact Circuit}\n')
        if seg["source_window"]:
            text += ('  Plot(FilePrefix="source_window" Time=(Range=(' + num(seg["start_s"]) + ' '
                     + num(seg["end_s"]) + ')) NoOverwrite)\n')
        if n == len(segments)-1:
            text += '  Plot(FilePrefix="final" Time=(25e-9))\n'
        text += ' }\n'
    return text + '}\n'
