# -*- coding: utf-8 -*-
"""纯 Python 几何工具和历史 HTD 名义尺寸模型，长度 mm、角度 deg。

HTD 的构造为槽底圆弧、相切直线侧壁、与外圆相切的齿顶圆角。
约束：Rp=p*z/(2*pi)，Ro=Rp-u，槽底最低点 Ro-hg；由槽口半宽
解侧壁倾角，或采用显式输入角度。各输入不满足约束时返回失败。

本模型不等同于 ISO 13050 完整 H 系统，也不证明完整带齿啮合。
GT 的原厂带齿及理论滚动共轭计算见 gt.py，不能调用此 HTD 模型代替。
"""

import concurrent.futures
import math
import os

_TOL = 1e-12

# ---------------------------------------------------------------------------
# 历史 HTD 名义尺寸表（mm）；3M~20M 部分尺寸参考 JB/T 7512.2-1994。
# 2M 为原有工程参考值。槽底/侧壁构造不声称符合整套制造标准。
# ---------------------------------------------------------------------------

HTD_SPECS = {
    2.0:  {'u': 0.2540, 'hg': 0.76, 'rb': 0.53, 'rf': 0.35, 's': 1.12, 'hb': 0.76, 'r_bt': 0.53, 'r_bf': 0.35, 'rt': 0.15, 'beta': 7.0},
    3.0:  {'u': 0.3810, 'hg': 1.28, 'rb': 0.91, 'rf': 0.60, 's': 1.90, 'hb': 1.17, 'r_bt': 0.81, 'r_bf': 0.55, 'rt': 0.30, 'beta': 7.0},
    5.0:  {'u': 0.5720, 'hg': 2.16, 'rb': 1.56, 'rf': 1.00, 's': 3.25, 'hb': 2.06, 'r_bt': 1.46, 'r_bf': 0.90, 'rt': 0.50, 'beta': 7.0},
    8.0:  {'u': 0.6860, 'hg': 3.54, 'rb': 2.57, 'rf': 1.60, 's': 5.35, 'hb': 3.36, 'r_bt': 2.46, 'r_bf': 1.50, 'rt': 0.80, 'beta': 7.0},
    14.0: {'u': 1.3970, 'hg': 6.20, 'rb': 4.65, 'rf': 3.00, 's': 9.80, 'hb': 6.02, 'r_bt': 4.50, 'r_bf': 2.80, 'rt': 1.40, 'beta': 7.0},
    20.0: {'u': 2.1600, 'hg': 8.60, 'rb': 6.84, 'rf': 4.50, 's': 14.80, 'hb': 8.40, 'r_bt': 6.64, 'r_bf': 4.20, 'rt': 2.00, 'beta': 7.0},
}

# 归一化比例参数（针对自定义节距按 5M 等比放缩）
HTD_RATIOS = {
    'u': 0.5720 / 5.0,    # ~0.1144
    'hg': 2.16 / 5.0,     # ~0.4320
    'rb': 1.56 / 5.0,     # ~0.3120
    'rf': 1.00 / 5.0,     # ~0.2000
    's': 3.25 / 5.0,      # ~0.6500
    'hb': 2.06 / 5.0,     # ~0.4120
    'r_bt': 1.46 / 5.0,   # ~0.2920
    'r_bf': 0.90 / 5.0,   # ~0.1800
    'rt': 0.50 / 5.0,     # 0.10, 标准齿顶倒角推荐系数 (0.10 * p)
    'beta': 7.0,
}

# 默认全局参数字典（向下兼容 UI 默认值）
HTD = {
    'r_bt': HTD_RATIOS['rb'],       # 槽底圆弧半径系数 (rb/p)
    'hb': HTD_RATIOS['hg'],         # 槽深系数 (hg/p)
    'theta_deg': 14.0,              # 齿槽齿形角 2β 参考值 (JB/T 7512.2: 14°)
    'clearance': 0.0,               # 默认额外单边间隙 (× p)
    'min_clearance': 0.0,           # 最小额外间隙
    'od_drop': HTD_RATIOS['u'] * 2, # 外径收缩系数 (2u/p)
    'r_tip': HTD_RATIOS['rt'],      # 齿顶倒角半径系数 (rt/p)
}

_SAMPLES = 192


def get_htd_spec(pitch):
    """查询历史 HTD 尺寸；非标节距仅为 5M 尺寸的工程缩放。

    3M~20M 的名义尺寸可对照 JB/T 7512.2-1994 表 1；2M 与任意节距
    均不在该表范围。此表不能代替 ISO 13050:2022 按齿数分档的 H 齿廓。
    """
    for std_p, sp in HTD_SPECS.items():
        if abs(pitch - std_p) < 1e-4:
            return dict(sp)
    return {k: (v if k == 'beta' else v * pitch)
            for k, v in HTD_RATIOS.items()}


# ---------------------------------------------------------------------------
# 向量工具
# ---------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _scale(a, s):
    return (a[0] * s, a[1] * s)


def _len(a):
    return math.hypot(a[0], a[1])


def _norm(a):
    n = _len(a)
    if n < _TOL:
        raise ValueError('零长度向量')
    return (a[0] / n, a[1] / n)


def _angle_of(v):
    return math.atan2(v[1], v[0])


