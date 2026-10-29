"""Regression tests for rejected inputs and preservation of requested geometry."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from tpg import geometry as G


class NumericRegressions(unittest.TestCase):
    def test_nonfinite_inputs_return_failure(self):
        for name in ('pitch', 'teeth', 'clearance', 'r_bt_ratio',
                     'flank_angle_deg', 'od_drop', 'depth_ratio', 'r_tip', 'samples'):
            for value in (float('inf'), float('-inf'), float('nan')):
                args = dict(pitch=5.0, teeth=20)
                args[name] = value
                with self.subTest(name=name, value=value):
                    self.assertFalse(G.solve_groove(**args).ok)

    def test_invalid_angles_fail(self):
        for angle in (-1, 0, 180, 360):
            with self.subTest(angle=angle):
                self.assertFalse(G.solve_groove(5, 20, flank_angle_deg=angle).ok)

    def test_unfeasible_radius_is_not_shrunk(self):
        result = G.solve_groove(5, 20, r_tip=0.9)
        self.assertFalse(result.ok)

    def test_feasible_radius_survives_chain_generation(self):
        result = G.solve_groove(5, 20, r_tip=0.4)
        self.assertTrue(result.ok, result.message)
        chain = G.closed_chain(result)
        self.assertEqual(result.r_tip, 0.4)
        fillets = [arc for arc in chain if isinstance(arc, G.Arc) and '倒角' in arc.name]
        self.assertEqual(len(fillets), 40)
        self.assertTrue(all(arc.radius == 0.4 for arc in fillets))

    def test_nonstandard_pitch_does_not_scale_angle(self):
        self.assertEqual(G.get_htd_spec(7.5)['beta'], 7.0)

    def test_belt_lowest_uses_outer_surface_reference(self):
        result = G.solve_groove(5, 20)
        self.assertAlmostEqual(result.belt_tip_lowest,
                               result.outer_radius - G.get_htd_spec(5)['hb'])

    def test_dimension_comparison_does_not_claim_full_mesh_check(self):
        result = G.solve_groove(5, 20, clearance=0.1)
        fit = G.belt_fit(result)
        self.assertFalse(fit['full_profile_checked'])
        self.assertAlmostEqual(fit['center_shift'], 0.0)


if __name__ == '__main__':
    unittest.main()
