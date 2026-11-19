"""Declared 3D linear-solver branch. No process launch or resource quota."""

PATCH_ID = 'three-dimensional-default-ils-set1-r1'


def apply(text, dimension, mixed=False):
    if type(dimension) is not int or dimension not in (2, 3):
        raise ValueError('Dimension must be 2 or 3')
    if mixed and dimension == 2:
        old = ' Transient=BE Method=Blocked SubMethod=ParDiSo\n'
        if text.count(old) != 1 or 'PrintLinearSolver' in text or 'ILS(' in text:
            raise ValueError('Expected original 2D mixed ParDiSo numerical block')
        return text.replace(old, old+' NumberOfThreads=1 NumberOfAssemblyThreads=1 NumberOfSolverThreads=1\n PrintLinearSolver\n')
    if dimension == 2:
        return text
    old = ' Transient=BE Method=Blocked SubMethod=ParDiSo\n' if mixed else ' Method=ParDiSo\n'
    new = (' Transient=BE Method=Blocked SubMethod=ILS(set=1)\n' if mixed
           else ' Method=ILS(set=1)\n')
    new += (' NumberOfThreads=1 NumberOfAssemblyThreads=1 NumberOfSolverThreads=1\n'
            ' PrintLinearSolver\n')
    if text.count(old) != 1 or 'PrintLinearSolver' in text or 'ILS(' in text:
        raise ValueError('Expected unchanged original ParDiSo numerical block')
    return text.replace(old, new)


def contract(dimension, mixed=False):
    if dimension == 2 and mixed:
        return dict(schema='dram-see-v4-numerical-method-2d-mixed-r1', branch_id='two-dimensional-mixed-pardiso-r1',
            dimension=2, mixed_mode=True, method='Blocked', submethod='ParDiSo',
            computational_threads=dict(assembly=1, linear_solver=1), os_total_thread_count_claim=None,
            time_integrator='BE', native_verified=False, physics_parameters_changed=False, acceptance_thresholds_changed=False,
            nonlinear_controls=dict(RelErrControl=True, Digits=5, ErrRef_electron=1e7, ErrRef_hole=1e7,
                                    Iterations=30, Notdamped=100, ExitOnFailure=True),
            source_dc_run='20261017T051217Z-v4-continuous-b1-d2-r8',
            selection_basis='Keep the actual D2 ParDiSo solver in the existing Blocked mixed-mode structure; no 3D ILS assumption transferred',
            qualification='Actual write/read, KCL and time/mesh refinement remain required')
    return dict(schema='dram-see-v4-numerical-method-r1', branch_id=PATCH_ID if dimension == 3 else 'original-2d-pardiso',
        dimension=dimension, mixed_mode=mixed,
        method='Blocked' if mixed else 'ILS(set=1)' if dimension == 3 else 'ParDiSo',
        submethod='ILS(set=1)' if mixed else None,
        computational_threads=dict(assembly=1, linear_solver=1), os_total_thread_count_claim=None,
        native_verified=False, physics_parameters_changed=False, acceptance_thresholds_changed=False,
        nonlinear_controls=dict(RelErrControl=True, Digits=5, ErrRef_electron=1e7,
                                ErrRef_hole=1e7, Iterations=30, Notdamped=100, ExitOnFailure=True),
        vendor_evidence=dict(document='Sentaurus Device User Guide W-2024.09',
            pages=[220, 221, 241, 242, 243, 1669],
            basis='ILS(set=1) is the documented 3D default; CLI thread limits override Math settings'),
        selection_basis=dict(observed_2d_run='20261017T051217Z-v4-continuous-b1-d2-r8',
            observed_2d_vertices=95993, observed_2d_VmHWM_kB=2373952,
            decision='Use the installed vendor 3D default iterative solver because direct-factor fill can grow in 3D',
            extrapolated_memory_prediction=None, resource_limit=None, custom_ILSrc=None),
        qualification='Real linear/nonlinear residuals and original current, KCL, write/read and refinement gates remain required')
