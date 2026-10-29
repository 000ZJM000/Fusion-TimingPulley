"""Sampling accuracy, exact compact encoding, and Fusion batch-write regressions."""
import bisect
import importlib
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import test_dryrun as harness
from test_gt_geometry import _distance_to_segment, _reference_contact


def _evaluate_spline(control, degree, knots, parameter):
    """de Boor evaluation independent of the polyline-to-Bezier construction."""
    span = min(len(control) - 1, bisect.bisect_right(knots, parameter) - 1)
    span = max(degree, span)
    work = [tuple(control[span - degree + j]) for j in range(degree + 1)]
    for level in range(1, degree + 1):
        for j in range(degree, level - 1, -1):
            index = span - degree + j
            weight = ((parameter - knots[index]) /
                      (knots[index + degree + 1 - level] - knots[index]))
            work[j] = tuple((1 - weight) * a + weight * b
                            for a, b in zip(work[j - 1], work[j]))
    return work[degree]


class SamplingPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.G = importlib.import_module('tpg.geometry')
        self.gt = importlib.import_module('tpg.gt')
        self.SK = importlib.import_module('tpg.sketch')
        self.UI = importlib.import_module('tpg.ui')
        self.design = harness.adsk.fusion.Design()
        self.component = self.design.rootComponent

    def test_fixed_count_preserves_shape_and_reports_error(self):
        for model in ('2GT', '3GT', '5GT'):
            for count in (9, 33, 65, 129):
                result = self.gt.solve_groove(model, 20, samples_per_tooth=count)
                self.assertTrue(result.ok, result.message)
                self.assertEqual(result.samples_per_tooth, count)
                self.assertEqual(len(result.half_profile_points), (count + 1) // 2)
                self.assertEqual(len(result.profile_chain), count * 20)
                self.assertLess(self.G.chain_gap_report(result.profile_chain), 1e-11)
                self.assertGreater(result.approximation_tolerance, 0)
                self.assertEqual(result.as_dict()['sampling_mode'], 'point_count')
            result = self.gt.solve_groove(model, 20, samples_per_tooth=33)
            points = result.half_profile_points
            for arc, a, b in result.envelope_pieces:
                for index in range(101):
                    point, _ = _reference_contact(arc, a + (b - a) * index / 100,
                                                  result.pitch_radius, self.gt.SPECS[model]['pld'])
                    error = min(_distance_to_segment(point, p, q)
                                for p, q in zip(points, points[1:]))
                    self.assertLessEqual(error, result.approximation_tolerance + 1e-10)
            finer = self.gt.solve_groove(model, 20, samples_per_tooth=129)
            self.assertLess(finer.approximation_tolerance, result.approximation_tolerance)

    def test_invalid_counts_do_not_silently_round(self):
        for count in (True, 8, 10, 33.5, 515, float('nan'), float('inf'), 'bad'):
            with self.subTest(count=count):
                self.assertFalse(self.gt.solve_groove('2GT', 20, samples_per_tooth=count).ok)

    def test_smooth_spline_reproduces_cubic_polynomial(self):
        spline = importlib.import_module('tpg.spline')
        nodes = [0., .13, .4, .71, 1.]
        curve = spline.interpolate(nodes, [(t**3, 2*t**3-3*t*t+t) for t in nodes],
                                   (0., 1.), (3., 1.))
        self.assertEqual(len(curve.knots), len(curve.control) + 4)
        self.assertEqual(len(set(curve.knots[4:-4])), len(curve.knots[4:-4]))
        for index in range(101):
            value = index / 100
            actual = _evaluate_spline(curve.control, 3, curve.knots, value)
            self.assertLess(math.dist(actual, (value**3, 2*value**3-3*value*value+value)), 1e-12)

    def test_native_entity_count_reduces_without_relaxing_accuracy(self):
        result = self.gt.solve_groove('2GT', 20)
        compact = self.SK.build(self.component, result, {})
        expanded = self.SK.build(self.component, result, {'compact_gt': False})
        self.assertEqual(expanded['arc_count'], 1540)
        self.assertEqual(compact['arc_count'], 140)
        self.assertTrue(compact['compact_used'])
        self.assertEqual(len(compact['sketch']._splines), 120)
        self.assertEqual(len(compact['sketch']._arcs), 20)
        self.assertEqual(len(compact['sketch']._lines), 0)
        self.assertEqual(result.approximation_tolerance, .001)
        self.assertGreaterEqual(compact['timings']['total_seconds'], 0)
        for spline in compact['sketch']._splines[:1]:
            control = [(p.x, p.y) for p in spline.geometry.controlPoints]
            arc, a, b = result.envelope_pieces[0]
            for value in (.07, .23, .57, .93):
                actual = _evaluate_spline(control, 3, spline.geometry.knots, value)
                expected, _ = _reference_contact(arc, a + (b-a)*value,
                                                  result.pitch_radius, result.od_drop/2)
                self.assertLess(math.dist(actual, tuple(x*.1 for x in expected)),
                                result.smooth_error_bound * .1)

    def test_failed_smooth_write_rolls_back_without_faceted_retry(self):
        result = self.gt.solve_groove('2GT', 20)
        sketch = self.component.sketches.add(self.component.xYConstructionPlane)
        collection = sketch.sketchCurves.sketchFixedSplines
        original, calls = collection.addByNurbsCurve, []
        def add(curve):
            calls.append(curve)
            if len(calls) == 3:
                raise RuntimeError('injected spline failure')
            return original(curve)
        with patch.object(collection, 'addByNurbsCurve', side_effect=add):
            with self.assertRaisesRegex(RuntimeError, '连续曲线写入失败'):
                self.SK.build(self.component, result, {'target_plane': sketch})
        self.assertEqual(sketch._splines, [])
        self.assertEqual(sketch._arcs, [])
        self.assertEqual(sketch._lines, [])

    def _existing_at_timeline(self):
        sketch = self.component.sketches.add(self.component.xYConstructionPlane)
        timeline = SimpleNamespace(markerPosition=12)
        def roll(before):
            self.assertFalse(before)
            timeline.markerPosition = 4
            return True
        feature = SimpleNamespace(index=3, rollTo=roll)
        self.design.timeline = timeline
        sketch.timelineObject = feature
        return sketch, timeline

    def test_existing_sketch_batches_only_at_its_timeline_position(self):
        sketch, timeline = self._existing_at_timeline()
        result = self.gt.solve_groove('2GT', 20)
        collection = sketch.sketchCurves.sketchFixedSplines
        original, states = collection.addByNurbsCurve, []
        def add(curve):
            states.append((sketch.isComputeDeferred, timeline.markerPosition))
            return original(curve)
        with patch.object(collection, 'addByNurbsCurve', side_effect=add):
            self.SK.build(self.component, result, {'target_plane': sketch})
        self.assertTrue(states)
        self.assertTrue(all(state == (True, 4) for state in states))
        self.assertFalse(sketch.isComputeDeferred)
        self.assertEqual(timeline.markerPosition, 12)

    def test_timeline_and_compute_state_restore_after_failure(self):
        sketch, timeline = self._existing_at_timeline()
        result = self.gt.solve_groove('2GT', 20)
        with patch.object(sketch.sketchCurves.sketchCircles, 'addByCenterRadius',
                          side_effect=RuntimeError('injected construction failure')):
            with self.assertRaisesRegex(RuntimeError, 'construction failure'):
                self.SK.build(self.component, result, {'target_plane': sketch})
        self.assertFalse(sketch.isComputeDeferred)
        self.assertEqual(timeline.markerPosition, 12)
        self.assertEqual(sketch._splines, [])
        self.assertEqual(sketch._arcs, [])

    def test_ui_sampling_controls_invalidate_geometry_cache(self):
        dialog = self.UI.Dialog(self.design)
        dialog.create(harness._FakeInputs())
        el = dialog.el
        for item in el[self.UI.ID_PROFILE].listItems._l:
            item.isSelected = item.name.startswith('GT')
        dialog.update()
        first = dialog.solve()[0]
        el[self.UI.ID_GT_TOLERANCE].value = .0004  # internal cm -> .004 mm
        dialog.update()
        coarser = dialog.solve()[0]
        self.assertIsNot(first, coarser)
        self.assertEqual(coarser.approximation_tolerance, .004)
        self.assertLess(coarser.samples_per_tooth, first.samples_per_tooth)
        mode = el[self.UI.ID_GT_SAMPLING].listItems
        mode.item(0).isSelected, mode.item(1).isSelected = False, True
        dialog.update()
        self.assertTrue(el[self.UI.ID_GT_SAMPLES].isEnabled)
        self.assertFalse(el[self.UI.ID_GT_TOLERANCE].isEnabled)
        self.assertEqual(dialog.solve()[0].samples_per_tooth, 33)
        el[self.UI.ID_GT_SAMPLES].value = 65
        dialog.update()
        self.assertEqual(dialog.solve()[0].samples_per_tooth, 65)
        el[self.UI.ID_COMPACT_GT].value = False
        dialog.update()
        self.assertIn(str(65 * 20), el[self.UI.ID_STATS].text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
