# -*- coding: utf-8 -*-
"""Nominal small-pitch GT conjugate geometry, without machining allowance.

The INPUT is the original Gates Unitta belt drawing (catalog pp. 46, 50, 54),
not a purported factory pulley groove drawing. US4515577A describes generating
the minimum pulley cavity by sweeping the belt tooth while its pitch line rolls
on the pulley pitch circle. This module implements that construction. It does
not certify the proprietary production groove, clearance, or manufacturing fit.

Coordinates on the straight belt are (x, d), with d positive into the tooth from
the belt land. R is the pulley pitch radius, u the pitch-line differential.
At rolling angle t the belt boundary in pulley coordinates is

    Q(a,t) = Rot(t) (x(a) + R*t, R - u - d(a)).

The envelope condition det(Q_a,Q_t)=0 gives

    t = (-(u+d)*d'/x' - x)/R.

For a source circle (cx,cd), radius r, x=cx+r*cos(a), d=cd+r*sin(a),
this simplifies exactly to t=((u+cd)*cot(a)-cx)/R. No circle is fitted to
the generated groove. Folded, hidden envelope branches at the concave belt
root are trimmed against the convex flank envelope. The reference chord chain
has an analytic second-derivative bound. prepare_smooth_profile constructs C2
splines with a conservative total error bound; outer lands stay exact arcs.
"""

import math

from . import geometry as G
from . import spline

SOURCE = 'https://www.unitta.co.jp/data/support/pdf/cat-b02-14/cat-b01-20_P014_087.pdf'
PATENT = 'https://patents.google.com/patent/US4515577A/en'
STANDARD_NOTE = ('原厂带齿尺寸 + 滚动包络的理论共轭槽；无加工间隙；'
                 '不是原厂量产轮槽认证，不能据此保证制造配合。')

# Independent catalog dimensions, mm. b is the flat land BETWEEN belt teeth.
# PLD is a radial pitch-line differential, not a diametral OD reduction.
SPECS = {
    '2GT': {'pitch': 2.0, 'pld': 0.254, 'h': 0.75, 'b': 0.40,
            'root_radius': 0.15, 'flank_radius': 1.0, 'tip_radius': 0.555,
            'catalog_page': 46},
    '3GT': {'pitch': 3.0, 'pld': 0.381, 'h': 1.14, 'b': 0.61,
            'root_radius': 0.25, 'flank_radius': 1.52, 'tip_radius': 0.85,
            'catalog_page': 50},
    '5GT': {'pitch': 5.0, 'pld': 0.5715, 'h': 1.93, 'b': 1.03,
            'root_radius': 0.51, 'flank_radius': 2.54, 'tip_radius': 1.37,
            'catalog_page': 54},
}


def get_spec(model_id):
    """Return a copy; these three pitches are not scaled from one another."""
    return dict(SPECS[model_id])


class GTResult(G.GrooveResult):
    __slots__ = ('profile_chain', 'model', 'source', 'standard_note',
                 'approximation_tolerance', 'generation_method',
                 'envelope_pieces', 'nominal_belt_spec', 'sampling_mode',
                 'samples_per_tooth', 'half_profile_points', 'smooth_curves',
                 'smooth_error_bound', 'smooth_samples_per_tooth')

    def __init__(self, **kw):
        # The base initializer iterates self.__slots__, so initialize its slots
        # explicitly when subclassing rather than calling its initializer.
        for name in G.GrooveResult.__slots__:
            setattr(self, name, kw.get(name))
        for name in self.__slots__:
            setattr(self, name, kw.get(name))
        self.warnings = list(kw.get('warnings') or [])

    def as_dict(self):
        if self.ok:
            result = G.GrooveResult.as_dict(self)
        else:
            result = {'ok': False, 'message': self.message,
                      'warnings': list(self.warnings)}
        result.update(model=self.model, source=self.source,
                      generation_method=self.generation_method,
                      standard_note=self.standard_note,
                      approximation_tolerance=self.approximation_tolerance,
                      sampling_mode=self.sampling_mode,
                      samples_per_tooth=self.samples_per_tooth,
                      smooth_error_bound=self.smooth_error_bound,
                      smooth_samples_per_tooth=self.smooth_samples_per_tooth,
                      smooth_continuity='C2' if self.smooth_curves else None,
                      patent=PATENT,
                      nominal_belt_spec=dict(self.nominal_belt_spec or {}),
                      machining_clearance=0.0,
                      factory_groove_certified=False)
        return result


