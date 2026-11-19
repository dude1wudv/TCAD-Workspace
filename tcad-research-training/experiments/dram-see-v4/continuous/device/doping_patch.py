"""Numerically stable evaluation of the existing mixed Gaussian donor profile.

No physical geometry/doping design parameter is changed. The exponent clamp is
a floating-point evaluation guard for an otherwise underflowing deep tail, not
a revised junction-depth model or a tolerance change.
"""
import math

FAILURE_RUN = '20261017T042819Z-v4-continuous-b1-d2-r4'
PATCH_ID = 'general-gaussian-finite-tail-r1'
EXPONENT_LIMIT = 700.0
MAX_ADDED_DONOR_CM3 = 1.45e20 * math.exp(-EXPONENT_LIMIT)


def expression(dimension):
    depth = 'y' if dimension == 2 else 'z'
    weight = '(1-tanh(x/s2_blend))/2'
    def tail(width):
        # The installed General evaluator documents abs, but not min/if.
        # min(q,700) = q-((q-700)+abs(q-700))/2. Below the limit the second
        # term is exactly zero, avoiding cancellation in an ordinary profile.
        # Multiplication spells out q; 0- removes unary/^ precedence ambiguity.
        q = '({0}/{1})*({0}/{1})'.format(depth, width)
        clipped = '({0})-((({0})-700)+abs(({0})-700))/2'.format(q)
        return '(s2_npk*exp(0-({0})))'.format(clipped)
    return '({0})*{1}+(1-({0}))*{2}'.format(weight, tail('s2_asn'), tail('s2_abl'))


def apply(text, dimension):
    depth = 'y' if dimension == 2 else 'z'
    original = 's2_npk*((1-tanh(x/s2_blend))/2*exp(-({0}/s2_asn)^2)+(1-(1-tanh(x/s2_blend))/2)*exp(-({0}/s2_abl)^2))'.format(depth)
    if text.count(original) != 1:
        raise ValueError('Original General donor expression differs; inspect before patching')
    changed = text.replace(original, expression(dimension))
    return changed.replace('; Future native doping audit MUST reject the -1 failure sentinel and incorrect coordinates.',
        '; Native r4 reported FPE. Gaussian exponents now stay within normal-double exp range.\n'
        '; Peak, blend, junction widths and expected physical audit values are unchanged.\n'
        '; Deep-tail numerical floor is at most 1.4296531e-284 cm^-3, below background precision.\n'
        '; Native doping audit still rejects the -1 failure sentinel and incorrect coordinates.')


def original_value(x, depth, sn_junction_depth_nm=87):
    if type(sn_junction_depth_nm) is not int or sn_junction_depth_nm not in (82,87,92):
        raise ValueError('SN junction depth must be 82, 87 or 92 nm')
    sn = (sn_junction_depth_nm/1000.) / math.sqrt(math.log(1450.))
    bl = .1375 / math.sqrt(math.log(1450.))
    w = (1-math.tanh(x/.005))/2
    return 1.45e20 * (w*math.exp(-(depth/sn)**2)+(1-w)*math.exp(-(depth/bl)**2))


def stable_value(x, depth, sn_junction_depth_nm=87):
    if type(sn_junction_depth_nm) is not int or sn_junction_depth_nm not in (82,87,92):
        raise ValueError('SN junction depth must be 82, 87 or 92 nm')
    sn = (sn_junction_depth_nm/1000.) / math.sqrt(math.log(1450.))
    bl = .1375 / math.sqrt(math.log(1450.))
    w = (1-math.tanh(x/.005))/2
    def tail(width):
        q = (depth/width)*(depth/width)
        clipped = q-((q-700)+abs(q-700))/2
        return 1.45e20 * math.exp(-clipped)
    return w*tail(sn)+(1-w)*tail(bl)