def _rot(pt, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (pt[0] * c - pt[1] * s, pt[0] * s + pt[1] * c)


# ---------------------------------------------------------------------------
# 数据容器
# ---------------------------------------------------------------------------

class GrooveResult(object):
    """轮槽求解结果。"""

    __slots__ = (
        'ok', 'message', 'warnings',
        # 输入
        'pitch', 'teeth', 'clearance', 'r_bt_ratio', 'theta_deg', 'od_drop',
        'hb_ratio', 'r_tip',
        # 派生
        'pitch_radius', 'outer_radius', 'pitch_angle',
        'r_bt', 'r_bf', 'hb', 'h_pd', 'belt_half_width', 'belt_tip_lowest',
        'groove_lowest', 'groove_depth', 'groove_half_width', 'tip_width',
        # 精确圆弧与直线
        'bottom_arc', 'flank_arc', 'bottom_center', 'flank_center',
        'bottom_arc_right', 'bottom_arc_left', 'bottom_center_right', 'bottom_center_left',
        'contact_right', 'contact_left', 'exit_right', 'exit_left',
        'line_right', 'line_left',
        # 齿顶倒角
        'tip_fillet_arc', 'tip_fillet_arc_right', 'tip_fillet_arc_left',
        'tip_fillet_center', 'tip_fillet_center_right', 'tip_fillet_center_left',
        'tip_out_right', 'tip_out_left',
        'tip_flank_right', 'tip_flank_left',
        # 廓形采样
        'belt_points', 'belt',
        # 扩展参数
        'tip_fillet', 'target_plane', 'center_point', 'has_flank', 'is_auto_theta',
        # 理论尖角与标称槽宽（未倒角前理论交点，用于 CAD 标注对比）
        'theoretical_sharp_right', 'theoretical_sharp_left', 'theoretical_slot_width',
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k, None))
        if self.warnings is None:
            self.warnings = []

    @property
    def pitch_diameter(self):
        return 2.0 * self.pitch_radius

    @property
    def outer_diameter(self):
        return 2.0 * self.outer_radius

    @property
    def root_diameter(self):
        """齿根圆直径：槽底最低点所在圆。"""
        return 2.0 * self.groove_lowest

    def as_dict(self):
        return {
            'ok': self.ok,
            'message': self.message,
            'warnings': list(self.warnings),
            'pitch': self.pitch,
            'teeth': self.teeth,
            'clearance': self.clearance,
            'theta_deg': self.theta_deg,
            'pitch_diameter': self.pitch_diameter,
            'outer_diameter': self.outer_diameter,
            'root_diameter': self.root_diameter,
            'r_bt': self.r_bt,
            'r_bf': self.r_bf,
            'r_tip': self.r_tip,
            'tip_fillet': self.tip_fillet if getattr(self, 'tip_fillet', None) is not None else self.r_tip,
            'groove_depth': self.groove_depth,
            'groove_width': 2.0 * self.groove_half_width,
            'tip_width': self.tip_width,
        }


class Arc(object):
    """一段圆弧。start → mid → end 沿弧顺序，可直接用于 Fusion 的
    sketchArcs.addByThreePoints(start, mid, end)。"""

    __slots__ = ('center', 'radius', 'start', 'end', 'mid',
                 'start_ang', 'end_ang', 'is_ccw', 'name')

    def __init__(self, center, radius, start, end, mid,
                 start_ang, end_ang, is_ccw, name=''):
        self.center = center
        self.radius = radius
        self.start = start
        self.end = end
        self.mid = mid
        self.start_ang = start_ang
        self.end_ang = end_ang
        self.is_ccw = is_ccw
        self.name = name

    @property
    def sweep(self):
        if self.is_ccw:
            return (self.end_ang - self.start_ang) % (2.0 * math.pi)
        else:
            return (self.start_ang - self.end_ang) % (2.0 * math.pi)

    @property
    def sweep_deg(self):
        return math.degrees(self.sweep)

    def __repr__(self):
        return '<Arc {0} r={1:.4f} c=({2:.4f},{3:.4f}) {4:.2f}deg>'.format(
            self.name or '-', self.radius, self.center[0], self.center[1],
            self.sweep_deg)


class Line(object):
    """一段直线。start → end，可直接用于 Fusion 的
    sketchLines.addByTwoPoints(start, end)。"""

    __slots__ = ('start', 'end', 'name')

    def __init__(self, start, end, name=''):
        self.start = start
        self.end = end
        self.name = name

    @property
    def length(self):
        return _len(_sub(self.end, self.start))

    def __repr__(self):
        return '<Line {0} ({1:.4f},{2:.4f})->({3:.4f},{4:.4f}) len={5:.4f}>'.format(
            self.name or '-', self.start[0], self.start[1],
            self.end[0], self.end[1], self.length)


# ---------------------------------------------------------------------------
# 历史带齿参考尺寸及示意采样（不参与制造齿形认证）
# ---------------------------------------------------------------------------

def solve_belt_tooth(pitch, r_bt_ratio=None, flank_angle_deg=None):
    """求解对应规格的同步带齿廓形几何尺寸。"""
    spec = get_htd_spec(pitch)
    r_bt = spec['r_bt'] if r_bt_ratio is None else r_bt_ratio * pitch
    r_bf = spec['r_bf']
    hb = spec['hb']
    theta = math.radians(HTD['theta_deg'] if flank_angle_deg is None
                         else flank_angle_deg)

    cx = spec['s'] / 2.0
    cz = -hb + r_bt
    h_pd = hb - r_bt
    tip_center = (0.0, -h_pd)
    contact = (r_bt * math.sin(theta), -h_pd + r_bt * (1.0 - math.cos(theta)))

    return {
        'r_bt': r_bt,
        'r_bf': r_bf,
        'hb': hb,
        'theta': theta,
        'cx': cx,
        'cz': cz,
        'h_pd': h_pd,
        'tip_center': tip_center,
        'flank_center': (cx, cz),
        'contact': contact,
        'tip_lowest_z': -hb,
        'half_width': cx,
    }