def _belt_arcs(spec):
    """Right half, from land to tip, as (center, radius, a0, a1).

    Root and flank circles are externally tangent; flank and tip circles
    internally tangent. The smaller-depth center is the catalog's flank.
    """
    rr, rf, rt = (spec['root_radius'], spec['flank_radius'], spec['tip_radius'])
    cr = ((spec['pitch'] - spec['b']) / 2.0, rr)
    ct = (0.0, spec['h'] - rt)
    centers = G._circle_intersect(cr, rr + rf, ct, rf - rt)
    if len(centers) != 2:
        raise ValueError('原厂带齿圆弧无法相切')
    cf = min(centers, key=lambda c: c[1])
    pr = (cr[0] + rr * (cf[0] - cr[0]) / (rr + rf),
          cr[1] + rr * (cf[1] - cr[1]) / (rr + rf))
    pt = (cf[0] + rf * (ct[0] - cf[0]) / (rf - rt),
          cf[1] + rf * (ct[1] - cf[1]) / (rf - rt))
    angle = lambda p, c: math.atan2(p[1] - c[1], p[0] - c[0])
    return [(cr, rr, -math.pi / 2.0, angle(pr, cr)),
            (cf, rf, angle(pr, cf), angle(pt, cf)),
            (ct, rt, angle(pt, ct), math.pi / 2.0)]


def _envelope(arc, a, radius, pld):
    (cx, cd), r = arc[:2]
    s, c = math.sin(a), math.cos(a)
    k = pld + cd
    t = (k * c / s - cx) / radius
    return G._rot((k * c / s + r * c, radius - k - r * s), t)


def _polar(arc, a, radius, pld):
    x, y = _envelope(arc, a, radius, pld)
    return math.atan2(x, y), math.hypot(x, y)


def _bisect(function, lo, hi, iterations=64):
    """Bracketed zero; lo and hi may be in either numerical order."""
    fl, fh = function(lo), function(hi)
    if abs(fl) < 1e-13:
        return lo
    if abs(fh) < 1e-13:
        return hi
    if fl * fh > 0.0:
        raise ValueError('滚动包络的可见分支未能形成有效交点')
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        fm = function(mid)
        if fl * fm <= 0.0:
            hi = mid
        else:
            lo, fl = mid, fm
    return (lo + hi) / 2.0


def _at_angle(pieces, angle, radius, pld):
    """Invert an exposed monotone polar branch, including its end points."""
    for arc, a, b in pieces:
        aa = _polar(arc, a, radius, pld)[0]
        ab = _polar(arc, b, radius, pld)[0]
        if ab - 2e-12 <= angle <= aa + 2e-12:
            target = min(aa, max(ab, angle))
            value = _bisect(lambda v: _polar(arc, v, radius, pld)[0] - target,
                            a, b)
            return arc, value, _polar(arc, value, radius, pld)[1]
    raise ValueError('滚动包络的极角超出有效分支')


def _trim_before(pieces, selected_arc, value):
    for index, (arc, _a, b) in enumerate(pieces):
        if arc is selected_arc:
            return [(arc, value, b)] + pieces[index + 1:]
    raise ValueError('包络分支不存在')


