# -*- coding: utf-8 -*-
"""Independent checks of the nominal GT rolling envelope (no Fusion needed)."""

import bisect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))

from tpg import geometry as G
from tpg import gt


def _distance_to_segment(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    ratio = max(0.0, min(1.0, ratio))
    return math.hypot(point[0] - start[0] - ratio * dx,
                      point[1] - start[1] - ratio * dy)


def _rolling_point(arc, parameter, angle, radius, pld):
    """Direct rigid motion, independent of gt._envelope's simplified formula."""
    (cx, cd), r = arc[:2]
    x = cx + r * math.cos(parameter)
    depth = cd + r * math.sin(parameter)
    v = (x + radius * angle, radius - pld - depth)
    c, s = math.cos(angle), math.sin(angle)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


def _reference_contact(arc, parameter, radius, pld):
    """Solve the unsimplified contact determinant from x,d,x',d'."""
    (cx, cd), r = arc[:2]
    x = cx + r * math.cos(parameter)
    d = cd + r * math.sin(parameter)
    dx, dd = -r * math.sin(parameter), r * math.cos(parameter)
    angle = (-dd * (pld + d) / dx - x) / radius
    return _rolling_point(arc, parameter, angle, radius, pld), angle


def _right_polygon(result):
    """Extract the first half groove without using the solver's belt_points."""
    points = [result.profile_chain[0].start]
    for entity in result.profile_chain:
        if isinstance(entity, G.Arc):
            break
        points.append(entity.end)
        if abs(entity.end[0]) < 1e-13:
            break
    return list(reversed(points))  # increasing angle from the groove center


def _radial_boundary(points, outer, angle):
    angles = [math.atan2(x, y) for x, y in points]
    index = bisect.bisect_left(angles, angle)
    if index == 0:
        return math.hypot(*points[0])
    if index >= len(points):
        return outer
    start, end = points[index - 1], points[index]
    direction = (math.sin(angle), math.cos(angle))
    dx, dy = end[0] - start[0], end[1] - start[1]
    return ((start[0] * end[1] - start[1] * end[0]) /
            (direction[0] * dy - direction[1] * dx))


class GTGeometryTests(unittest.TestCase):
    def test_original_independent_dimensions_and_outer_diameter(self):
        expected = {
            '2GT': (2.0, .254, .75, .40, .15, 1.0, .555),
            '3GT': (3.0, .381, 1.14, .61, .25, 1.52, .85),
            '5GT': (5.0, .5715, 1.93, 1.03, .51, 2.54, 1.37),
        }
        names = ('pitch', 'pld', 'h', 'b', 'root_radius', 'flank_radius', 'tip_radius')
        for model, dimensions in expected.items():
            self.assertEqual(tuple(gt.get_spec(model)[name] for name in names), dimensions)
            result = gt.solve_groove(model, 20)
            self.assertTrue(result.ok, result.message)
            self.assertAlmostEqual(result.outer_diameter,
                                   dimensions[0] * 20 / math.pi - 2 * dimensions[1], places=12)
            self.assertAlmostEqual(result.groove_depth, dimensions[2], places=12)
            self.assertAlmostEqual(result.groove_lowest,
                                   result.outer_radius - dimensions[2], places=12)
            self.assertEqual(result.belt_tip_lowest, result.groove_lowest)
        self.assertAlmostEqual(gt.solve_groove('2GT', 20).outer_diameter,
                               12.224395447351628, places=12)
        copy = gt.get_spec('2GT')
        copy['h'] = 99
        self.assertEqual(gt.SPECS['2GT']['h'], .75)

    def test_source_circles_are_tangent_and_land_is_between_teeth(self):
        for model in gt.SPECS:
            spec = gt.get_spec(model)
            root, flank, tip = gt._belt_arcs(spec)
            self.assertAlmostEqual(root[0][0], (spec['pitch'] - spec['b']) / 2.0)
            self.assertLess(flank[0][0], 0.0)
            self.assertLess(flank[0][1], 0.0)
            for before, after in ((root, flank), (flank, tip)):
                point1 = (before[0][0] + before[1] * math.cos(before[3]),
                          before[0][1] + before[1] * math.sin(before[3]))
                point2 = (after[0][0] + after[1] * math.cos(after[2]),
                          after[0][1] + after[1] * math.sin(after[2]))
                self.assertLess(math.hypot(point1[0] - point2[0], point1[1] - point2[1]), 1e-12)
                tangent1 = (-math.sin(before[3]) * (before[3] - before[2]),
                            math.cos(before[3]) * (before[3] - before[2]))
                tangent2 = (-math.sin(after[2]) * (after[3] - after[2]),
                            math.cos(after[2]) * (after[3] - after[2]))
                self.assertAlmostEqual(tangent1[0] * tangent2[1] - tangent1[1] * tangent2[0], 0.0)
                self.assertGreater(tangent1[0] * tangent2[0] + tangent1[1] * tangent2[1], 0.0)

    def test_contact_equation_and_velocity_tangency(self):
        for model, count in (('2GT', 12), ('3GT', 20), ('5GT', 40), ('5GT', 100)):
            result = gt.solve_groove(model, count)
            self.assertTrue(result.ok, result.message)
            pld = gt.SPECS[model]['pld']
            for arc, a, b in result.envelope_pieces:
                for index in range(1, 12):
                    parameter = a + (b - a) * index / 12.0
                    expected, angle = _reference_contact(arc, parameter, result.pitch_radius, pld)
                    actual = gt._envelope(arc, parameter, result.pitch_radius, pld)
                    self.assertLess(math.hypot(expected[0] - actual[0], expected[1] - actual[1]), 1e-11)
                    # Finite differences of the original two-variable motion:
                    # boundary velocity and rolling velocity must be parallel.
                    delta = 1e-6
                    qa = _rolling_point(arc, parameter - delta, angle, result.pitch_radius, pld)
                    qb = _rolling_point(arc, parameter + delta, angle, result.pitch_radius, pld)
                    ta = _rolling_point(arc, parameter, angle - delta, result.pitch_radius, pld)
                    tb = _rolling_point(arc, parameter, angle + delta, result.pitch_radius, pld)
                    da = ((qb[0] - qa[0]) / (2 * delta), (qb[1] - qa[1]) / (2 * delta))
                    dt = ((tb[0] - ta[0]) / (2 * delta), (tb[1] - ta[1]) / (2 * delta))
                    cross = da[0] * dt[1] - da[1] * dt[0]
                    self.assertLess(abs(cross), 2e-7)

    def test_chords_respect_reported_tolerance(self):
        # Sample every subinterval of an independent fine reference at parameters
        # unrelated to the adaptive subdivision's midpoint acceptance checks.
        for model, count in (('2GT', 12), ('3GT', 20), ('5GT', 20), ('5GT', 100)):
            result = gt.solve_groove(model, count, tolerance=.001)
            pld = gt.SPECS[model]['pld']
            for arc, a, b in result.envelope_pieces:
                points = gt._chord_points(arc, a, b, result.pitch_radius, pld, .001)
                for index in range(1001):
                    parameter = a + (b - a) * index / 1000.0
                    expected, _ = _reference_contact(arc, parameter, result.pitch_radius, pld)
                    error = min(_distance_to_segment(expected, p, q) for p, q in zip(points, points[1:]))
                    self.assertLessEqual(error, result.approximation_tolerance + 1e-11)
            finer = gt.solve_groove(model, count, tolerance=.00025)
            self.assertTrue(finer.ok, finer.message)
            self.assertGreater(len(finer.profile_chain), len(result.profile_chain))

    def test_swept_tooth_does_not_penetrate_generated_material(self):
        # This checks arbitrary belt positions, not the envelope equation: points
        # swept by the belt must stay outside the retained pulley material.
        for model, count in (('2GT', 12), ('2GT', 40), ('3GT', 16),
                             ('3GT', 40), ('5GT', 20), ('5GT', 40)):
            result = gt.solve_groove(model, count)
            self.assertTrue(result.ok, result.message)
            spec = gt.get_spec(model)
            points = _right_polygon(result)
            for arc in gt._belt_arcs(spec):
                for parameter_index in range(41):
                    parameter = arc[2] + (arc[3] - arc[2]) * parameter_index / 40.0
                    for roll_index in range(81):
                        roll = (roll_index / 40.0 - 1.0) * result.pitch_angle
                        x, y = _rolling_point(arc, parameter, roll, result.pitch_radius, spec['pld'])
                        polar = abs(math.atan2(x, y))
                        radial = math.hypot(x, y)
                        if polar > result.pitch_angle / 2.0 or radial > result.outer_radius:
                            continue
                        boundary = _radial_boundary(points, result.outer_radius, polar)
                        if radial < boundary:
                            # Chord tolerance is Euclidean, not radial. Near a
                            # radial tangent a small normal error can have a
                            # much greater radial intersection difference.
                            reflected = (abs(x), y)
                            error = min(_distance_to_segment(reflected, p, q)
                                        for p, q in zip(points, points[1:]))
                            self.assertLessEqual(error, result.approximation_tolerance + 1e-10,
                                                 (model, count, roll, parameter))

    def test_closure_symmetry_and_nonintersection(self):
        for model in gt.SPECS:
            for count in (12, 16, 20, 40, 100, 400):
                result = gt.solve_groove(model, count)
                if not result.ok:
                    self.assertIn((model, count), (('3GT', 12), ('5GT', 12), ('5GT', 16)))
                    self.assertIn('欠切', result.message)
                    continue
                chain = G.closed_chain(result)
                self.assertEqual(len(G.tip_arcs(result)), count)
                self.assertEqual(len(chain) % count, 0)
                for current, following in zip(chain, chain[1:] + chain[:1]):
                    self.assertLess(math.hypot(current.end[0] - following.start[0],
                                               current.end[1] - following.start[1]), 2e-11)
                # Strict angular ordering of a positive-radius full ring proves
                # no edge crossings, independently of pairwise tolerance logic.
                advance = 0.0
                for entity in chain:
                    start = math.atan2(entity.start[1], entity.start[0])
                    end = math.atan2(entity.end[1], entity.end[0])
                    step = (end - start) % (2 * math.pi)
                    self.assertGreater(step, 0.0)
                    self.assertLess(step, math.pi)
                    advance += step
                    for point in (entity.start, entity.end):
                        self.assertTrue(all(math.isfinite(value) for value in point))
                self.assertAlmostEqual(advance, 2 * math.pi, places=9)
                per_tooth = len(chain) // count
                groove = chain[:per_tooth - 1]
                vertices = [groove[0].start] + [entity.end for entity in groove]
                for a, b in zip(vertices, reversed(vertices)):
                    self.assertAlmostEqual(a[0], -b[0], places=11)
                    self.assertAlmostEqual(a[1], b[1], places=11)
                self.assertGreater(result.tip_width, 0.0)

    def test_invalid_inputs_and_theory_status(self):
        for model, count in [('8GT', 20), ('GT2', 20), (None, 20),
                             ('2GT', float('nan')), ('2GT', float('inf')),
                             ('2GT', -1), ('2GT', 0), ('2GT', 2), ('2GT', 401),
                             ('2GT', 20.5), ('2GT', True), ('2GT', None)]:
            result = gt.solve_groove(model, count)
            self.assertFalse(result.ok, (model, count))
            self.assertEqual(result.profile_chain, [])
            self.assertFalse(result.as_dict()['ok'])
        for tolerance in (0, -1, float('nan'), float('inf'), 1, None, True):
            self.assertFalse(gt.solve_groove('2GT', 20, tolerance=tolerance).ok)
        for model, count in (('2GT', 3), ('3GT', 12), ('3GT', 13), ('5GT', 16), ('5GT', 17)):
            self.assertFalse(gt.solve_groove(model, count).ok)
        for model, count in (('2GT', 12), ('3GT', 14), ('5GT', 18)):
            result = gt.solve_groove(model, count)
            self.assertTrue(result.ok, result.message)
            metadata = result.as_dict()
            self.assertFalse(metadata['factory_groove_certified'])
            self.assertEqual(metadata['machining_clearance'], 0.0)
            self.assertEqual(metadata['approximation_tolerance'], .001)
            self.assertEqual(metadata['source'], gt.SOURCE)
            self.assertEqual(metadata['patent'], gt.PATENT)
            self.assertIn('理论', metadata['standard_note'])
            self.assertEqual(metadata['generation_method'], 'nominal_rolling_conjugate_envelope')


if __name__ == '__main__':
    unittest.main(verbosity=2)