def belt_tooth_points(pitch, samples=None, r_bt_ratio=None,
                      flank_angle_deg=None):
    """带齿廓形采样点（局部坐标）。"""
    belt = solve_belt_tooth(pitch, r_bt_ratio, flank_angle_deg)
    n = samples or _SAMPLES
    n_side = max(10, n // 3)
    n_tip = max(16, n - 2 * n_side)

    r_bt = belt['r_bt']
    hb = belt['hb']
    cx = belt['cx']

    pts = []
    # 右侧从节线到齿顶
    for i in range(n_side + 1):
        t = i / float(n_side)
        pts.append((cx * (1.0 - t * 0.3), -hb * 0.6 * t))
    # 齿顶半圆
    for i in range(1, n_tip + 1):
        ang = -math.pi * 0.2 - math.pi * 0.6 * (i / float(n_tip))
        pts.append((r_bt * math.cos(ang), -hb + r_bt * (1.0 + math.sin(ang))))
    # 左侧回节线
    for i in range(1, n_side + 1):
        t = i / float(n_side)
        pts.append((-cx * (0.7 + t * 0.3), -hb * 0.6 * (1.0 - t)))

    return pts, belt


def offset_points(pts, distance, ref=None):
    """点列等距偏置采样近似（预览用）。"""
    n = len(pts)
    if ref is None:
        ref = min(pts, key=lambda p: p[1])
    out = []
    for i in range(n):
        if i == 0:
            tx = pts[1][0] - pts[0][0]
            ty = pts[1][1] - pts[0][1]
        elif i == n - 1:
            tx = pts[n - 1][0] - pts[n - 2][0]
            ty = pts[n - 1][1] - pts[n - 2][1]
        else:
            tx = pts[i + 1][0] - pts[i - 1][0]
            ty = pts[i + 1][1] - pts[i - 1][1]
        L = math.hypot(tx, ty)
        if L < _TOL:
            out.append(pts[i])
            continue
        nx, ny = ty / L, -tx / L
        if nx * (pts[i][0] - ref[0]) + ny * (pts[i][1] - ref[1]) < 0:
            nx, ny = -nx, -ny
        out.append((pts[i][0] + distance * nx, pts[i][1] + distance * ny))
    return out



# ---------------------------------------------------------------------------
# 几何相切求解
# ---------------------------------------------------------------------------

def _minor_arc_mid(center, radius, ang_s, ang_e):
    """计算从 ang_s 到 ang_e 的**小弧**（短弧）中间点及旋转方向。

    `(ang_e - ang_s) % 2π` 始终给出 CCW 扫掠。当小弧为 CW 时该公式返回
    的是大弧扫掠（≈ 2π），导致中间点落在错误一侧，进而产生巨大的"气球形"圆弧。
    本函数始终选取角度较小的那段弧，正确计算中间点。

    返回 (mid_point, is_ccw)。
    """
    sw_ccw = (ang_e - ang_s) % (2.0 * math.pi)
    if sw_ccw <= math.pi:          # CCW 更短
        sw = sw_ccw
        mid_ang = ang_s + sw / 2.0
        is_ccw = True
    else:                          # CW 更短
        sw = 2.0 * math.pi - sw_ccw
        mid_ang = ang_s - sw / 2.0
        is_ccw = False
    mid = (center[0] + radius * math.cos(mid_ang),
           center[1] + radius * math.sin(mid_ang))
    return mid, is_ccw


def _circle_intersect(c0, r0, c1, r1):
    """求圆 (c0, r0) 与 (c1, r1) 的交点列表。"""
    d = _sub(c1, c0)
    dist = _len(d)
    if dist < _TOL:
        return []
    if dist > r0 + r1 + 1e-9 or dist < abs(r0 - r1) - 1e-9:
        return []
    a = (r0 * r0 - r1 * r1 + dist * dist) / (2.0 * dist)
    h2 = max(0.0, r0 * r0 - a * a)
    h = math.sqrt(h2)
    u = _scale(d, 1.0 / dist)
    base = _add(c0, _scale(u, a))
    if h < 1e-12:
        return [base]
    perp = (-u[1], u[0])
    return [_add(base, _scale(perp, h)), _sub(base, _scale(perp, h))]


def solve_beta_for_groove(Ro, hg, rb, rt, half_s):
    """根据标称槽宽 s（槽口半宽 half_s = s / 2）精确求解齿侧斜线倾角 beta：
    - 使齿侧斜线与齿顶倒角的切点 P_line 的横坐标严格等于 half_s（即槽宽严格等于标准 s，如 3M 为 1.90mm）
    - 槽底圆弧严格相切于齿侧斜线下端点 P_bot
    - 齿顶倒角圆弧严格内切于外圆 Ro，且相切于齿侧斜线上端点 P_line
    - 槽底最低点仅下沉到 Ro - hg，绝对不与齿根圆形成多余相切约束
    """
    Cby = (Ro - hg) + rb
    if rt == 0.0:
        y_sharp = math.sqrt(max(0.0, Ro * Ro - half_s * half_s))
        A = half_s
        B = -(y_sharp - Cby)
        R_AB = math.hypot(A, B)
        if R_AB < rb:
            raise ValueError('槽口宽、槽深与槽底半径不允许相切侧壁')
        phi = math.atan2(B, A)
        arg = max(-1.0, min(1.0, rb / R_AB))
        return phi + math.acos(arg)

    R_ctr = Ro - rt

    def f(b):
        sin_b = math.sin(b)
        cos_b = math.cos(b)
        K = rb + rt - Cby * sin_b
        if R_ctr <= abs(K):
            return -1.0
        v = math.sqrt(R_ctr * R_ctr - K * K)
        xct = K * cos_b + v * sin_b
        px = xct - rt * cos_b
        return px - half_s

    low = 0.0
    high = math.pi / 2.0 - 1e-9
    f_low = f(low)
    f_high = f(high)
    if abs(f_low) < 1e-12:
        return low
    if abs(f_high) < 1e-12:
        return high
    if f_low * f_high > 0:
        raise ValueError('无法在有效角度范围内满足槽宽与相切约束')
    for _ in range(50):
        mid = (low + high) * 0.5
        f_mid = f(mid)
        if abs(f_mid) < 1e-12 or (high - low) < 1e-12:
            return mid
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return (low + high) * 0.5


def groove_arcs(result):
    """计算单个齿槽的尺寸约束轮廓（严格双圆外公切线连续相切模型）：
    - 槽深 hg：带轮外圆顶点 (0, Ro) 到槽底最低点 (0, ybot) 距离严格为 hg，最低点 ybot = Ro - hg
    - 槽底圆弧：半径 rb，圆心 Cb = (0, ybot + rb)
    - 齿侧斜线：法向量与 Y 轴夹角为 β，与槽底圆弧严格相切于 P_bot_r / P_bot_l
    - 齿顶倒角圆弧：半径 rt，严格与齿侧斜线在材料侧相切，且严格与带轮外圆 Ro 内切
    - 齿侧斜线段：连接倒角切点 P_line 与槽底切点 P_bot，槽宽严格吻合标称值 s，斜线长度恒大于零！
    - 连接处（外圆 ↔ 倒角弧 ↔ 齿侧斜线 ↔ 槽底圆弧）全一阶光滑相切（G1 连续，零拐点）。
    """
    if not result.ok:
        raise ValueError('轮槽求解失败：{0}'.format(result.message))

    Ro = result.outer_radius
    hg = result.groove_depth
    rb = result.r_bt
    half_s = getattr(result, 'groove_half_width', None)

    rt = getattr(result, 'r_tip', None)
    if rt is None:
        rt = getattr(result, 'tip_fillet', 0.0) or 0.0
    rt = float(rt)

    # 优先依据标称槽宽 s 自动求解侧壁倾角 beta（使倒角切点/槽口宽度严格吻合标准 s，如 3M 为 1.90mm）
    # 当且仅当显式自定义了齿形角时才采用固定角度
    is_auto = getattr(result, 'is_auto_theta', False) or getattr(result, 'theta_deg', None) is None
    explicit_theta = getattr(result, 'theta_deg', None)
    if (not is_auto) and explicit_theta is not None:
        beta = math.radians(explicit_theta / 2.0)
    elif half_s is not None:
        beta = solve_beta_for_groove(Ro, hg, rb, rt, half_s)
        result.theta_deg = math.degrees(beta) * 2.0
    else:
        raise ValueError('缺少可用于求解齿侧角的槽口宽度')

    if not 0.0 < beta < math.pi / 2.0:
        raise ValueError('相切约束要求齿侧半角在 0° 与 90° 之间')

    ybot = Ro - hg
    P_bot = (0.0, ybot)
    Cby = ybot + rb
    Cb = (0.0, Cby)

    cos_b = math.cos(beta)
    sin_b = math.sin(beta)

    # 槽底圆弧相切切点（法线方向为外向法向量 (cos_b, -sin_b)）
    P_bot_r = (rb * cos_b, Cby - rb * sin_b)
    P_bot_l = (-rb * cos_b, Cby - rb * sin_b)

    # 槽底弧：从 P_bot_r 经 (0, ybot) 到 P_bot_l（顺时针 CW，扫掠角 π - 2β，供整体/校核计算使用）
    ang_b_s = -beta
    ang_b_e = -math.pi + beta
    arc_bottom = Arc(center=Cb, radius=rb, start=P_bot_r, end=P_bot_l, mid=P_bot,
                     start_ang=ang_b_s, end_ang=ang_b_e, is_ccw=False, name='槽底弧')

    # 将槽底圆弧关于中心对称轴分为左右两段，方便标注（汇交于槽底中心最低点 P_bot，生成标准草图顶点与非单段连续底弧）
    # 右槽底弧：从 P_bot_r 到 P_bot（顺时针 CW，角度从 -beta 到 -pi/2）
    ang_s_r = -beta
    ang_e_r = -math.pi / 2.0
    mid_ang_r = (ang_s_r + ang_e_r) / 2.0
    mid_r = (Cb[0] + rb * math.cos(mid_ang_r), Cb[1] + rb * math.sin(mid_ang_r))
    arc_bottom_right = Arc(center=Cb, radius=rb, start=P_bot_r, end=P_bot, mid=mid_r,
                           start_ang=ang_s_r, end_ang=ang_e_r, is_ccw=False, name='右槽底弧')

    # 左槽底弧：从 P_bot 到 P_bot_l（顺时针 CW，角度从 -pi/2 到 -pi + beta）
    ang_s_l = -math.pi / 2.0
    ang_e_l = -math.pi + beta
    mid_ang_l = (ang_s_l + ang_e_l) / 2.0
    mid_l = (Cb[0] + rb * math.cos(mid_ang_l), Cb[1] + rb * math.sin(mid_ang_l))
    arc_bottom_left = Arc(center=Cb, radius=rb, start=P_bot, end=P_bot_l, mid=mid_l,
                          start_ang=ang_s_l, end_ang=ang_e_l, is_ccw=False, name='左槽底弧')

    # 齿侧斜线与外圆理论交点（未倒角时的理论槽宽与理论尖点）
    K_sharp = rb - Cby * sin_b
    disc_sharp = Ro * Ro - K_sharp * K_sharp
    if disc_sharp < 0:
        raise ValueError('齿槽几何超出外圆边界')
    v_sharp = math.sqrt(disc_sharp)
    x_sharp = K_sharp * cos_b + v_sharp * sin_b
    y_sharp = -K_sharp * sin_b + v_sharp * cos_b
    P_sharp_r = (x_sharp, y_sharp)
    P_sharp_l = (-x_sharp, y_sharp)

    # 齿顶倒角与外圆、齿侧斜线双相切解析求解
    rt_used = rt
    if rt > 0.0:
        R_ctr = Ro - rt
        K = rb + rt - Cby * sin_b
        disc = R_ctr * R_ctr - K * K
        if R_ctr <= 0 or disc <= 0:
            raise ValueError('指定倒角半径无法满足外圆与齿侧的相切约束')
        if math.sqrt(disc) <= Cby * cos_b + 1e-9:
            raise ValueError('指定倒角半径使齿侧线段消失；请减小倒角或调整齿槽尺寸')

    if rt > 0.0:
        R_ctr = Ro - rt_used
        K = rb + rt_used - Cby * sin_b
        v = math.sqrt(max(0.0, R_ctr * R_ctr - K * K))
        xct = K * cos_b + v * sin_b
        yct = -K * sin_b + v * cos_b

        Ct_r = (xct, yct)
        Ct_l = (-xct, yct)

        P_line_r = (xct - rt_used * cos_b, yct + rt_used * sin_b)
        P_line_l = (-P_line_r[0], P_line_r[1])

        P_out_r = (xct * Ro / R_ctr, yct * Ro / R_ctr)
        P_out_l = (-P_out_r[0], P_out_r[1])

        # 右齿顶倒角弧：从外圆切点 P_out_r 到侧线切点 P_line_r（逆时针 CCW）
        phi_out_r = math.atan2(yct, xct)
        phi_line_r = math.pi - beta
        sw_fr = (phi_line_r - phi_out_r) % (2.0 * math.pi)
        mid_fr_ang = phi_out_r + sw_fr / 2.0
        mid_fr = (xct + rt_used * math.cos(mid_fr_ang), yct + rt_used * math.sin(mid_fr_ang))
        arc_fillet_r = Arc(center=Ct_r, radius=rt_used, start=P_out_r, end=P_line_r, mid=mid_fr,
                           start_ang=phi_out_r, end_ang=phi_line_r, is_ccw=True, name='右齿顶倒角弧')

        # 左齿顶倒角弧：从侧线切点 P_line_l 到外圆切点 P_out_l（逆时针 CCW）
        phi_line_l = beta
        phi_out_l = math.pi - phi_out_r
        sw_fl = (phi_out_l - phi_line_l) % (2.0 * math.pi)
        mid_fl_ang = phi_line_l + sw_fl / 2.0
        mid_fl = (-xct + rt_used * math.cos(mid_fl_ang), yct + rt_used * math.sin(mid_fl_ang))
        arc_fillet_l = Arc(center=Ct_l, radius=rt_used, start=P_line_l, end=P_out_l, mid=mid_fl,
                           start_ang=phi_line_l, end_ang=phi_out_l, is_ccw=True, name='左齿顶倒角弧')
    else:
        rt_used = 0.0
        P_out_r = P_sharp_r
        P_out_l = P_sharp_l
        P_line_r = P_sharp_r
        P_line_l = P_sharp_l
        arc_fillet_r = None
        arc_fillet_l = None
        Ct_r = P_sharp_r
        Ct_l = P_sharp_l

    result.r_tip = rt_used
    result.tip_fillet = rt_used

    line_right = Line(start=P_line_r, end=P_bot_r, name='右齿侧线')
    line_left = Line(start=P_bot_l, end=P_line_l, name='左齿侧线')
    side_length = ((P_line_r[0] - P_bot_r[0]) * sin_b +
                   (P_line_r[1] - P_bot_r[1]) * cos_b)
    if side_length <= 1e-9:
        raise ValueError('齿侧相切线段长度必须大于零')

    # pts 统一导出关键几何点与倒角圆弧
    pts = (P_out_r, P_out_l, P_bot_r, P_bot_l,
           P_out_r, P_out_l, P_line_r, P_line_l,
           arc_fillet_r, arc_fillet_l, line_left,
           P_sharp_r, P_sharp_l,
           arc_bottom_right, arc_bottom_left, Cb, Cb, P_bot)

    return arc_bottom, line_right, line_left, pts


# ---------------------------------------------------------------------------
# 轮槽主求解
# ---------------------------------------------------------------------------

def solve_groove(pitch, teeth, clearance=None, r_bt_ratio=None,
                 flank_angle_deg=None, od_drop=None, samples=None,
                 depth_ratio=None, tip_fillet=None, r_tip=None):
    """求解历史 HTD 尺寸约束模型；返回结果不表示 ISO 齿廓合格。"""
    warnings = ['历史 HTD 模型仅满足名义尺寸及解析相切约束，未实现 ISO 13050 完整齿廓与公差。']

    # 输入校验
    try:
        if isinstance(pitch, bool) or isinstance(teeth, bool):
            raise ValueError()
        pitch = float(pitch)
        teeth_value = float(teeth)
        if not math.isfinite(pitch) or not math.isfinite(teeth_value):
            raise ValueError()
        z = int(teeth_value)
    except (TypeError, ValueError, OverflowError):
        return GrooveResult(ok=False, message='节距和齿数必须是有限数值，齿数必须为整数')
    if pitch <= 0:
        return GrooveResult(ok=False, message='节距必须大于 0')
    if teeth_value != z:
        return GrooveResult(ok=False, message='齿数必须是整数')
    if z < 3:
        return GrooveResult(ok=False, message='齿数必须 >= 3')

    values = {'间隙': clearance, '槽底半径系数': r_bt_ratio,
              '齿形角': flank_angle_deg, '外径收缩量': od_drop,
              '槽深系数': depth_ratio, '倒角半径': tip_fillet,
              '齿顶倒角半径': r_tip, '采样数': samples}
    for label, value in values.items():
        if value is not None:
            try:
                finite = math.isfinite(value)
            except (TypeError, ValueError, OverflowError):
                finite = False
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite:
                return GrooveResult(ok=False, message=label + '必须为有限数值')
    if r_bt_ratio is not None and r_bt_ratio <= 0:
        return GrooveResult(ok=False, message='槽底半径系数必须大于零')
    if depth_ratio is not None and depth_ratio <= 0:
        return GrooveResult(ok=False, message='槽深系数必须大于零')
    if flank_angle_deg is not None and not 0 < flank_angle_deg < 180:
        return GrooveResult(ok=False, message='齿形角必须大于 0° 且小于 180°')
    if samples is not None and (int(samples) != samples or samples < 3):
        return GrooveResult(ok=False, message='采样数必须为不小于 3 的整数')
    if samples is not None:
        samples = int(samples)
    if r_tip is not None and tip_fillet is not None and r_tip != tip_fillet:
        return GrooveResult(ok=False, message='r_tip 与 tip_fillet 不能指定不同的倒角半径')

    if pitch not in (3.0, 5.0, 8.0, 14.0, 20.0):
        warnings.append('该节距不在 JB/T 7512.2-1994 表 1 范围内，仅为工程参考。')

    spec = get_htd_spec(pitch)

    if clearance is None:
        c = HTD['clearance'] * pitch
    else:
        c = float(clearance)
    if c < 0:
        return GrooveResult(ok=False, message='间隙不能为负')

    # 外径收缩量与外圆半径
    if od_drop is not None:
        if od_drop < 0:
            return GrooveResult(ok=False, message='外径收缩系数不能为负')
        u = float(od_drop) / 2.0
    else:
        u = spec['u']

    pitch_radius = pitch * z / (2.0 * math.pi)
    pitch_angle = 2.0 * math.pi / z
    outer_radius = pitch_radius - u

    if not math.isfinite(outer_radius):
        return GrooveResult(ok=False, message='输入尺寸超出有限浮点计算范围')

    if outer_radius <= 0:
        return GrooveResult(
            ok=False,
            message='外圆半径为负：齿数 {0} 太少（节圆半径 {1:.4f} mm，外径收缩 {2:.4f} mm）'
                    .format(z, pitch_radius, u * 2.0))

    # 槽深与槽宽
    if depth_ratio is not None and depth_ratio > 0:
        hg = depth_ratio * pitch + c
    else:
        hg = spec['hg'] + c

    # 槽底半径与齿侧半径
    if r_bt_ratio is not None and r_bt_ratio > 0:
        rb = r_bt_ratio * pitch + c
    else:
        rb = spec['rb'] + c
    rf = spec.get('rf', spec['rb'])

    # 齿形角 2β：若未指定则自动依据标称槽宽求解侧壁倾角
    is_auto_theta = (flank_angle_deg is None)
    theta_deg = flank_angle_deg if flank_angle_deg is not None else spec.get('beta', 7.0) * 2.0

    # 齿顶倒角半径 rt
    if r_tip is not None:
        rt = float(r_tip)
    elif tip_fillet is not None:
        rt = float(tip_fillet)
    else:
        rt = float(spec['rt'])

    if rt < 0:
        return GrooveResult(ok=False, message='齿顶倒角半径不能为负')
    if rt > 0 and rt >= outer_radius:
        return GrooveResult(
            ok=False,
            message='齿顶倒角半径必须小于带轮外圆半径')

    s = spec['s'] + 2.0 * c
    xe = s / 2.0

    if xe >= outer_radius:
        return GrooveResult(
            ok=False,
            message='槽口半宽 {0:.4f} mm 大于等于外圆半径 {1:.4f} mm：'
                    '齿数太少或节距过大'.format(xe, outer_radius))

    # 槽口角宽检查
    half_slot_angle = math.asin(min(1.0, xe / outer_radius))
    slot_angle = 2.0 * half_slot_angle
    if slot_angle >= pitch_angle:
        return GrooveResult(
            ok=False,
            message='槽口角宽 {0:.2f}° 不小于齿距角 {1:.2f}°：'
                    '齿数 {2} 太少，槽口已占满整周'.format(
                        math.degrees(slot_angle), math.degrees(pitch_angle), z))

    groove_lowest = outer_radius - hg
    if groove_lowest <= 0:
        return GrooveResult(
            ok=False,
            message='槽底最低点半径为负（{0:.4f} mm）：齿数太少或槽深过大'
                    .format(groove_lowest))

    nominal_tip_width = outer_radius * (pitch_angle - slot_angle)
    if nominal_tip_width <= 0:
        return GrooveResult(
            ok=False,
            message='齿顶宽度 {0:.4f} mm 为负：请增大齿数或减小间隙'.format(nominal_tip_width))

    belt_pts, belt = belt_tooth_points(pitch, samples, r_bt_ratio, flank_angle_deg)

    res = GrooveResult(
        ok=True,
        message='求解成功',
        warnings=warnings,
        pitch=pitch,
        teeth=z,
        clearance=c,
        r_bt_ratio=(r_bt_ratio if r_bt_ratio is not None else spec['rb'] / pitch),
        theta_deg=theta_deg,
        is_auto_theta=is_auto_theta,
        od_drop=2.0 * u,
        hb_ratio=hg / pitch,
        r_tip=rt,
        tip_fillet=rt,
        pitch_radius=pitch_radius,
        outer_radius=outer_radius,
        pitch_angle=pitch_angle,
        r_bt=rb,
        r_bf=rf,
        hb=hg,
        h_pd=belt['h_pd'],
        belt_half_width=belt['half_width'],
        belt_tip_lowest=outer_radius - spec['hb'],
        groove_lowest=groove_lowest,
        groove_depth=hg,
        groove_half_width=xe,
        tip_width=nominal_tip_width,
        belt_points=belt_pts,
        belt=belt,
    )

    try:
        # 求解一次并严格保留指定尺寸；不可通过缩小倒角掩盖不可行输入。
        for attempt in range(1):
            bottom_arc, line_right, line_left, pts = groove_arcs(res)
            res.bottom_arc = bottom_arc
            res.line_right = line_right
            res.line_left = line_left
            res.flank_arc = None
            res.has_flank = (line_right is not None)
            res.bottom_center = bottom_arc.center
            res.flank_center = bottom_arc.center
            res.exit_right, res.exit_left = pts[0], pts[1]
            res.contact_right, res.contact_left = pts[2], pts[3]
            if len(pts) > 4:
                res.tip_out_right, res.tip_out_left = pts[4], pts[5]
                res.tip_flank_right, res.tip_flank_left = pts[6], pts[7]
                res.tip_fillet_arc_right = pts[8]
                res.tip_fillet_arc_left = pts[9]
                res.tip_fillet_arc = pts[8]
                if pts[8] is not None:
                    res.tip_fillet_center = pts[8].center
                    res.tip_fillet_center_right = pts[8].center
                if pts[9] is not None:
                    res.tip_fillet_center_left = pts[9].center

                # 精确计算含倒角时的齿顶外圆弧宽
                ang_out_r = math.atan2(res.tip_out_right[0], res.tip_out_right[1])
                sw_tip = pitch_angle - 2.0 * ang_out_r
                res.tip_width = outer_radius * sw_tip
                if res.tip_width <= 1e-9:
                    return GrooveResult(
                        ok=False,
                        message='齿顶倒角过大导致齿顶外圆宽度为负：请减小倒角半径或增大齿数')
            if len(pts) > 12:
                res.theoretical_sharp_right = pts[11]
                res.theoretical_sharp_left = pts[12]
                res.theoretical_slot_width = 2.0 * pts[11][0]
            if len(pts) > 16:
                res.bottom_arc_right = pts[13]
                res.bottom_arc_left = pts[14]
                res.bottom_center_right = pts[15]
                res.bottom_center_left = pts[16]
            break
    except ValueError as err:
        return GrooveResult(ok=False, message=str(err))

    return res


# ---------------------------------------------------------------------------
# 整圈轮廓构造
# ---------------------------------------------------------------------------

def _reverse_arc(arc):
    """反转圆弧的遍历方向。"""
    sa, ea = arc.end_ang, arc.start_ang
    ccw = not arc.is_ccw
    if ccw:
        sweep = (ea - sa) % (2.0 * math.pi)
    else:
        sweep = -((sa - ea) % (2.0 * math.pi))
    mid_ang = sa + sweep / 2.0
    mid = (arc.center[0] + arc.radius * math.cos(mid_ang),
           arc.center[1] + arc.radius * math.sin(mid_ang))
    return Arc(center=arc.center, radius=arc.radius,
               start=arc.end, end=arc.start, mid=mid,
               start_ang=sa, end_ang=ea, is_ccw=ccw, name=arc.name)


def _rotate_arc(arc, ang):
    return Arc(center=_rot(arc.center, ang),
               radius=arc.radius,
               start=_rot(arc.start, ang),
               end=_rot(arc.end, ang),
               mid=_rot(arc.mid, ang),
               start_ang=arc.start_ang + ang,
               end_ang=arc.end_ang + ang,
               is_ccw=arc.is_ccw,
               name=arc.name)


def _mirror_arc(arc):
    return Arc(center=(-arc.center[0], arc.center[1]),
               radius=arc.radius,
               start=(-arc.start[0], arc.start[1]),
               end=(-arc.end[0], arc.end[1]),
               mid=(-arc.mid[0], arc.mid[1]),
               start_ang=math.pi - arc.start_ang,
               end_ang=math.pi - arc.end_ang,
               is_ccw=not arc.is_ccw,
               name=arc.name)


def _rotate_line(line, ang):
    return Line(start=_rot(line.start, ang),
                end=_rot(line.end, ang),
                name=line.name)


def _rotate_entity(ent, ang):
    if isinstance(ent, Arc):
        return _rotate_arc(ent, ang)
    elif isinstance(ent, Line):
        return _rotate_line(ent, ang)
    else:
        raise TypeError('未知图元类型: {0}'.format(type(ent)))


def closed_chain(result):
    """生成完整连续闭合轮廓（逆时针）：
    单个齿距由完全相切的圆弧与斜线严格首尾相接组成：
    - 若 r_tip > 0：
        [右齿侧线, 右槽底弧, 左槽底弧, 左齿侧线, 左齿顶倒角弧, 齿顶外圆弧, 右齿顶倒角弧] (7 段)
    - 若 r_tip == 0：
        [右齿侧线, 右槽底弧, 左槽底弧, 左齿侧线, 齿顶外圆弧] (5 段)

    所有连接点（外圆 ↔ 倒角弧 ↔ 侧线 ↔ 右底弧 ↔ 槽底顶点 ↔ 左底弧 ↔ 侧线）一阶光滑相切（G1 连续），端点严格贴合（gap = 0.0）！
    """
    if not result.ok:
        raise ValueError('轮槽求解失败：{0}'.format(result.message))

    if getattr(result, 'profile_chain', None) is not None:
        return list(result.profile_chain)

    z = int(result.teeth)
    pitch_ang = result.pitch_angle
    Ro = result.outer_radius

    bottom_arc, line_right, line_left, pts = groove_arcs(result)
    arc_bottom_right = pts[13]
    arc_bottom_left = pts[14]
    arc_fillet_r = pts[8]
    arc_fillet_l = pts[9]

    chain = []

    for i in range(z):
        ang_i = i * pitch_ang
        ang_next = ((i + 1) % z) * pitch_ang

        e_lr = _rotate_entity(line_right, ang_i)
        e_abr = _rotate_entity(arc_bottom_right, ang_i)
        e_abl = _rotate_entity(arc_bottom_left, ang_i)
        e_ll = _rotate_entity(line_left, ang_i)

        if arc_fillet_l is not None:
            e_afl = _rotate_entity(arc_fillet_l, ang_i)
            tip_s = e_afl.end
        else:
            e_afl = None
            tip_s = e_ll.end

        if arc_fillet_r is not None:
            e_afr_next = _rotate_entity(arc_fillet_r, ang_next)
            tip_e = e_afr_next.start
        else:
            e_afr_next = None
            e_lr_next = _rotate_entity(line_right, ang_next)
            tip_e = e_lr_next.start

        ang_tip_s = math.atan2(tip_s[1], tip_s[0])
        ang_tip_e = math.atan2(tip_e[1], tip_e[0])
        sw = (ang_tip_e - ang_tip_s) % (2.0 * math.pi)
        mid_ang = ang_tip_s + sw / 2.0
        mid = (Ro * math.cos(mid_ang), Ro * math.sin(mid_ang))
        e_outer = Arc(center=(0.0, 0.0), radius=Ro,
                      start=tip_s, end=tip_e, mid=mid,
                      start_ang=ang_tip_s, end_ang=ang_tip_e, is_ccw=True, name='齿顶外圆弧')

        tooth_ents = [e_lr, e_abr, e_abl, e_ll]
        if e_afl is not None:
            tooth_ents.append(e_afl)
        tooth_ents.append(e_outer)
        if e_afr_next is not None:
            tooth_ents.append(e_afr_next)

        chain.extend(tooth_ents)

    # 严格端点坐标复用（首尾相接，gap = 0.0）
    for k in range(len(chain)):
        next_k = (k + 1) % len(chain)
        chain[next_k].start = chain[k].end

    return chain


def groove_positions(result):
    """返回各齿槽的圆弧序列与槽口极角。

    每个齿槽返回 ((arcs...), a_right, a_left)。
    """
    if not result.ok:
        raise ValueError('轮槽求解失败：{0}'.format(result.message))
    chain = closed_chain(result)
    z = int(result.teeth)
    per_tooth = len(chain) // z
    out = []
    for i in range(z):
        sub = chain[i * per_tooth : (i + 1) * per_tooth]
        outer_arc = [a for a in sub if a.name == '齿顶外圆弧'][0]
        a_left = outer_arc.start_ang
        a_right = outer_arc.end_ang
        out.append((tuple(sub), a_right, a_left))
    return out


def tip_arcs(result):
    """外圆齿顶圆弧序列。"""
    if not result.ok:
        raise ValueError('轮槽求解失败：{0}'.format(result.message))
    chain = closed_chain(result)
    return [a for a in chain if isinstance(a, Arc) and a.name == '齿顶外圆弧']


def tip_arc_pairs(result):
    """齿顶圆弧的 (起始角, 终止角, 角宽)，逆时针。"""
    arcs = tip_arcs(result)
    return [(a.start_ang, a.end_ang, a.sweep) for a in arcs]


def tip_arc_stats(result):
    """返回 (最小齿顶角宽, 最大齿顶角宽, 单槽角宽) 弧度。"""
    arcs = tip_arcs(result)
    if not arcs:
        return (0.0, 0.0, 0.0)
    sweeps = [a.sweep for a in arcs]
    pitch_angle = 2.0 * math.pi / result.teeth
    slot_angle = (pitch_angle - sweeps[0]) % (2.0 * math.pi)
    return (min(sweeps), max(sweeps), slot_angle)


def sample_chain(chain, tolerance=0.01):
    pts = []
    for ent in chain:
        if isinstance(ent, Arc):
            n = chord_segments(ent.radius, ent.sweep, tolerance)
            direction = 1.0 if ent.is_ccw else -1.0
            for i in range(n):
                ang = ent.start_ang + direction * ent.sweep * (i / float(n))
                pts.append((ent.center[0] + ent.radius * math.cos(ang),
                            ent.center[1] + ent.radius * math.sin(ang)))
        elif isinstance(ent, Line):
            pts.append(ent.start)
    return pts


def chain_gap_report(arcs):
    """闭合缝隙检查，返回最大首尾间隙 (mm)。"""
    if not arcs:
        return float('inf')
    worst = 0.0
    for i in range(len(arcs)):
        a = arcs[i]
        b = arcs[(i + 1) % len(arcs)]
        worst = max(worst, _len(_sub(a.end, b.start)))
    return worst


def polygon_area(pts):
    if len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def belt_fit(result, samples=None):
    """仅比较名义槽深与带齿高；不构成全齿廓干涉/啮合校核。"""
    spec = get_htd_spec(result.pitch)
    hb_belt = spec['hb']
    r_bt_belt = spec['r_bt']
    r_bf_belt = spec['r_bf']

    tip_gap = result.groove_depth - hb_belt
    bottom_excess = result.bottom_arc.radius - r_bt_belt
    # 历史模型的槽底圆心始终是 (0, Ro-hg+rb)，额外间隙同时加到 hg/rb，
    # 因此不能把输入 clearance 冒充圆心位移测量。
    nominal_bottom_y = result.outer_radius - spec['hg'] + spec['rb']
    center_shift = _len(_sub(result.bottom_arc.center, (0.0, nominal_bottom_y)))
    flank_radius_excess = (result.flank_arc.radius - r_bf_belt) if result.flank_arc is not None else 0.0

    warnings = []
    if tip_gap < -1e-9:
        warnings.append(('error', '带齿高度超出带轮槽深 {0:.4f} mm'.format(-tip_gap)))
    if bottom_excess < -1e-9:
        warnings.append(('warn', '槽底圆弧半径小于带齿顶圆弧半径'))

    return {
        'ok': tip_gap >= -1e-9,
        'tip_gap': tip_gap,
        'clearance': result.clearance,
        'bottom_excess': bottom_excess,
        'center_shift': center_shift,
        'flank_radius_excess': flank_radius_excess,
        'warnings': warnings,
        'full_profile_checked': False,
        'scope': 'nominal_depth_only',
    }


def pitch_diameter(pitch, teeth):
    return pitch * teeth / math.pi


def recommended_bore(result):
    root_d = result.root_diameter
    hi = max(4.0, root_d * 0.40)
    lo = min(6.0, max(3.0, hi * 0.35))
    return (lo, hi)


def chord_segments(radius, sweep, tolerance=0.01):
    if not all(math.isfinite(v) for v in (radius, sweep, tolerance)):
        raise ValueError('离散圆弧参数必须为有限数值')
    if tolerance <= 0:
        raise ValueError('离散公差必须大于零')
    if radius <= 0 or sweep <= 0:
        return 1
    tol = tolerance
    if tol >= radius:
        return 2
    # acos(1-tol/r) 在大半径/小公差时会因消去误差得到零。
    # 同一弦高公式的稳定形式；不得用固定段数上限破坏用户要求的公差。
    half = 2.0 * math.asin(math.sqrt(tol / radius / 2.0))
    if half == 0.0:
        raise ValueError('离散公差小于当前浮点精度可表达的范围')
    return max(2, int(math.ceil(sweep / (2.0 * half))))


# ---------------------------------------------------------------------------
# 多线程并发批处理
# ---------------------------------------------------------------------------

def solve_groove_batch(params_list, max_workers=None):
    """并发批量求解带轮轮槽（多线程加速，提高扫描与大批量计算效率）。"""
    workers = max_workers or min(32, (os.cpu_count() or 4) + 4)

    def _worker(item):
        if isinstance(item, dict):
            return solve_groove(**item)
        elif isinstance(item, (tuple, list)):
            return solve_groove(*item)
        else:
            raise TypeError('params_list 元素必须是 dict 或 tuple/list')

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_worker, params_list))
