* r04 L08 full WHR + event4 nodal/matched-zero candidate; labels unknown.
Device Cell {
 File { Grid="cell_msh.tdr" Current="device.plt" Plot="device.tdr"
  OpticalSolverInput="reference-apd.plx" IlluminationSpectrum="reference-spectrum.txt" }
Electrode {
 {Name="WL1" Voltage=0 WorkFunction=4.6} {Name="WL2" Voltage=0 WorkFunction=4.6}
 {Name="BL" Voltage=0} {Name="SN1" Voltage=0} {Name="SN2" Voltage=0} {Name="BODY" Voltage=0}
}
 Physics {
 Temperature=300 Fermi EffectiveIntrinsicDensity(OldSlotboom)
 Mobility(DopingDep HighFieldSaturation Enormal)
 Recombination(SRH(DopingDep) Auger)
 Optics (
  OpticalGeneration (
   ComputeFromSpectrum ( RefreshEveryTime KeepSpectralData )
   QuantumYield ( pmiModel="pmi_r04_nodal" )
  )
  OpticalSolver ( FromFile (
   DatasetName = AbsorbedPhotonDensity SpectralInterpolation = Off
   IdentifyingParameter = ("Wavelength")
  ) )
  Excitation (
   Wavelength=1 Intensity=1 Theta=0 Phi=0
   Window ("r04_fixed_basis") (
    Origin=(0 0 -0.01) XDirection=(1 0 0) YDirection=(0 1 0)
    Rectangle ( Corner1=(-0.01 -0.01) Corner2=(0.164 0.05) )
    -WeightedAPDintegration
   )
  )
 )
 }
CurrentPlot {
 OpticalGeneration(Integrate(Semiconductor))
 AbsorbedPhotonDensity(Integrate(Semiconductor) Minimum(Semiconductor) Maximum(Semiconductor))
 QuantumYield(Integrate(Semiconductor) Minimum(Semiconductor) Maximum(Semiconductor))
 eDensity(Integrate(Semiconductor)) hDensity(Integrate(Semiconductor))
 PMIUserField0(Integrate(Semiconductor) Minimum(Semiconductor) Maximum(Semiconductor))
 PMIUserField1(Minimum(Semiconductor) Maximum(Semiconductor))
 PMIUserField2(Minimum(Semiconductor) Maximum(Semiconductor))
 PMIUserField3(Minimum(Semiconductor) Maximum(Semiconductor))
 PMIUserField4(Integrate(Semiconductor))
 PMIUserField5(Minimum(Semiconductor) Maximum(Semiconductor))
}
}
File { Output="transient" PMIPath="." }
Plot { Potential ElectricField/Vector Doping DonorConcentration AcceptorConcentration
 eDensity hDensity eCurrent/Vector hCurrent/Vector TotalCurrent/Vector
 AbsorbedPhotonDensity QuantumYield OpticalGeneration
 PMIUserField0 PMIUserField1 PMIUserField2 PMIUserField3 PMIUserField4 PMIUserField5 }
Math { Number_Of_Threads=1 CoordinateSystem {AsIs} RelErrControl Digits=5
 ErrRef(electron)=1e7 ErrRef(hole)=1e7 Iterations=30 NotDamped=100 ExitOnFailure
 Transient=BE Method=Blocked SubMethod=ILS(set=1) PrintLinearSolver CurrentPlot(IntegrationUnit=cm) }
System {
 Cell access ("SN1"=sn1 "SN2"=sn2 "BL"=bl "WL1"=wl1 "WL2"=wl2 "BODY"=0)
 Vsource_pset vwl1 (wl1 0) {pwl=(0 0 10.2e-9 0 10.3e-9 2.5 18e-9 2.5 18.1e-9 0
  30.1e-9 0 30.2e-9 2.5 32e-9 2.5 32.1e-9 0 35e-9 0)}
 Vsource_pset vwl2 (wl2 0) {pwl=(0 0 2e-9 0 2.1e-9 2.5 10e-9 2.5 10.1e-9 0 35e-9 0)}
 Vsource_pset vdrive (drive 0) {pwl=(0 0 18.1e-9 0 18.2e-9 0.6 35e-9 0.6)}
 Vsource_pset vplate (plate 0) {dc=0.6}
 Resistor_pset rdrive (bl drive) {resistance=1000}
 Capacitor_pset cstore1 (sn1 plate) {capacitance=2e-14}
 Capacitor_pset cstore2 (sn2 plate) {capacitance=2e-14}
 Capacitor_pset cbl (bl 0) {capacitance=2e-13}
 Set(sn1=0.6) Set(sn2=0.6)
 Plot "circuit.plt" (time() v(sn1) v(sn2) v(bl) v(wl1) v(wl2) v(plate) v(drive)
  i(access,sn1) i(access,sn2) i(access,bl) i(access,wl1) i(access,wl2) i(access,0)
  i(cstore1,sn1) i(cstore2,sn2) i(cbl,bl) i(rdrive,bl))
}
Solve {
 access.Optics
 Coupled(Iterations=100) {Poisson}
 Coupled(Iterations=100) {Poisson Electron Hole Contact Circuit}
 Plot(FilePrefix="initial")
 Unset(sn1) Unset(sn2)
 Transient(InitialTime=0 FinalTime=1e-13 InitialStep=1e-13 MinStep=1e-18 MaxStep=5.0000000000000003e-10 Increment=1.3) {
  Coupled {Poisson Electron Hole Contact Circuit}
 }
 Plot(FilePrefix="diagnostic-final")
}
