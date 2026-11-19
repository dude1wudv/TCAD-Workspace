"""Analytic prescribed 3D Gaussian source; never native or measured TCAD data."""
import math


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _time_args(t0, sigma):
    if not finite(t0) or not finite(sigma) or t0 < 0 or sigma <= 0:
        raise ValueError('Invalid time center or sigma')


def time_density(t, t0, sigma):
    _time_args(t0, sigma)
    if not finite(t):
        raise ValueError('Invalid time')
    if t < 0:
        return 0.
    return (2 * math.exp(-.5 * ((t-t0)/sigma)**2)
            / (math.sqrt(2*math.pi)*sigma*(1+math.erf(t0/(math.sqrt(2)*sigma)))))


def time_mass(a, b, t0, sigma):
    _time_args(t0, sigma)
    if not all(finite(v) for v in (a, b)) or b < a:
        raise ValueError('Invalid time interval')
    a = max(a, 0.)
    if b <= a:
        return 0.
    x, y = (a-t0)/(math.sqrt(2)*sigma), (b-t0)/(math.sqrt(2)*sigma)
    if x >= 0:
        numerator = math.erfc(x)-math.erfc(y)
    elif y <= 0:
        numerator = math.erfc(-y)-math.erfc(-x)
    else:
        numerator = math.erf(y)-math.erf(x)
    return numerator/(1+math.erf(t0/(math.sqrt(2)*sigma)))


def step_average(a, b, t0, sigma):
    if b <= a:
        raise ValueError('A BE interval must have positive length')
    return time_mass(a, b, t0, sigma)/(b-a)


def time_moment(a, b, t0, sigma):
    mass = time_mass(a, b, t0, sigma)
    if b <= max(a, 0.):
        return 0.
    return t0*mass + sigma**2*(
        time_density(max(a, 0.), t0, sigma)-time_density(b, t0, sigma))


def _vertical(track):
    if track.get('direction') != [0., 1., 0.]:
        raise ValueError('This analytic oracle only accepts the registered +y source')
    start = track.get('start_um')
    if not isinstance(start, list) or len(start) != 3 or not all(finite(v) for v in start):
        raise ValueError('Three finite start coordinates required')
    if not all(finite(track.get(k)) and track[k] > 0 for k in ('length_um', 'wt_hi_um')):
        raise ValueError('Positive track length and Gaussian width required; point deposition unsupported')


def _gaussian_moments(lo, hi, center, width):
    a, b = (lo-center)/width, (hi-center)/width
    if a >= 0:
        fraction = (math.erfc(a)-math.erfc(b))/2
    elif b <= 0:
        fraction = (math.erfc(-b)-math.erfc(-a))/2
    else:
        fraction = (math.erf(b)-math.erf(a))/2
    moment = center*fraction + width/(2*math.sqrt(math.pi))*(math.exp(-a*a)-math.exp(-b*b))
    return fraction, moment


def box_moments(track, bounds):
    """Return integral (1,x,y,z) against normalized 3D spatial source, units 1,um.

    bounds are xmin,ymin,zmin,xmax,ymax,zmax. No clipped charge renormalization.
    A +y uniform finite segment separates into two transverse Gaussians.
    """
    _vertical(track)
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 6
            or not all(finite(v) for v in bounds) or any(bounds[i] >= bounds[i+3] for i in range(3))):
        raise ValueError('Invalid 3D box')
    x, y, z = track['start_um']
    length, width = track['length_um'], track['wt_hi_um']
    lo, hi = max(y, bounds[1]), min(y+length, bounds[4])
    if hi <= lo:
        return (0., 0., 0., 0.)
    fx, mx = _gaussian_moments(bounds[0], bounds[3], x, width)
    fz, mz = _gaussian_moments(bounds[2], bounds[5], z, width)
    fy, my = (hi-lo)/length, (hi*hi-lo*lo)/(2*length)
    return (fx*fy*fz, mx*fy*fz, fx*my*fz, fx*fy*mz)


def spatial_density(track, x, y, z):
    """Normalized spatial density in um^-3; exactly no 2D thickness factor."""
    _vertical(track)
    if not all(finite(v) for v in (x, y, z)):
        raise ValueError('Invalid spatial coordinate')
    sx, sy, sz = track['start_um']
    if not 0 <= y-sy < track['length_um']:
        return 0.
    width = track['wt_hi_um']
    return math.exp(-((x-sx)**2+(z-sz)**2)/width**2)/(math.pi*width**2*track['length_um'])