def _exposed_pieces(arcs, radius, pld):
    """Remove the concave-root envelope loop analytically, before meshing.

    Each retained branch has decreasing polar angle. The exposed boundary is
    the lower radial envelope of the root, convex flank/tip and outer circle.
    Root folds end at Q'=0. Convex polar folds end where
    R*sin(a)^2 - (u+cd) - r*sin(a)=0. A root/flank double-contact intersection
    trims the remaining loop, rather than connecting disjoint sample points.
    """
    root, flank, tip = arcs
    (_cx, cd), rr, a0, a1 = root
    k = pld + cd
    speed = lambda a: (-rr * math.sin(a)
                       - k * (k + rr * math.sin(a)) /
                       (radius * math.sin(a) ** 2))
    if speed(a0) <= 0.0:
        raise ValueError('该齿数产生根部欠切，无法形成有效理论轮槽')
    folded = speed(a1) < 0.0
    end = _bisect(speed, a0, a1) if folded else a1
    root_piece = [(root, a0, end)]

    convex = []
    for arc in (flank, tip):
        (_cx, cd), r, a, b = arc
        bfactor = lambda v: radius * math.sin(v) ** 2 - pld - cd - r * math.sin(v)
        if bfactor(b) <= 0.0:
            continue
        if bfactor(a) < 0.0:
            a = _bisect(bfactor, a, b)
        convex.append((arc, a, b))
    if not convex:
        raise ValueError('该齿数产生欠切，凸齿侧无有效包络')

    if not folded:
        # At high tooth counts the original tangency is already exposed.
        if convex[0][0] is not flank or abs(convex[0][1] - flank[2]) > 1e-10:
            raise ValueError('根部与齿侧的可见分支不相接')
        return root_piece + convex

    outer = radius - pld
    ca, cv, _ = convex[0]
    cangle, cradius = _polar(ca, cv, radius, pld)
    mouth = None
    if cradius >= outer:
        for arc, a, b in convex:
            if _polar(arc, b, radius, pld)[1] <= outer:
                value = _bisect(lambda v: _polar(arc, v, radius, pld)[1] - outer,
                                a, b)
                mouth = (arc, value)
                break
        if mouth is None:
            raise ValueError('理论齿槽未能与外圆相交')
        ma, mv = mouth
        if _polar(ma, mv, radius, pld)[0] >= _polar(root, a0, radius, pld)[0]:
            # On very small pulleys the convex sweep consumes the root fillet.
            return _trim_before(convex, ma, mv)

    low = max(0.0, _polar(root, end, radius, pld)[0])
    high = min(cangle, _polar(root, a0, radius, pld)[0])
    if high < low:
        raise ValueError('欠切分支无法修剪为连续的理论轮槽')

    def difference(angle):
        return (_at_angle(root_piece, angle, radius, pld)[2]
                - _at_angle(convex, angle, radius, pld)[2])

    if difference(low) * difference(high) > 0.0:
        raise ValueError('该齿数的理论包络存在欠切/悬垂分支，拒绝生成轮槽')
    crossing = _bisect(difference, low, high)
    _ra, rv, _rr = _at_angle(root_piece, crossing, radius, pld)
    ca, cv, _cr = _at_angle(convex, crossing, radius, pld)
    return [(root, a0, rv)] + _trim_before(convex, ca, cv)


def _second_derivative_bound(arc, a, b, radius, pld):
    """Conservative supremum of |Q''| on this circle-parameter interval.

    Q'=Rot(t)*A*(1,cot(a)), t'= -k/(R*sin(a)^2), and
    A=-r*sin(a)-k^2/(R*sin(a)^2)-k*r/(R*sin(a)).
    All retained intervals have monotone nonzero |sin(a)|. Triangle and mean
    value inequalities give this bound without relying on midpoint sag alone.
    Thus each chord's distance from Q is at most bound*(b-a)^2/8.
    """
    (_cx, cd), r = arc[:2]
    k = pld + cd
    smin = min(abs(math.sin(a)), abs(math.sin(b)))
    smax = max(abs(math.sin(a)), abs(math.sin(b)))
    cmax = max(abs(math.cos(a)), abs(math.cos(b)))
    aprime = (r * cmax + 2.0 * k * k * cmax / (radius * smin ** 3)
              + abs(k * r) * cmax / (radius * smin ** 2))
    smid = math.sin((a + b) / 2.0)
    amid = -r * smid - k * (k + r * smid) / (radius * smid ** 2)
    absolute = min(r * smax + k * k / (radius * smin ** 2)
                   + abs(k * r) / (radius * smin),
                   abs(amid) + aprime * abs(b - a) / 2.0)
    return (aprime / smin + absolute / smin ** 2
            + abs(k) * absolute / (radius * smin ** 3))


