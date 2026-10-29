# -*- coding: utf-8 -*-
"""Regression tests for preserving user geometry when generation fails.

Run with: python -B tests/test_regressions.py
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'lib'))

import fusion_stub
fusion_stub.install()

import adsk.core
import adsk.fusion
import TimingPulleyGenerator as TPG

G = TPG.G
SK = TPG.SK


class SketchRegressions(unittest.TestCase):
    def setUp(self):
        self.design = adsk.fusion.Design()
        self.component = self.design.rootComponent
        TPG._app.activeProduct = self.design
        self.result = G.solve_groove(5.0, 20)

    def user_sketch(self, name='user'):
        sketch = self.component.sketches.add(self.component.xYConstructionPlane)
        sketch.name = name
        p = adsk.core.Point3D.create
        line = sketch.sketchCurves.sketchLines.addByTwoPoints(
            p(50, 50, 0), p(51, 50, 0))
        circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(
            p(60, 60, 0), 1)
        return sketch, line, circle

    def failing_arc(self):
        original = SK._add_arc
        calls = [0]

        def add(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError('injected arc failure')
            return original(*args, **kwargs)
        return add

    def test_existing_geometry_remains_editable(self):
        sketch, line, circle = self.user_sketch()
        out = SK.build(self.component, self.result, {'target_plane': sketch})
        self.assertTrue(out['ok'])
        self.assertFalse(line.isFixed)
        self.assertFalse(circle.isFixed)
        self.assertTrue(all(c.isFixed for c in sketch._arcs))
        self.assertTrue(all(c.isFixed for c in sketch._lines if c is not line))
        self.assertTrue(all(c.isFixed for c in sketch._circles if c is not circle))

    def test_fallback_removes_partial_exact_chain(self):
        sketch, line, circle = self.user_sketch()
        with patch.object(SK, '_add_arc', side_effect=self.failing_arc()):
            out = SK.build(self.component, self.result,
                           {'target_plane': sketch, 'sampled_fallback': True})
        self.assertTrue(out['ok'])
        self.assertEqual(sketch._arcs, [])
        expected = len(G.sample_chain(G.closed_chain(self.result)))
        self.assertEqual(len(sketch._lines), expected + 1)
        self.assertIs(sketch._lines[0], line)
        self.assertFalse(line.isFixed)
        self.assertFalse(circle.isFixed)
        # Fallback is closed using Point3D values, as accepted by both APIs.
        first = sketch._lines[1].startSketchPoint.geometry
        last = sketch._lines[-1].endSketchPoint.geometry
        self.assertAlmostEqual(first.x, last.x)
        self.assertAlmostEqual(first.y, last.y)

    def test_failure_rolls_back_only_new_entities(self):
        sketch, line, circle = self.user_sketch()
        sketch.isComputeDeferred = True
        with patch.object(SK, '_add_arc', side_effect=self.failing_arc()):
            with self.assertRaisesRegex(RuntimeError, 'injected arc failure'):
                SK.build(self.component, self.result,
                         {'target_plane': sketch, 'sampled_fallback': False})
        self.assertEqual(sketch._lines, [line])
        self.assertEqual(sketch._circles, [circle])
        self.assertEqual(sketch._arcs, [])
        self.assertTrue(sketch.isComputeDeferred)
        self.assertFalse(line.isFixed)
        self.assertFalse(circle.isFixed)

    def test_construction_failure_removes_all_new_entities(self):
        sketch, line, circle = self.user_sketch()
        circles = sketch.sketchCurves.sketchCircles
        original = circles.addByCenterRadius
        calls = [0]

        def add(*args):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError('injected circle failure')
            return original(*args)

        with patch.object(circles, 'addByCenterRadius', side_effect=add):
            with self.assertRaisesRegex(RuntimeError, 'injected circle failure'):
                SK.build(self.component, self.result, {'target_plane': sketch})
        self.assertEqual(sketch._lines, [line])
        self.assertEqual(sketch._circles, [circle])
        self.assertEqual(sketch._arcs, [])
        self.assertFalse(sketch.isComputeDeferred)

    def test_failed_replacement_keeps_original(self):
        original, line, _ = self.user_sketch('replace-me')
        with patch.object(SK, '_add_arc', side_effect=self.failing_arc()):
            with self.assertRaisesRegex(RuntimeError, 'injected arc failure'):
                SK.build(self.component, self.result, {
                    'sketch_name': 'replace-me', 'replace': True,
                    'sampled_fallback': False})
        self.assertTrue(original.isValid)
        self.assertEqual(self.component.sketches.count, 1)
        self.assertIs(self.component.sketches.item(0), original)
        self.assertFalse(line.isFixed)

    def test_invalid_result_is_rejected_before_replacement(self):
        original, _, _ = self.user_sketch('replace-me')
        with self.assertRaises(ValueError):
            SK.build(self.component, SimpleNamespace(ok=False), {
                'sketch_name': 'replace-me', 'replace': True})
        self.assertTrue(original.isValid)
        self.assertEqual(self.component.sketches.count, 1)

    def test_zero_profiles_keeps_original(self):
        original, _, _ = self.user_sketch('replace-me')
        with patch.object(type(original.profiles), 'count', property(lambda _: 0)):
            with self.assertRaisesRegex(ValueError, 'Profile'):
                SK.build(self.component, self.result, {
                    'sketch_name': 'replace-me', 'replace': True})
        self.assertTrue(original.isValid)
        self.assertEqual(self.component.sketches.count, 1)

    def test_circle_world_geometry_is_resolved_to_center(self):
        sketch, _, circle = self.user_sketch()
        self.assertEqual(SK.resolve_center_point(sketch, circle), (600.0, 600.0))
        selected = SimpleNamespace(worldGeometry=SimpleNamespace(
            center=adsk.core.Point3D.create(1.5, 2.5, 0)))
        self.assertEqual(SK.resolve_center_point(sketch, selected), (15.0, 25.0))

    def test_invalid_center_does_not_leave_new_sketch(self):
        with self.assertRaises(ValueError):
            SK.build(self.component, self.result, {'center_point': object()})
        self.assertEqual(self.component.sketches.count, 0)

    def test_profile_selection_uses_parent_sketch(self):
        sketch, _, _ = self.user_sketch()
        out = SK.build(self.component, self.result, {
            'target_plane': SimpleNamespace(parentSketch=sketch)})
        self.assertIs(out['sketch'], sketch)
        self.assertEqual(self.component.sketches.count, 1)

    def test_label_height_matches_current_fusion_signature(self):
        sketch, _, _ = self.user_sketch()
        made = SK.draw_labels(sketch, [('size', 1.0, 2.0, 3.0)])
        self.assertEqual(made, 1)
        self.assertIsInstance(sketch._texts[0].height, adsk.core.ValueInput)
        self.assertAlmostEqual(sketch._texts[0].height.value, 0.3)

    def test_labels_support_older_fusion_signature(self):
        sketch, _, _ = self.user_sketch()
        inputs = []

        def create(text, height):
            inputs.append((text, height))
            return SimpleNamespace(setAsMultiLine=lambda *args: True)

        sketch.sketchTexts = SimpleNamespace(createInput2=create, add=lambda _: None)
        self.assertEqual(SK.draw_labels(sketch, [('size', 1.0, 2.0, 3.0)]), 1)
        self.assertEqual(inputs[0][0], 'size')
        self.assertAlmostEqual(inputs[0][1], 0.3)

    def test_execute_places_labels_at_selected_center(self):
        sketch, _, _ = self.user_sketch()
        opts = dict(
            sketch_name='labels', replace=False, target_plane=sketch,
            center_point=adsk.fusion.SketchPoint(
                adsk.core.Point3D.create(1.5, 2.5, 0)),
            draw_pitch_circle=True, draw_root_circle=True,
            draw_outer_circle=False, labels=True, sampled_fallback=False)
        dialog = SimpleNamespace(read=lambda: opts,
                                 solve=lambda _: (self.result, ''))
        with patch.object(TPG, '_dialog', dialog):
            with patch.object(SK, 'draw_labels') as draw:
                TPG._on_execute(SimpleNamespace())
        draw.assert_called_once()
        self.assertEqual(draw.call_args.kwargs, {'cx': 15.0, 'cy': 25.0})


if __name__ == '__main__':
    unittest.main()
