"""Continuous GT output: C2 continuity, analytic error, and native spline knots."""
import importlib
import math
import unittest

from test_sampling_performance import _evaluate_spline
from test_gt_geometry import _reference_contact
import test_dryrun as harness


class SmoothCurveTests(unittest.TestCase):
    def setUp(self):
        self.gt = importlib.import_module('tpg.gt')
        self.SK = importlib.import_module('tpg.sketch')
        self.spline = importlib.import_module('tpg.spline')

    def test_analytic_derivative_matches_independent_contact_motion(self):
        for model in self.gt.SPECS:
            result = self.gt.solve_groove(model, 20)
            for arc, a, b in result.envelope_pieces:
                for fraction in (.13, .47, .83):
                    value = a + (b-a)*fraction
                    delta = 1e-6
                    p, _ = _reference_contact(arc, value-delta, result.pitch_radius, result.od_drop/2)
                    q, _ = _reference_contact(arc, value+delta, result.pitch_radius, result.od_drop/2)
                    expected = tuple((y-x)/(2*delta) for x, y in zip(p, q))
                    actual = self.gt._envelope_derivative(arc, value, result.pitch_radius, result.od_drop/2)
                    self.assertLess(math.dist(actual, expected), 1e-7)

    def test_c2_continuity_with_single_interior_knots(self):
        for model in self.gt.SPECS:
            result = self.gt.solve_groove(model, 20)
            curves = self.gt.prepare_smooth_profile(result)
            for (arc, a, b), curve in zip(result.envelope_pieces, curves):
                interior = curve.knots[4:-4]
                self.assertEqual(len(interior), len(set(interior)))
                nodes = curve.knots[3:-3]
                for index in range(len(curve.spans)-1):
                    before, after = curve.spans[index:index+2]
                    h1, h2 = nodes[index+1]-nodes[index], nodes[index+2]-nodes[index+1]
                    d1 = tuple(3*(before[3][d]-before[2][d])/h1 for d in (0,1))
                    d2 = tuple(3*(after[1][d]-after[0][d])/h2 for d in (0,1))
                    dd1 = tuple(6*(before[3][d]-2*before[2][d]+before[1][d])/h1**2 for d in (0,1))
                    dd2 = tuple(6*(after[2][d]-2*after[1][d]+after[0][d])/h2**2 for d in (0,1))
                    self.assertLess(math.dist(d1,d2), 1e-8)
                    self.assertLess(math.dist(dd1,dd2), 1e-6)
                first, last = curve.spans[0], curve.spans[-1]
                actual_start = tuple(3*(first[1][d]-first[0][d])/(nodes[1]-nodes[0]) for d in (0,1))
                actual_end = tuple(3*(last[3][d]-last[2][d])/(nodes[-1]-nodes[-2]) for d in (0,1))
                expected_start = tuple(v*(b-a) for v in self.gt._envelope_derivative(arc,a,result.pitch_radius,result.od_drop/2))
                expected_end = tuple(v*(b-a) for v in self.gt._envelope_derivative(arc,b,result.pitch_radius,result.od_drop/2))
                self.assertLess(math.dist(actual_start,expected_start), 1e-9)
                self.assertLess(math.dist(actual_end,expected_end), 1e-9)

    def test_nurbs_stays_within_reported_analytic_error_bound(self):
        cases = [('2GT',12),('3GT',14),('5GT',18),('2GT',20),('3GT',20),('5GT',20),('5GT',400)]
        for model, teeth in cases:
            for count in (None,9,33,129):
                result = self.gt.solve_groove(model,teeth,samples_per_tooth=count)
                curves = self.gt.prepare_smooth_profile(result)
                if count is None:
                    self.assertLessEqual(result.smooth_error_bound, .001)
                else:
                    self.assertEqual(result.smooth_samples_per_tooth,count)
                for (arc,a,b), curve in zip(result.envelope_pieces,curves):
                    for index in range(251):
                        fraction = index/250
                        expected,_ = _reference_contact(arc,a+(b-a)*fraction,result.pitch_radius,result.od_drop/2)
                        actual = _evaluate_spline(curve.control,3,curve.knots,fraction)
                        self.assertLessEqual(math.dist(actual,expected),result.smooth_error_bound+1e-10)
                        self.assertGreater(actual[1],0)
                        self.assertGreaterEqual(math.hypot(*actual),result.groove_lowest-1e-8)
                        self.assertLessEqual(math.hypot(*actual),result.outer_radius+1e-8)
                self.assertIs(curves,self.gt.prepare_smooth_profile(result))

    def test_topology_validator_rejects_interpolation_loop(self):
        self.assertFalse(self.spline.polar_monotone(((1,3),(5,1),(-3,1),(0,2))))
        for model in self.gt.SPECS:
            result = self.gt.solve_groove(model,20)
            for curve in self.gt.prepare_smooth_profile(result):
                self.assertTrue(all(self.spline.polar_monotone(span) for span in curve.spans))

    def test_native_output_has_no_sampling_corners_and_closes(self):
        result = self.gt.solve_groove('2GT',20)
        design = harness.adsk.fusion.Design()
        output = self.SK.build(design.rootComponent,result,{'center':(12.,34.)})
        sketch = output['sketch']
        self.assertEqual(sketch._lines,[])
        branches = 2*len(result.smooth_curves)
        for spline in sketch._splines:
            interior = spline.geometry.knots[4:-4]
            self.assertEqual(len(interior),len(set(interior)))
        for tooth in range(result.teeth):
            curves = sketch._splines[tooth*branches:(tooth+1)*branches]+[sketch._arcs[tooth]]
            following = sketch._splines[((tooth+1)%result.teeth)*branches]
            for before,after in zip(curves,curves[1:]+[following]):
                p,q=before.endSketchPoint.geometry,after.startSketchPoint.geometry
                self.assertLess(math.dist((p.x,p.y),(q.x,q.y)),1e-10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
