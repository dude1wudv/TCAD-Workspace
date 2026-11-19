Device Cell {
 File { Grid="cell_msh.tdr" Current="device.plt" Plot="device.tdr" }
 Electrode { {Name="source" Voltage=0} {Name="drain" Voltage=0} {Name="gate" Voltage=0 WorkFunction=4.6} {Name="body" Voltage=0} }
 Physics { AreaFactor=1 Temperature=300 Fermi EffectiveIntrinsicDensity(OldSlotboom)
 Mobility(DopingDep HighFieldSaturation Enormal) Recombination(SRH(DopingDep) Auger) HeavyIon ( StartPoint=(0.8,0) Direction=(-0.49999999999999994,0.8660254037844387) Time=1e-9 Length=1.3856406460551016 Wt_hi=0.03 LET_f=0.00673709900499838 Gaussian PicoCoulomb ) }
}
File { Output="transient" }
Plot { eDensity hDensity Potential ElectricField/Vector Doping TotalCurrent/Vector eCurrent/Vector hCurrent/Vector HeavyIonChargeDensity HeavyIonGeneration }
CurrentPlot { HeavyIonGeneration(Integrate(Semiconductor)) }
Math { RelErrControl Digits=5 ErrRef(electron)=1e7 ErrRef(hole)=1e7 Iterations=30 Notdamped=100
 Transient=BE Method=Blocked SubMethod=ParDiSo ExitOnFailure }
System {
 Cell access ("source"=bl "drain"=sn "gate"=wl "body"=0)
 Vsource_pset vwl (wl 0) {pwl=(0 0 3.05e-9 0 3.10e-9 1.8 4e-9 1.8)}
 Vsource_pset vpre (pre 0) {pwl=(0 0 2.8e-9 0 2.9e-9 0.5 4e-9 0.5)}
 Resistor_pset rpre (bl pre) {resistance=50}
 Capacitor_pset cstore (sn 0) {capacitance=1e-14}
 Capacitor_pset cbl (bl 0) {capacitance=1e-13}
 Capacitor_pset cref (ref 0) {capacitance=1e-13}
 Resistor_pset rsn (sn 0) {resistance=1e20}
 Resistor_pset rbl (bl 0) {resistance=1e20}
 Resistor_pset rref (ref 0) {resistance=1e20}
 Plot "circuit.plt" (time() v(bl) v(wl) v(sn) v(ref) i(access,sn) i(access,bl)
 i(cstore,sn) i(cbl,bl) i(cref,ref) i(rsn,sn) i(rbl,bl) i(rref,ref) i(rpre,bl))
}
Solve {
 Load(FilePrefix="charged")
 Set(bl=0 ref=0.5)
 Plot(FilePrefix="prestrike")
 Transient(InitialTime=0.95e-9 FinalTime=1.05e-9 InitialStep=2e-13 MinStep=1e-18 MaxStep=1e-12 Increment=1.3) {
 Coupled {Poisson Electron Hole Contact Circuit} Plot(FilePrefix="strike" Time=(1e-9))
 }
 Transient(InitialTime=1.05e-9 FinalTime=2.8e-9 InitialStep=1e-12 MinStep=1e-18 MaxStep=1e-11 Increment=1.4) {
 Coupled {Poisson Electron Hole Contact Circuit} Plot(FilePrefix="hold" Time=(2.8e-9))
 }
 Unset(bl)
 Transient(InitialTime=2.8e-9 FinalTime=3e-9 InitialStep=1e-13 MinStep=1e-18 MaxStep=1e-12 Increment=1.4) {Coupled {Poisson Electron Hole Contact Circuit}}
 Set(rpre."resistance"=1e20)
 Unset(ref)
 Transient(InitialTime=3e-9 FinalTime=4e-9 InitialStep=1e-13 MinStep=1e-18 MaxStep=1e-11 Increment=1.4) {
 Coupled {Poisson Electron Hole Contact Circuit} Plot(FilePrefix="final" Time=(4e-9))
 }
}