def _chord_parameters(arc, a, b, radius, pld, tolerance):
    parameters = [a]

    def subdivide(lo, hi, depth):
        bound = _second_derivative_bound(arc, lo, hi, radius, pld)
        if bound * (hi - lo) ** 2 / 8.0 <= tolerance:
            parameters.append(hi)
        else:
            if depth >= 30:
                raise ValueError('包络离散未能达到指定误差')
            mid = (lo + hi) / 2.0
            subdivide(lo, mid, depth + 1)
            subdivide(mid, hi, depth + 1)

    subdivide(a, b, 0)
    return parameters


def _chord_points(arc, a, b, radius, pld, tolerance):
    return [_envelope(arc, value, radius, pld)
            for value in _chord_parameters(arc, a, b, radius, pld, tolerance)]


def _fixed_count_points(pieces, radius, pld, count, with_parameters=False):
    """Distribute half-groove segments by length, retaining every branch join.

    Points remain on the analytic envelope. Report a conservative chord error
    from the same second-derivative bound used by adaptive sampling.
    """
    lengths = []
    for arc, a, b in pieces:
        probes = [_envelope(arc, a + (b - a) * i / 8.0, radius, pld)
                  for i in range(9)]
        lengths.append(sum(math.hypot(q[0] - p[0], q[1] - p[1])
                           for p, q in zip(probes, probes[1:])))
    remaining = (count - 1) // 2 - len(pieces)
    shares = [remaining * length / sum(lengths) for length in lengths]
    segments = [1 + int(share) for share in shares]
    extras = (count - 1) // 2 - sum(segments)
    order = sorted(range(len(pieces)), key=lambda i: shares[i] % 1, reverse=True)
    for i in order[:extras]:
        segments[i] += 1
    points, error, parameters = [], 0.0, []
    for (arc, a, b), n in zip(pieces, segments):
        step = (b - a) / n
        parameters.append([a + step * i for i in range(n + 1)])
        if not points:
            points.append(_envelope(arc, a, radius, pld))
        for i in range(n):
            lo, hi = a + step * i, a + step * (i + 1)
            points.append(_envelope(arc, hi, radius, pld))
            error = max(error, _second_derivative_bound(arc, lo, hi, radius, pld)
                        * step * step / 8.0)
    return (points, error, parameters) if with_parameters else (points, error)


def _envelope_derivative(arc, a, radius, pld):
    (cx, cd), r = arc[:2]
    s, c, k = math.sin(a), math.cos(a), pld + cd
    angle = (k * c / s - cx) / radius
    speed = -r * s - k * (k + r * s) / (radius * s * s)
    return G._rot((speed, speed * c / s), angle)


