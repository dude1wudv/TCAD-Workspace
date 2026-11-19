set data [load_file {/home/tcad/research-training/runs/20261010T203923Z-v3-r50-main-l018-alpha-a30-s202610311-b1-babd5730/final_access_des.tdr}]
set plot [create_plot -dataset $data]
set_plot_prop -plot $plot -title {v3 R50-main actual 4 ns signal E-field (not a readout curve) | 20261010T203923Z-v3-r50-main-l018-alpha-a30-s202610311-b1-babd5730 | V/cm, coordinates um}
foreach f [list_fields -plot $plot -show] {set_field_prop -plot $plot -geom $data $f -hide -hide_bands}
set_field_prop -plot $plot -geom $data Abs(ElectricField-V) -show -show_bands -scale log -levels 41
zoom_plot -plot $plot -reset
export_view {/home/tcad/research-training/dram-see-v3/r50-main-gui/20261010T203923Z-v3-r50-main-l018-alpha-a30-s202610311-b1-babd5730/final-field-native.png} -plots $plot -resolution 1400x1000 -format PNG -overwrite
set proof [open {/home/tcad/research-training/dram-see-v3/r50-main-gui/20261010T203923Z-v3-r50-main-l018-alpha-a30-s202610311-b1-babd5730/native-proof.txt} w]
puts $proof [list_fields -dataset $data]
puts $proof {V3_R50_MAIN_NATIVE_FIELD_EXPORT_COMPLETED 20261010T203923Z-v3-r50-main-l018-alpha-a30-s202610311-b1-babd5730 9c7171232bedbd53eca606fcd7d83417beedef8bd39bd8a34528af05528dbd19}
close $proof
