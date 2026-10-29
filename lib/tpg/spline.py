"""Clamped C2 cubic interpolation, using only Python's standard library.

Solve the usual tridiagonal second-derivative equations. Convert the resulting
piecewise polynomial to a clamped cubic B-spline with SINGLE interior knots.
Bezier spans are retained for conservative error bounds and independent tests.
"""


class Curve:
    def __init__(self, control, knots, spans):
        self.control = control
        self.knots = knots
        self.spans = spans


def interpolate(parameters, points, start_derivative, end_derivative):
    count = len(points)
    if count < 2 or count != len(parameters):
        raise ValueError('连续曲线至少需要两个对应参数点')
    steps = [b - a for a, b in zip(parameters, parameters[1:])]
    if any(h <= 0 for h in steps):
        raise ValueError('连续曲线的参数必须严格递增')
    lower, diagonal, upper = [0.] * count, [0.] * count, [0.] * count
    rhs = [[0., 0.] for _ in points]
    slopes = [tuple((q[d] - p[d]) / h for d in (0, 1))
              for p, q, h in zip(points, points[1:], steps)]
    diagonal[0], upper[0] = 2 * steps[0], steps[0]
    diagonal[-1], lower[-1] = 2 * steps[-1], steps[-1]
    rhs[0] = [6 * (slopes[0][d] - start_derivative[d]) for d in (0, 1)]
    rhs[-1] = [6 * (end_derivative[d] - slopes[-1][d]) for d in (0, 1)]
    for i in range(1, count - 1):
        lower[i], upper[i] = steps[i - 1], steps[i]
        diagonal[i] = 2 * (steps[i - 1] + steps[i])
        rhs[i] = [6 * (slopes[i][d] - slopes[i - 1][d]) for d in (0, 1)]
    for i in range(1, count):
        factor = lower[i] / diagonal[i - 1]
        diagonal[i] -= factor * upper[i - 1]
        rhs[i] = [rhs[i][d] - factor * rhs[i - 1][d] for d in (0, 1)]
    second = [(0., 0.) for _ in points]
    second[-1] = tuple(v / diagonal[-1] for v in rhs[-1])
    for i in range(count - 2, -1, -1):
        second[i] = tuple((rhs[i][d] - upper[i] * second[i + 1][d]) / diagonal[i]
                          for d in (0, 1))
    spans = []
    for i, h in enumerate(steps):
        slope_a = tuple(slopes[i][d] - h * (2 * second[i][d] + second[i + 1][d]) / 6
                        for d in (0, 1))
        slope_b = tuple(slopes[i][d] + h * (second[i][d] + 2 * second[i + 1][d]) / 6
                        for d in (0, 1))
        spans.append((points[i], tuple(points[i][d] + h * slope_a[d] / 3 for d in (0, 1)),
                      tuple(points[i + 1][d] - h * slope_b[d] / 3 for d in (0, 1)),
                      points[i + 1]))
    knots = [parameters[0]] * 4 + parameters[1:-1] + [parameters[-1]] * 4
    # S'' is a linear B-spline whose control values are the nodal second
    # derivatives. Integrate twice using the standard B-spline derivative rule.
    derivatives = [tuple(start_derivative)]
    for i, value in enumerate(second):
        scale = (knots[i + 4] - knots[i + 2]) / 2
        derivatives.append(tuple(derivatives[-1][d] + value[d] * scale for d in (0, 1)))
    control = [points[0]]
    for i, value in enumerate(derivatives):
        scale = (knots[i + 4] - knots[i + 1]) / 3
        control.append(tuple(control[-1][d] + value[d] * scale for d in (0, 1)))
    control[-1] = points[-1]
    return Curve(control, knots, spans)


def polar_monotone(bezier, depth=0):
    """Certify cross(B,B') >= 0 via its degree-5 Bernstein coefficients.

    Used for the right groove, which has positive y. Together these conditions
    keep polar angle monotone and prevent interpolation loops/neighbor overlap.
    Subdivide only when the convex-hull sign bound is inconclusive.
    """
    if min(point[1] for point in bezier) <= 0:
        return False
    derivative = [tuple(3 * (q[d] - p[d]) for d in (0, 1))
                  for p, q in zip(bezier, bezier[1:])]
    choose3, choose2, choose5 = (1, 3, 3, 1), (1, 2, 1), (1, 5, 10, 10, 5, 1)
    coefficients = [0.] * 6
    for i, p in enumerate(bezier):
        for j, q in enumerate(derivative):
            coefficients[i + j] += ((p[0] * q[1] - p[1] * q[0])
                                      * choose3[i] * choose2[j] / choose5[i + j])
    roundoff = max(abs(c) for c in coefficients) * 1e-12
    if min(coefficients) >= -roundoff:
        return max(coefficients) > 0
    if depth >= 14 or max(coefficients) < -roundoff:
        return False
    levels = [list(bezier)]
    for _ in range(3):
        levels.append([tuple((p[d] + q[d]) / 2 for d in (0, 1))
                       for p, q in zip(levels[-1], levels[-1][1:])])
    left = tuple(level[0] for level in levels)
    right = tuple(level[-1] for level in reversed(levels))
    return polar_monotone(left, depth + 1) and polar_monotone(right, depth + 1)
