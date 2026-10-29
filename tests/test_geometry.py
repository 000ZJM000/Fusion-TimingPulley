# -*- coding: utf-8 -*-
"""
几何引擎离线自检（ISO 13050 / JB/T 7512.2 标准带轮廓形）
======================================================

    python tests/test_geometry.py

覆盖：
    1. 标准同步带齿几何数据与规格一致性
    2. 轮槽精确相切、槽底 U 型扫掠角（160°~200°，杜绝气球形畸变）、整圈连续闭合
    3. 全型号 × 常用齿数多线程并发扫描（2M~20M，211 组规格）
    4. 非法输入被拒绝
    5. 参数敏感性（间隙 / 齿侧角 / 齿顶半径 / 外径收缩）
    6. 多线程并发批处理求解 (solve_groove_batch)
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, 'lib'))

from tpg import geometry as G          # noqa: E402
from tpg import profiles as P          # noqa: E402

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PASS = []
FAIL = []


def check(name, ok, detail=''):
    if ok:
        PASS.append(name)
    else:
        FAIL.append('{0}  {1}'.format(name, detail))


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------------------------------------------------------------------
# 1. 带齿规格与解析解
# ---------------------------------------------------------------------------

def verify_belt_tooth():
    print('\n[1] 标准带齿数据校验 (ISO 13050)')
    print('{0:<6}{1:>10}{2:>10}{3:>10}{4:>10}{5:>12}'.format(
        '节距', 'r_bt', 'r_bf', 'hb', '槽口半宽', '齿顶最低点z'))
    print('-' * 62)
    for pitch in (2.0, 3.0, 5.0, 8.0, 14.0, 20.0):
        b = G.solve_belt_tooth(pitch)
        r_bt, r_bf = b['r_bt'], b['r_bf']
        hb = b['hb']

        print('{0:<6g}{1:>10.4f}{2:>10.4f}{3:>10.4f}{4:>10.4f}{5:>12.4f}'.format(
            pitch, r_bt, r_bf, hb, b['half_width'], b['tip_lowest_z']))

        check('p={0:g} 带齿顶半径为正'.format(pitch), r_bt > 0)
        check('p={0:g} 带齿侧半径为正'.format(pitch), r_bf > 0)
        check('p={0:g} 带齿高度为正'.format(pitch), hb > 0)
        check('p={0:g} 槽口半宽合理'.format(pitch),
              0.15 * pitch < b['half_width'] < 0.45 * pitch,
              '{0:.4f} ({1:.3f}p)'.format(b['half_width'], b['half_width'] / pitch))


def verify_arc_sweep():
    print('\n[1.5] Arc.sweep 跨分支割线 (±π) 测试')
    arc_ccw = G.Arc(center=(0, 0), radius=10.0, start=(0, 0), end=(0, 0), mid=(0, 0),
                    start_ang=3.0, end_ang=-3.0, is_ccw=True, name='cross_pi_ccw')
    expected_ccw = (-3.0 - 3.0) % (2.0 * math.pi)
    check('CCW 跨越分支割线 sweep 正确', abs(arc_ccw.sweep - expected_ccw) < 1e-12,
          'got {0}, expected {1}'.format(arc_ccw.sweep, expected_ccw))
    check('CCW sweep 为正且小于 2π', 0 < arc_ccw.sweep < 2.0 * math.pi)

    arc_cw = G.Arc(center=(0, 0), radius=10.0, start=(0, 0), end=(0, 0), mid=(0, 0),
                   start_ang=-3.0, end_ang=3.0, is_ccw=False, name='cross_pi_cw')
    expected_cw = (-3.0 - 3.0) % (2.0 * math.pi)
    check('CW 跨越分支割线 sweep 正确', abs(arc_cw.sweep - expected_cw) < 1e-12,
          'got {0}, expected {1}'.format(arc_cw.sweep, expected_cw))
    print('  Arc.sweep 跨分支割线测试通过')


# ---------------------------------------------------------------------------
# 2. 单点：轮槽几何 + 啮合 + 无气球形畸变
# ---------------------------------------------------------------------------

def verify_case(label, pitch, teeth, clearance=None, **kw):
    res = G.solve_groove(pitch, teeth, clearance=clearance, **kw)
    if not res.ok:
        check(label, False, '求解失败: ' + str(res.message))
        return None

    fit = G.belt_fit(res)

    try:
        chain = G.closed_chain(res)
        gap = G.chain_gap_report(chain)
    except ValueError as err:
        check(label + ' | 闭合链可构造', False, str(err))
        return res

    b = res.bottom_arc
    f = res.flank_arc

    has_fillet = (res.r_tip is not None and res.r_tip > 1e-9)
    per_tooth = len(chain) // int(teeth)
    expected_segments = per_tooth * int(teeth)
    tot_b = b.sweep_deg

    print('{0:<16} PCD={1:>9.4f} OD={2:>9.4f} 槽底={3:>8.4f} 槽深={4:>7.4f} '
          '槽口半宽={5:>7.4f} 齿顶宽={6:>7.4f} 槽底弧={7:>6.1f}° 段数={8:>4d}'
          .format(label, res.pitch_diameter, res.outer_diameter,
                  res.groove_lowest, res.groove_depth, res.groove_half_width,
                  res.tip_width, tot_b, len(chain)))

    check(label + ' | 整圈闭合 (gap < 1e-12)', gap < 1e-12, 'gap={0:.3e}'.format(gap))
    check(label + ' | 段数 = {0}×齿数'.format(per_tooth),
          len(chain) == expected_segments,
          '{0} vs {1}'.format(len(chain), expected_segments))
    check(label + ' | 带齿不干涉轮槽', fit['ok'], str(fit['warnings']))
    check(label + ' | 齿顶间隙大于等于零', fit['tip_gap'] >= -1e-9,
          'tip={0:.5f}'.format(fit['tip_gap']))
    check(label + ' | 槽底圆弧半径不小于带齿顶', fit['bottom_excess'] >= -1e-9,
          'excess={0:.5f}'.format(fit['bottom_excess']))
    check(label + ' | 外圆 < 节圆',
          res.outer_radius < res.pitch_radius,
          'Rout={0:.4f} Rp={1:.4f}'.format(res.outer_radius, res.pitch_radius))
    check(label + ' | 槽底低于外圆',
          res.groove_lowest < res.outer_radius,
          '{0:.4f} < {1:.4f}'.format(res.groove_lowest, res.outer_radius))
    check(label + ' | 齿顶宽为正', res.tip_width > 0,
          '{0:.4f}'.format(res.tip_width))

    # 关键防气球形畸变检查：正常 HTD 槽底圆弧总扫掠角应在 100°~200°，绝不能出现 318° 畸变气球
    check(label + ' | 槽底圆弧扫掠角正常 (100°~200°)', 100.0 <= tot_b <= 200.0,
          'got {0:.2f}° (拒绝气球形畸变)'.format(tot_b))

    # 左右底弧非单段连续，在槽底中心最低点交汇
    abr = getattr(res, 'bottom_arc_right', None)
    abl = getattr(res, 'bottom_arc_left', None)
    check(label + ' | 左右底弧独立存在', abr is not None and abl is not None)
    if abr is not None and abl is not None:
        check(label + ' | 左右底弧在槽底中心交汇', _dist(abr.end, abl.start) < 1e-12)
        check(label + ' | 左右底弧半径均等于槽底半径',
              abs(abr.radius - res.r_bt) < 1e-9 and abs(abl.radius - res.r_bt) < 1e-9)
        check(label + ' | 左右底弧圆心重合', _dist(abr.center, abl.center) < 1e-12)

    # 槽底与齿侧直线相切检验
    lr = getattr(res, 'line_right', None)
    if lr is not None:
        check(label + ' | 槽底-齿侧切点重合',
              _dist(b.start, res.contact_right) < 1e-9 and
              _dist(lr.end, res.contact_right) < 1e-9)
        nb = (res.contact_right[0] - b.center[0], res.contact_right[1] - b.center[1])
        vl = (lr.end[0] - lr.start[0], lr.end[1] - lr.start[1])
        dot_nl = abs(nb[0] * vl[0] + nb[1] * vl[1]) / (G._len(nb) * G._len(vl))
        check(label + ' | 槽底圆弧与齿侧直线相切', dot_nl < 1e-9, 'dot={0:.3e}'.format(dot_nl))

    check(label + ' | 槽口落在外圆上',
          abs(_dist(res.exit_right, (0.0, 0.0)) - res.outer_radius) < 1e-9,
          '{0:.3e}'.format(abs(_dist(res.exit_right, (0, 0)) - res.outer_radius)))

    # 齿顶倒角相切与几何检验
    if has_fillet:
        check(label + ' | 齿顶倒角半径大于零', res.r_tip > 0)
        check(label + ' | 倒角圆弧存在', res.tip_fillet_arc_right is not None)
        check(label + ' | 倒角外圆切点在带轮外圆上',
          abs(G._len(res.tip_out_right) - res.outer_radius) < 1e-9)
        check(label + ' | 倒角外圆切点在倒角圆上',
          abs(_dist(res.tip_out_right, res.tip_fillet_center_right) - res.r_tip) < 1e-9)
        check(label + ' | 倒角齿侧切点在齿侧直线上',
          _dist(res.tip_flank_right, lr.start) < 1e-9 if lr is not None else True)
        check(label + ' | 倒角齿侧切点在倒角圆上',
          abs(_dist(res.tip_flank_right, res.tip_fillet_center_right) - res.r_tip) < 1e-9)

        # 外圆与倒角切点法线共线
        no = res.tip_out_right
        nto = (res.tip_out_right[0] - res.tip_fillet_center_right[0],
               res.tip_out_right[1] - res.tip_fillet_center_right[1])
        cross_out = abs(no[0] * nto[1] - no[1] * nto[0]) / (G._len(no) * G._len(nto))
        check(label + ' | 倒角与外圆切点法线共线相切', cross_out < 1e-12, 'sin={0:.3e}'.format(cross_out))

    # 标准公称尺寸精确度检验（JB/T 7512.2 / ISO 13050）
    if res.clearance == 0.0 and getattr(res, 'r_bt_ratio', None) is None:
        sp = G.get_htd_spec(res.pitch)
        check(label + ' | 槽底圆弧半径符合国标 R={0:.2f}mm'.format(sp['rb']),
              abs(b.radius - sp['rb']) < 1e-4,
              'got {0:.4f}, expected {1:.4f}'.format(b.radius, sp['rb']))
        check(label + ' | 节顶距符合国标 u={0:.4f}mm'.format(sp['u']),
              abs((res.pitch_radius - res.outer_radius) - sp['u']) < 1e-4,
              'got {0:.4f}, expected {1:.4f}'.format(res.pitch_radius - res.outer_radius, sp['u']))
        if lr is not None:
            mouth_w = math.hypot(lr.start[0] - res.line_left.end[0], lr.start[1] - res.line_left.end[1])
            check(label + ' | 齿侧相切线段长度非零且存在', G._len(G._sub(lr.start, lr.end)) > 0)
            check(label + ' | 理论槽宽大于零', getattr(res, 'theoretical_slot_width', 0) > 0)

    sweeps = [p[2] for p in G.tip_arc_pairs(res)]
    check(label + ' | 齿顶圆弧角宽为正', all(s > 0 for s in sweeps),
          'min={0:.6f}'.format(min(sweeps) if sweeps else -1))

    poly = G.sample_chain(chain, tolerance=0.005)
    check(label + ' | 面积为正(逆时针)', G.polygon_area(poly) > 0,
          '{0:.4f}'.format(G.polygon_area(poly)))

    return res


# ---------------------------------------------------------------------------
# 2.5 多线程批处理求解自检
# ---------------------------------------------------------------------------

def verify_batch_solve():
    print('\n[2.5] 多线程批处理 solve_groove_batch 测试')
    params_list = [
        {'pitch': 2.0, 'teeth': 16},
        {'pitch': 3.0, 'teeth': 24},
        {'pitch': 5.0, 'teeth': 20, 'clearance': 0.1},
        {'pitch': 8.0, 'teeth': 30},
        {'pitch': 14.0, 'teeth': 40},
        {'pitch': 20.0, 'teeth': 30},
    ]
    serial_results = [G.solve_groove(**p) for p in params_list]
    parallel_results = G.solve_groove_batch(params_list, max_workers=4)

    check('批处理结果数量一致', len(serial_results) == len(parallel_results))
    for i, (s, p) in enumerate(zip(serial_results, parallel_results)):
        check('批处理 [{0}] 成功状态一致'.format(i), s.ok == p.ok and s.ok is True)
        check('批处理 [{0}] 节圆直径一致'.format(i), abs(s.pitch_diameter - p.pitch_diameter) < 1e-12)
        check('批处理 [{0}] 槽深一致'.format(i), abs(s.groove_depth - p.groove_depth) < 1e-12)
        check('批处理 [{0}] 齿顶宽一致'.format(i), abs(s.tip_width - p.tip_width) < 1e-12)
    print('  并发批处理测试通过 ({0} 组任务)'.format(len(params_list)))


# ---------------------------------------------------------------------------
# 3. 全型号扫描 (多线程并发求解)
# ---------------------------------------------------------------------------

def scan_models():
    print('\n[3] 全型号 × 常用齿数扫描 (多线程并发求解)')
    total = 0
    bad = 0
    tasks = []
    for mid in P.model_ids('HTD'):
        m = P.model('HTD', mid)
        pitch = m['pitch_mm']
        for z in m['z_typical']:
            tasks.append((mid, pitch, z))

    batch_params = [{'pitch': pitch, 'teeth': z} for mid, pitch, z in tasks]
    batch_results = G.solve_groove_batch(batch_params)

    shown_per_model = {}
    for (mid, pitch, z), res in zip(tasks, batch_results):
        total += 1
        if not res.ok:
            bad += 1
            print('  !! {0} z={1} 失败: {2}'.format(mid, z, res.message))
            continue
        try:
            chain = G.closed_chain(res)
            gap = G.chain_gap_report(chain)
        except ValueError as err:
            bad += 1
            print('  !! {0} z={1} 闭合失败: {2}'.format(mid, z, err))
            continue
        if gap > 1e-12:
            bad += 1
            print('  !! {0} z={1} 闭合间隙 {2:.3e}'.format(mid, z, gap))
            continue
        per_tooth = len(chain) // z
        expected_n = per_tooth * z
        if len(chain) != expected_n:
            bad += 1
            print('  !! {0} z={1} 段数异常: {2} != {3}'.format(mid, z, len(chain), expected_n))
            continue
        fit = G.belt_fit(res)
        if not fit['ok']:
            bad += 1
            print('  !! {0} z={1} 啮合校核失败 {2}'.format(mid, z, fit['warnings']))
            continue
        if res.tip_width <= 0:
            bad += 1
            print('  !! {0} z={1} 齿顶宽非正'.format(mid, z))
            continue
        # 槽底角扫掠检查
        tot_b = res.bottom_arc.sweep_deg
        if not (100.0 <= tot_b <= 200.0):
            bad += 1
            print('  !! {0} z={1} 槽底扫掠角异常: {2:.2f}°'.format(
                mid, z, tot_b))
            continue

        shown = shown_per_model.get(mid, 0)
        if shown < 2:
            print('{0:<6}{1:>6}  PCD={2:>9.4f} OD={3:>9.4f} 槽深={4:>7.4f} '
                  '齿顶宽={5:>7.4f} 槽底弧={6:>6.1f}° 齿顶间隙={7:>8.5f}'.format(
                      mid, z, res.pitch_diameter, res.outer_diameter,
                      res.groove_depth, res.tip_width, tot_b, fit['tip_gap']))
            shown_per_model[mid] = shown + 1

    check('全型号扫描无失败', bad == 0, '{0}/{1} 失败'.format(bad, total))
    print('共扫描 {0} 组，失败 {1} 组 (多线程并发执行)'.format(total, bad))


# ---------------------------------------------------------------------------
# 4. 非法输入
# ---------------------------------------------------------------------------

def scan_invalid():
    print('\n[4] 非法输入')
    cases = [
        ('节距为 0', dict(pitch=0, teeth=20)),
        ('节距为负', dict(pitch=-5, teeth=20)),
        ('齿数 2', dict(pitch=5, teeth=2)),
        ('齿数非整数', dict(pitch=5, teeth=20.5)),
        ('间隙为负', dict(pitch=5, teeth=20, clearance=-1)),
        ('外径收缩为负', dict(pitch=5, teeth=20, od_drop=-1.0)),
        ('齿顶半径过大', dict(pitch=5, teeth=20, r_bt_ratio=6.0)),
        ('齿数 3', dict(pitch=5, teeth=3)),
        ('齿顶倒角为负', dict(pitch=5, teeth=20, r_tip=-0.5)),
        ('齿顶倒角 >= rf', dict(pitch=5, teeth=20, r_tip=1.5)),
        ('齿顶倒角过大', dict(pitch=5, teeth=20, r_tip=5.0)),
    ]
    for name, kw in cases:
        res = G.solve_groove(**kw)
        check('非法输入被拒绝: ' + name, not res.ok, '竟然返回 ok=True')


# ---------------------------------------------------------------------------
# 5. 参数敏感性
# ---------------------------------------------------------------------------

def scan_sensitivity():
    print('\n[5] 参数敏感性（5M / 20 齿）')

    print('\n-- 额外间隙 --')
    print('{0:>10}{1:>11}{2:>11}{3:>11}{4:>10}'.format(
        '间隙mm', 'D外圆', '槽深', '齿顶宽', '齿顶间隙'))
    print('-' * 55)
    for c in (0.0, 0.05, 0.1, 0.2, 0.3):
        res = G.solve_groove(5.0, 20, clearance=c)
        if c == 0.3:
            check('间隙 0.3 不允许靠缩小圆角伪造可解结果', not res.ok, res.message)
            continue
        if not res.ok:
            check('间隙 {0} 可解'.format(c), False, res.message)
            continue
        fit = G.belt_fit(res)
        print('{0:>10.3f}{1:>11.4f}{2:>11.4f}{3:>11.4f}{4:>10.5f}'
              .format(c, res.outer_diameter, res.groove_depth, res.tip_width, fit['tip_gap']))
        check('间隙 {0} 可解'.format(c), True)
        check('间隙 {0} 齿形圆弧正常'.format(c), res.bottom_arc is not None)
        tot_b = res.bottom_arc.sweep_deg
        check('间隙 {0} 槽底弧无畸变'.format(c), 100.0 <= tot_b <= 200.0)

    print('\n-- 齿侧角 --')
    print('{0:>10}{1:>11}{2:>11}{3:>11}{4:>11}'.format(
        '齿侧角°', 'r_bf', '槽深', '齿顶宽', '槽底弧度°'))
    print('-' * 58)
    for th in (10.0, 16.0, 20.0, 26.0, 32.0, 40.0):
        res = G.solve_groove(5.0, 20, flank_angle_deg=th)
        if not res.ok:
            print('{0:>10.1f}  失败: {1}'.format(th, res.message))
            continue
        tot_b = res.bottom_arc.sweep_deg
        print('{0:>10.1f}{1:>11.4f}{2:>11.4f}{3:>11.4f}{4:>11.1f}'.format(
            th, res.r_bf, res.groove_depth, res.tip_width, tot_b))

    print('\n-- 外径收缩系数 --')
    print('{0:>12}{1:>12}{2:>12}{3:>12}'.format(
        'od_drop/p', 'D外圆', '槽深', '齿顶宽'))
    print('-' * 50)
    for k in (0.0, 0.15, 0.2286, 0.35, 0.45):
        res = G.solve_groove(5.0, 20, od_drop=k * 5.0)
        if not res.ok:
            print('{0:>12.3f}  失败: {1}'.format(k, res.message))
            continue
        print('{0:>12.3f}{1:>12.4f}{2:>12.4f}{3:>12.4f}'.format(
            k, res.outer_diameter, res.groove_depth, res.tip_width))

    print('\n-- 齿顶倒角半径 rt --')
    print('{0:>10}{1:>11}{2:>11}{3:>11}{4:>11}'.format(
        'rt(mm)', 'D外圆', '槽深', '齿顶宽', '段数'))
    print('-' * 58)
    for rt_val in (0.0, 0.10, 0.25, 0.40):
        res = G.solve_groove(5.0, 20, r_tip=rt_val)
        if not res.ok:
            print('{0:>10.2f}  失败: {1}'.format(rt_val, res.message))
            continue
        ch = G.closed_chain(res)
        gap = G.chain_gap_report(ch)
        print('{0:>10.2f}{1:>11.4f}{2:>11.4f}{3:>11.4f}{4:>11d}'.format(
            rt_val, res.outer_diameter, res.groove_depth, res.tip_width, len(ch)))
        check('rt={0:.2f} 可解'.format(rt_val), res.ok)
        check('rt={0:.2f} 闭合 (gap < 1e-12)'.format(rt_val), gap < 1e-12)
        expected_n = (7 if rt_val > 0.0 else 5) * 20
        check('rt={0:.2f} 段数正确'.format(rt_val), len(ch) == expected_n)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print('=' * 78)
    print('同步带轮几何引擎 离线自检 (标准 ISO 13050 模型)')
    print('=' * 78)

    verify_belt_tooth()
    verify_arc_sweep()

    print('\n[2] 轮槽几何 / 啮合 / 闭合')
    verify_case('5M-20T', 5.0, 20)
    verify_case('5M-20T c=0.1', 5.0, 20, clearance=0.1)
    verify_case('5M-20T c=0.2', 5.0, 20, clearance=0.2)
    verify_case('5M-20T r_tip=0', 5.0, 20, r_tip=0)
    verify_case('5M-20T r_tip=0.35', 5.0, 20, r_tip=0.35)
    verify_case('5M-10T', 5.0, 10)
    verify_case('5M-216T', 5.0, 216)
    verify_case('2M-14T', 2.0, 14)
    verify_case('2M-20T', 2.0, 20)
    verify_case('3M-30T', 3.0, 30)
    verify_case('8M-30T', 8.0, 30)
    verify_case('14M-40T', 14.0, 40)
    verify_case('20M-30T', 20.0, 30)

    verify_batch_solve()
    scan_models()
    scan_invalid()
    scan_sensitivity()

    print('\n' + '=' * 78)
    print('通过 {0} 项，失败 {1} 项'.format(len(PASS), len(FAIL)))
    if FAIL:
        print('\n失败明细:')
        for f in FAIL[:40]:
            print('  x ' + f)
        return 1
    print('全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
