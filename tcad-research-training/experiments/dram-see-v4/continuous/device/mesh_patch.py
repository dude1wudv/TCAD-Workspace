"""Refine the continuous active doping neighborhood after native r5 errors."""

FAILURE_RUN = '20261017T043418Z-v4-continuous-b1-d2-r5'
PATCH_ID = 'active-doping-gradient-refinement-r1'


def specification(dimension, mesh_scale=1):
    if type(mesh_scale) not in (int, float) or mesh_scale not in (1, .5):
        raise ValueError('Only main or h/2 mesh refinement is supported')
    if dimension == 2:
        spec = dict(native_axis_order='X,Y(depth)', lower_um=[-.1, 0.], upper_um=[.1, .25],
                    max_element_um=[.001, .001], min_element_um=[.0005, .0005])
    elif dimension == 3:
        spec = dict(native_axis_order='X,Y(width),Z(depth)', lower_um=[-.1, -.07, 0.], upper_um=[.1, .07, .25],
                    max_element_um=[.001, .005, .001], min_element_um=[.0005, .0025, .0005])
    else:
        raise ValueError('Dimension must be 2 or 3')
    for key in ('max_element_um', 'min_element_um'):
        spec[key] = [v*mesh_scale for v in spec[key]]
    return spec


def apply(text, dimension, mesh_scale=1):
    marker = '; Uncontacted external boundaries retain natural insulating conditions.'
    if text.count(marker) != 1 or 'Window.ActiveDoping' in text:
        raise ValueError('Original mesh refinement insertion point differs')
    spec = specification(dimension, mesh_scale)
    lower = spec['lower_um'] if dimension == 3 else spec['lower_um'] + [0.]
    upper = spec['upper_um'] if dimension == 3 else spec['upper_um'] + [0.]
    def numbers(values):return ' '.join(format(v, '.12g') for v in values)
    block = '''; Native r5 measured 3.15-21.94 percent interpolation errors at unchanged
; doping probes. Refine the whole active gradient neighborhood, not probe points.
(sdedr:define-refeval-window "Window.ActiveDoping" "{kind}" (position {lower}) (position {upper}))
(sdedr:define-refinement-size "Mesh.ActiveDoping" {maximum} {minimum})
(sdedr:define-refinement-placement "Place.ActiveDoping" "Mesh.ActiveDoping" (list "window" "Window.ActiveDoping" "material" "Silicon"))
'''.format(kind='Rectangle' if dimension == 2 else 'Cuboid', lower=numbers(lower), upper=numbers(upper),
           maximum=numbers(spec['max_element_um']), minimum=numbers(spec['min_element_um']))
    return text.replace(marker, block + marker)