def prepare_smooth_profile(result):
    """C2 curves for each genuine analytic branch, with a conservative bound.

    For each span, |Q-S| <= |Q-L| + |S-L|. The first term is bounded by
    sup|Q''|*da^2/8. The second is bounded by 3/4 of the maximum difference
    between the Bezier and straight-chord interior controls. This does not rely
    on sampled error alone. Fixed-count mode retains the selected point count.
    """
    if not result.ok:
        raise ValueError('无效的 GT 求解结果')
    if result.smooth_curves is not None:
        return result.smooth_curves
    radius, pld = result.pitch_radius, result.od_drop / 2
    pieces, target = result.envelope_pieces, result.approximation_tolerance
    fixed = result.sampling_mode == 'point_count'
    if fixed:
        _, _, parameters = _fixed_count_points(
            pieces, radius, pld, result.samples_per_tooth, with_parameters=True)
    else:
        parameters = [_chord_parameters(arc, a, b, radius, pld, target * .4)
                      for arc, a, b in pieces]
    curves, max_error, sample_count = [], 0., 1
    for index, ((arc, a, b), values) in enumerate(zip(pieces, parameters)):
        for attempt in range(16):
            points = [_envelope(arc, value, radius, pld) for value in values]
            original = list(points)
            points[0] = curves[-1].control[-1] if curves else result.exit_right
            if index == len(pieces) - 1:
                points[-1] = (0., result.groove_lowest)
            numeric_margin = max(math.dist(p, q) for p, q in zip(points, original)) + 1e-12
            nodes = [(value - a) / (b - a) for value in values]
            start_d = G._scale(_envelope_derivative(arc, a, radius, pld), b - a)
            end_d = G._scale(_envelope_derivative(arc, b, radius, pld), b - a)
            curve = spline.interpolate(nodes, points, start_d, end_d)
            errors = []
            for lo, hi, bezier in zip(values, values[1:], curve.spans):
                p, c1, c2, q = bezier
                chord_c1 = tuple((2 * p[d] + q[d]) / 3 for d in (0, 1))
                chord_c2 = tuple((p[d] + 2 * q[d]) / 3 for d in (0, 1))
                errors.append(_second_derivative_bound(arc, lo, hi, radius, pld)
                              * (hi - lo) ** 2 / 8
                              + .75 * max(math.dist(c1, chord_c1), math.dist(c2, chord_c2))
                              + numeric_margin)
            invalid = {i for i, span in enumerate(curve.spans) if not spline.polar_monotone(span)}
            if fixed and invalid:
                raise ValueError('采样点太少，连续曲线发生局部折返；请增加每齿采样点数')
            if fixed or (max(errors) <= target and not invalid):
                break
            refined = [values[0]]
            for i, (lo, hi, error) in enumerate(zip(values, values[1:], errors)):
                if error > target or i in invalid:
                    refined.append((lo + hi) / 2)
                refined.append(hi)
            values = refined
        else:
            raise ValueError('连续曲线未能达到指定误差上限')
        curves.append(curve)
        max_error = max(max_error, *errors)
        sample_count += len(values) - 1
    result.smooth_curves = curves
    result.smooth_error_bound = max_error
    result.smooth_samples_per_tooth = 2 * sample_count - 1
    return curves


