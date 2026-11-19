set data [load_file {/home/tcad/research-training/runs/20261010T103149Z-v3-physical-l018-b1-33b11a8f/final_access_des.tdr}]
set plot [create_plot -dataset $data]
set_plot_prop -plot $plot -title {v3 actual 4 ns signal E-field (not a readout curve) | 20261010T103149Z-v3-physical-l018-b1-33b11a8f | V/cm, coordinates um}
foreach f [list_fields -plot $plot -show] {set_field_prop -plot $plot -geom $data $f -hide -hide_bands}
set_field_prop -plot $plot -geom $data Abs(ElectricField-V) -show -show_bands -scale log -levels 41
zoom_plot -plot $plot -reset
export_view {/home/tcad/research-training/dram-see-v3/gui/20261010T103149Z-v3-physical-l018-b1-33b11a8f/final-field-native.png} -plots $plot -resolution 1400x1000 -format PNG -overwrite
set proof [open {/home/tcad/research-training/dram-see-v3/gui/20261010T103149Z-v3-physical-l018-b1-33b11a8f/native-proof.txt} w]
puts $proof [list_fields -dataset $data]
puts $proof {V3_NATIVE_FIELD_EXPORT_COMPLETED 20261010T103149Z-v3-physical-l018-b1-33b11a8f b93832c293345c1510ec216114c8a8e2f1b96fbc878566670d94ea9926a4b9a5}
close $proof
