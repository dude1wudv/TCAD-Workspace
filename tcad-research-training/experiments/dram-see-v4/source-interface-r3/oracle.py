"""Document Eq810 Gaussian oracle; never supplies replacement measured data."""
import math


def mass(a,b,t0,s):
    if not all(math.isfinite(v) for v in (a,b,t0,s)) or s <= 0 or b < a:
        raise ValueError('Invalid temporal interval/kernel')
    a = max(a,0.)
    if b <= a:
        return 0.
    x,y = (a-t0)/(math.sqrt(2)*s),(b-t0)/(math.sqrt(2)*s)
    if x >= 0:
        numerator = math.erfc(x)-math.erfc(y)
    elif y <= 0:
        numerator = math.erfc(-y)-math.erfc(-x)
    else:
        numerator = math.erf(y)-math.erf(x)
    return numerator/(1+math.erf(t0/(math.sqrt(2)*s)))


def instantaneous(t,t0,s):
    if t < 0:
        return 0.
    return 2*math.exp(-.5*((t-t0)/s)**2)/(math.sqrt(2)*s*math.sqrt(math.pi)*(1+math.erf(t0/(math.sqrt(2)*s))))


def step_average(a,b,t0,s):
    if b <= a:
        raise ValueError('A BE source sample needs a positive accepted interval')
    return mass(a,b,t0,s)/(b-a)


def rectangular(rows,key,time_moment=False):
    return math.fsum(b[key]*(b['time']-a['time'])*((a['time']+b['time'])/2 if time_moment else 1.)
                     for a,b in zip(rows,rows[1:]))
