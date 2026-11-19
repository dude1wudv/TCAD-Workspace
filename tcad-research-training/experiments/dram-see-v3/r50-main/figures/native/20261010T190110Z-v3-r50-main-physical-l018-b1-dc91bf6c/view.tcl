set data [load_file {/home/tcad/research-training/runs/20261010T190110Z-v3-r50-main-physical-l018-b1-dc91bf6c/final_access_des.tdr}]
set plot [create_plot -dataset $data]
set_plot_prop -plot $plot -title {v3 R50-main actual 4 ns signal E-field (not a readout curve) | 20261010T190110Z-v3-r50-main-physical-l018-b1-dc91bf6c | V/cm, coordinates um}
foreach f [list_fields -plot $plot -show] {set_field_prop -plot $plot -geom $data $f -hide -hide_bands}
set_field_prop -plot $plot -geom $data Abs(ElectricField-V) -show -show_bands -scale log -levels 41
zoom_plot -plot $plot -reset
export_view {/home/tcad/research-training/dram-see-v3/r50-main-gui/20261010T190110Z-v3-r50-main-physical-l018-b1-dc91bf6c/final-field-native.png} -plots $plot -resolution 1400x1000 -format PNG -overwrite
set proof [open {/home/tcad/research-training/dram-see-v3/r50-main-gui/20261010T190110Z-v3-r50-main-physical-l018-b1-dc91bf6c/native-proof.txt} w]
puts $proof [list_fields -dataset $data]
puts $proof {V3_R50_MAIN_NATIVE_FIELD_EXPORT_COMPLETED 20261010T190110Z-v3-r50-main-physical-l018-b1-dc91bf6c 6ba3d7f5986e8c9b25926c2edfd9c6bb963a78a6cc2331c048a7b4dc0c2a48ac}
close $proof
