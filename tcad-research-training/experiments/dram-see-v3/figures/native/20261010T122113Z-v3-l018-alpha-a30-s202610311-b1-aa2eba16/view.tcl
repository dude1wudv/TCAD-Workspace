set data [load_file {/home/tcad/research-training/runs/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/final_access_des.tdr}]
set plot [create_plot -dataset $data]
set_plot_prop -plot $plot -title {v3 actual 4 ns signal E-field (not a readout curve) | 20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16 | V/cm, coordinates um}
foreach f [list_fields -plot $plot -show] {set_field_prop -plot $plot -geom $data $f -hide -hide_bands}
set_field_prop -plot $plot -geom $data Abs(ElectricField-V) -show -show_bands -scale log -levels 41
zoom_plot -plot $plot -reset
export_view {/home/tcad/research-training/dram-see-v3/gui/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/final-field-native.png} -plots $plot -resolution 1400x1000 -format PNG -overwrite
set proof [open {/home/tcad/research-training/dram-see-v3/gui/20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16/native-proof.txt} w]
puts $proof [list_fields -dataset $data]
puts $proof {V3_NATIVE_FIELD_EXPORT_COMPLETED 20261010T122113Z-v3-l018-alpha-a30-s202610311-b1-aa2eba16 feea6832e0d859db5f636aeda6e58665d43f890cb6e2ae66b52e898dd9503f82}
close $proof
