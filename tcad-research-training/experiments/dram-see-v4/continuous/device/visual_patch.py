"""Bind the current geometry observer to the established native plot/geom API."""

FAILURE_RUN = '20261017T043418Z-v4-continuous-b1-d2-r5'
PATCH_ID = 'svisual-explicit-plot-geom-r1'
IN_PROCESS_IDENTITY_ID = 'svisual-in-process-mesh-identity-r1'


def apply(text):
    replacements = (
        ('integrate_field -dataset $s2_dataset -field $field',
         'integrate_field -plot $s2_plot -geom $s2_dataset -field $field'),
        ('calculate_field_value -dataset $s2_dataset -field $field -min',
         'calculate_field_value -plot $s2_plot -geom $s2_dataset -field $field -min'),
        ('calculate_field_value -dataset $s2_dataset -field $field -max',
         'calculate_field_value -plot $s2_plot -geom $s2_dataset -field $field -max'),
        ('create_field -dataset $s2_dataset -name ONE',
         'create_field -plot $s2_plot -geom $s2_dataset -name ONE'),
    )
    for original, replacement in replacements:
        if text.count(original) != 1:
            raise ValueError('Original SVisual command differs: ' + original)
        text = text.replace(original, replacement)
    return '# Native r5 context failure: use the already-established explicit -plot/-geom API.\n' + text


def apply_in_process_identity(text):
    """Explicit continuation branch; retain both observed mesh identity checks.

    Reuse the unchanged pure Tcl provider that completed real TDX r10 hashing.
    SVisual has not demonstrated a fork failure, so this is a preventive removal
    of the same external-hash dependency, not a claimed SVisual repair.
    """
    original_globals = '    global s2_mesh s2_expected_sha s2_run_id s2_channels\n'
    original_hash = '''        set output [exec sha256sum -- $s2_mesh]
        if {![regexp {^([0-9a-fA-F]{64})[ *]} $output unused digest]} {
            error "sha256sum did not return a digest"
        }
        set digest [string tolower $digest]
'''
    replacement_hash = '''        if {!$s2_hash_ready} {
            source $s2_hash_provider_script
            ::dram_tdx_sha256::initialize
            set provider [open geometry-hash-provider.csv {WRONLY CREAT EXCL}]
            fconfigure $provider -encoding utf-8 -translation lf
            s2_csv $provider {schema source_path source_sha256 source_bytes tcl_patchlevel package_name package_version backend safe_interpreter unsafe_commands_visible package_unknown_empty known_vectors_verified chunk_bytes maximum_supported_file_bytes algorithm_representation_limit_not_resource_quota}
            s2_csv $provider [::dram_tdx_sha256::provider]
            close $provider
            set s2_hash_ready 1
        }
        set digest [::dram_tdx_sha256::digest_file $s2_mesh]
'''
    if text.count(original_globals) != 1 or text.count(original_hash) != 1:
        raise ValueError('Original SVisual mesh identity implementation differs')
    text = text.replace(original_globals, original_globals.rstrip('\n') +
                        ' s2_hash_ready s2_hash_provider_script\n')
    text = text.replace(original_hash, replacement_hash)
    return ('# Explicit metadata continuation: pure in-process mesh hashing.\n'
            'set s2_hash_ready 0\n'
            'set s2_hash_provider_script [file join [file dirname [info script]] tdx_hash_sha256.tcl]\n'
            + text)
