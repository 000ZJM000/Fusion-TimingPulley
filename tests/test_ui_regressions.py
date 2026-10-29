"""UI regressions using the existing Fusion input doubles."""
import csv
import math
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / 'lib'))
sys.path.insert(0, str(_ROOT / 'tests'))
import test_dryrun as harness


class UIRegressions(unittest.TestCase):
    def setUp(self):
        # Use the current modules after the entrypoint's reload boundary.
        import importlib
        self.UI = importlib.import_module('tpg.ui')
        self.G = importlib.import_module('tpg.geometry')
        self.dialog = self.UI.Dialog(harness.design)
        self.dialog.create(harness._FakeInputs())
        self.inputs = self.dialog.el

    def select_family(self, prefix):
        for item in self.inputs[self.UI.ID_PROFILE].listItems._l:
            item.isSelected = item.name.startswith(prefix)
        self.dialog.update()

    def test_family_change_refills_models_and_returns(self):
        self.select_family('RPP')
        self.assertFalse(self.inputs[self.UI.ID_MODEL].isEnabled)
        self.select_family('HTD')
        self.assertEqual(self.inputs[self.UI.ID_MODEL].listItems.item(0).name, '2M')
        self.assertIsNotNone(self.dialog.solve()[0])

    def test_angle_database_units_are_always_radians(self):
        self.inputs[self.UI.ID_THETA].value = math.radians(190)
        self.assertAlmostEqual(self.dialog.read()['theta_deg'], 190.0)

    def test_invalid_expression_is_rejected(self):
        self.inputs[self.UI.ID_RBT].isValidExpression = False
        self.assertFalse(self.dialog.validate()[0])

    def test_small_user_adjustment_is_preserved(self):
        for item in self.inputs[self.UI.ID_MODEL].listItems._l:
            item.isSelected = item.name == '5M'
        self.dialog.update()
        self.inputs[self.UI.ID_ODDROP].value += 0.0002
        params = self.dialog.read()
        result, error = self.dialog.solve(params)
        self.assertIsNotNone(result, error)
        self.assertAlmostEqual(result.od_drop, params['od_drop_ratio'] * params['pitch'])

    def test_zero_fillet_export_is_zero(self):
        result = self.G.solve_groove(5, 20, r_tip=0)
        rows = {key: value for key, value, unit in self.UI.param_rows(result, {})}
        self.assertEqual(float(rows['齿顶倒角半径']), 0.0)

    def test_csv_round_trips_commas_quotes_and_newlines(self):
        rows = [('name,with,commas', 'value "quoted"\nnext line', 'mm')]
        with tempfile.TemporaryDirectory(dir=_ROOT / 'tests') as tmp:
            path = Path(tmp) / 'roundtrip.csv'
            self.UI.write_csv(str(path), rows)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                parsed = list(csv.reader(stream))
        self.assertEqual(parsed[1], list(rows[0]))

    def test_gt_family_selects_three_independent_models(self):
        self.select_family('GT')
        names = [item.name for item in self.inputs[self.UI.ID_MODEL].listItems._l]
        self.assertEqual(names, ['2GT', '3GT', '5GT'])
        self.assertFalse(self.inputs[self.UI.ID_PITCH_AUTO].isEnabled)
        self.assertFalse(self.inputs[self.UI.ID_PITCH].isEnabled)
        self.assertFalse(self.inputs[self.UI.ID_RBT].isEnabled)
        self.assertFalse(self.inputs[self.UI.ID_CLEAR].isEnabled)
        for model, pitch in (('2GT', 2), ('3GT', 3), ('5GT', 5)):
            with self.subTest(model=model):
                for item in self.inputs[self.UI.ID_MODEL].listItems._l:
                    item.isSelected = item.name == model
                self.dialog.update()
                result, error = self.dialog.solve()
                self.assertIsNotNone(result, error)
                self.assertEqual(result.pitch, pitch)
                self.assertTrue(self.dialog.validate()[0])
                self.assertIn('理论共轭', self.inputs[self.UI.ID_STATS].text)
                rows = self.UI.param_rows(result, self.dialog.read())
                self.assertIn('无加工间隙', self.UI.summary_text(result, self.dialog.read(), []))
                self.assertNotIn('带齿顶圆弧半径', [r[0] for r in rows])

    def test_gt_rejects_rescaled_pitch(self):
        self.select_family('GT')
        params = self.dialog.read()
        params['pitch'] = 2.5
        result, error = self.dialog.solve(params)
        self.assertIsNone(result)
        self.assertIn('不能按比例缩放', error)

    def test_gt_closed_profile_reaches_fusion_adapter(self):
        import importlib
        gt = importlib.import_module('tpg.gt')
        sketch_api = importlib.import_module('tpg.sketch')
        result = gt.solve_groove('2GT', 20)
        self.assertTrue(result.ok, result.message)
        design = harness.adsk.fusion.Design()
        output = sketch_api.build(design.rootComponent, result,
                                  {'sketch_name': 'GT20', 'sampled_fallback': False})
        self.assertTrue(output['ok'])
        self.assertEqual(output['arc_count'], (2 * len(result.smooth_curves) + 1) * result.teeth)
        self.assertTrue(output['compact_used'])
        self.assertEqual(output['source_segment_count'], len(self.G.closed_chain(result)))


if __name__ == '__main__':
    unittest.main()