def solve_groove(model_id, teeth, tolerance=0.001, samples_per_tooth=None):
    """Solve nominal 2GT/3GT/5GT; tolerance is a chord error in mm.

    samples_per_tooth=None uses the tolerance; otherwise use 9..513 odd points
    per complete groove and report the resulting error bound, not tolerance.
    Software input range is 3..400 integral teeth. This is not a manufacturer's
    minimum-tooth recommendation. Invalid/undercut configurations fail closed.
    """
    result = GTResult(ok=False, model=model_id, source=SOURCE,
                      standard_note=STANDARD_NOTE,
                      approximation_tolerance=tolerance,
                      generation_method='nominal_rolling_conjugate_envelope',
                      profile_chain=[])
    try:
        if model_id not in SPECS:
            raise ValueError('仅支持原厂独立尺寸的 2GT、3GT、5GT')
        spec = get_spec(model_id)
        result.nominal_belt_spec = spec
        if isinstance(teeth, bool) or not math.isfinite(float(teeth)):
            raise ValueError('齿数必须为 3~400 的整数')
        count = int(teeth)
        if float(teeth) != count or not 3 <= count <= 400:
            raise ValueError('齿数必须为 3~400 的整数')
        if isinstance(tolerance, bool):
            raise ValueError('离散误差必须为 0.0000001~0.01 mm')
        tolerance = float(tolerance)
        if not math.isfinite(tolerance) or not 1e-7 <= tolerance <= 0.01:
            raise ValueError('离散误差必须为 0.0000001~0.01 mm')
        if samples_per_tooth is not None:
            if isinstance(samples_per_tooth, bool):
                raise ValueError('每齿采样点数必须为 9~513 的奇数（含槽底和两端）')
            points_value = float(samples_per_tooth)
            if not math.isfinite(points_value) or not points_value.is_integer():
                raise ValueError('每齿采样点数必须为 9~513 的奇数（含槽底和两端）')
            samples_per_tooth = int(points_value)
            if not 9 <= samples_per_tooth <= 513 or samples_per_tooth % 2 == 0:
                raise ValueError('每齿采样点数必须为 9~513 的奇数（含槽底和两端）')
        pitch, pld, h = spec['pitch'], spec['pld'], spec['h']
        radius = pitch * count / (2.0 * math.pi)
        outer, lowest = radius - pld, radius - pld - h
        if lowest <= 0.0:
            raise ValueError('该齿数的理论槽底穿过轮心')
        arcs = _belt_arcs(spec)
        pieces = _exposed_pieces(arcs, radius, pld)
        right = []
        if samples_per_tooth is not None:
            right, tolerance = _fixed_count_points(pieces, radius, pld, samples_per_tooth)
        else:
            for arc, a, b in pieces:
                points = _chord_points(arc, a, b, radius, pld, tolerance)
                if right and math.hypot(right[-1][0] - points[0][0],
                                        right[-1][1] - points[0][1]) > 1e-8:
                    raise ValueError('修剪后的包络分支不连续')
                right.extend(points if not right else points[1:])
        right[0] = G._scale(right[0], outer / G._len(right[0]))
        right[-1] = (0.0, lowest)
        angle = math.atan2(right[0][0], right[0][1])
        pitch_angle = 2.0 * math.pi / count
        land_angle = pitch_angle - 2.0 * angle
        if angle <= 0.0 or land_angle <= 1e-9:
            raise ValueError('该齿数的相邻理论齿槽重叠，无有效齿顶宽')
        # A decreasing polar graph is a direct topology check: mirrored and
        # periodically repeated halves cannot cross when the land is positive.
        polar = [math.atan2(x, y) for x, y in right]
        if any(a <= b for a, b in zip(polar, polar[1:])):
            raise ValueError('欠切导致理论轮槽极角不单调')
        local = right + [(-x, y) for x, y in reversed(right[:-1])]
        chain = []
        first = local[0]
        for index in range(count):
            rotation = index * pitch_angle
            pts = [G._rot(point, rotation) for point in local]
            for a, b in zip(pts, pts[1:]):
                chain.append(G.Line(a, b, 'GT理论滚动包络'))
            finish = (first if index == count - 1 else
                      G._rot(first, (index + 1) * pitch_angle))
            start_angle = math.atan2(pts[-1][1], pts[-1][0])
            end_angle = start_angle + land_angle
            mid_angle = start_angle + land_angle / 2.0
            chain.append(G.Arc((0.0, 0.0), outer, pts[-1], finish,
                               (outer * math.cos(mid_angle), outer * math.sin(mid_angle)),
                               start_angle, end_angle, True, '齿顶外圆弧'))
        result.ok = True
        result.message = STANDARD_NOTE
        result.pitch, result.teeth = pitch, count
        result.clearance, result.od_drop, result.r_tip = 0.0, 2.0 * pld, 0.0
        result.pitch_radius, result.outer_radius = radius, outer
        result.pitch_angle, result.groove_lowest = pitch_angle, lowest
        result.groove_depth, result.hb, result.h_pd = h, h, pld
        result.belt_half_width = (pitch - spec['b']) / 2.0
        result.belt_tip_lowest = lowest
        result.groove_half_width, result.tip_width = first[0], outer * land_angle
        result.exit_right, result.exit_left = first, (-first[0], first[1])
        result.tip_out_right, result.tip_out_left = result.exit_right, result.exit_left
        result.theoretical_sharp_right = result.exit_right
        result.theoretical_sharp_left = result.exit_left
        result.theoretical_slot_width = 2.0 * first[0]
        result.profile_chain, result.envelope_pieces = chain, pieces
        result.half_profile_points = right
        result.sampling_mode = 'point_count' if samples_per_tooth is not None else 'tolerance'
        result.samples_per_tooth = len(local)
        result.approximation_tolerance = tolerance
        result.belt = {'model': model_id, 'source': SOURCE, 'spec': dict(spec)}
        # A belt outline is separate from the generated pulley envelope.
        belt_right = []
        for arc in arcs:
            (cx, cd), r, a, b = arc
            for sample in range(25):
                if belt_right and sample == 0:
                    continue
                value = a + (b - a) * sample / 24.0
                belt_right.append((cx + r * math.cos(value),
                                   -cd - r * math.sin(value)))
        belt_right[-1] = (0.0, -h)
        result.belt_points = belt_right + [(-x, y) for x, y in reversed(belt_right[:-1])]
        result.has_flank, result.tip_fillet = True, 0.0
    except (ValueError, TypeError, OverflowError, KeyError) as error:
        result.message = str(error)
        result.profile_chain = []
    return result
