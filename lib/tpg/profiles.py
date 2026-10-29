# -*- coding: utf-8 -*-
"""系列、型号与节距索引。

各节距有独立尺寸，不能把不同齿形按节距相似缩放。实际求解数据由
geometry.py（历史 HTD 名义尺寸模型）与 gt.py（原厂带齿的理论共轭）维护。
本表的齿数范围是软件输入范围，不代表载荷或寿命设计结论。
"""

# ---------------------------------------------------------------------------
# 系列定义
# ---------------------------------------------------------------------------

# groove_model 决定用哪个几何求解器
GROOVE_HTD = 'htd'            # 历史 HTD 尺寸约束模型
GROOVE_TRAPEZOIDAL = 'trap'   # 梯形槽（待实现）
GROOVE_CURVILINEAR = 'curve'  # 曲线槽（待实现）

FAMILIES = {
    # ---- 已实现 ----------------------------------------------------------
    'HTD': {
        'name': 'HTD（名义尺寸参考模型）',
        'standard': '名义尺寸参考；未作完整标准齿廓校核',
        'groove_model': GROOVE_HTD,
        'implemented': True,
        'models': ['2M', '3M', '5M', '8M', '14M', '20M'],
    },

    # ---- 已声明、几何求解器待实现 ----------------------------------------
    'GT': {
        'name': 'GT（2 / 3 / 5 mm 理论共轭轮槽）',
        'standard': 'Gates Unitta 带齿尺寸 + US4515577 共轭方法；无加工间隙',
        'groove_model': GROOVE_CURVILINEAR,
        'implemented': True,
        'models': ['2GT', '3GT', '5GT'],
    },
    'RPP': {
        'name': 'RPP（圆弧齿，Bando/Carlisle 体系）',
        'standard': 'RPP Plus / RPP Silver',
        'groove_model': GROOVE_CURVILINEAR,
        'implemented': False,
        'models': ['RPP3M', 'RPP5M', 'RPP8M', 'RPP14M'],
    },
    'T': {
        'name': 'T 形（梯形齿，公制节距）',
        'standard': 'ISO 5296 / DIN 7721',
        'groove_model': GROOVE_TRAPEZOIDAL,
        'implemented': False,
        'models': ['T2.5', 'T5', 'T10', 'T20'],
    },
    'AT': {
        'name': 'AT 形（梯形齿，公制节距，大齿高）',
        'standard': 'ISO 5296 / DIN 7721',
        'groove_model': GROOVE_TRAPEZOIDAL,
        'implemented': False,
        'models': ['AT5', 'AT10', 'AT20'],
    },
    'MXL': {
        'name': '英制梯形齿（MXL / XL / L / H / XH / XXH）',
        'standard': 'ISO 5296 / ANSI',
        'groove_model': GROOVE_TRAPEZOIDAL,
        'implemented': False,
        'models': ['MXL', 'XL', 'L', 'H', 'XH', 'XXH'],
    },
}

# ---------------------------------------------------------------------------
# 节距表（单位 mm）
# ---------------------------------------------------------------------------

PITCH_TABLE_MM = {
    # HTD
    '2M': 2.0, '3M': 3.0, '5M': 5.0, '8M': 8.0, '14M': 14.0, '20M': 20.0,
    # GT 系
    '2GT': 2.0, '3GT': 3.0, '5GT': 5.0,
    '2MGT': 2.0, '3MGT': 3.0, '5MGT': 5.0, '8MGT': 8.0, '14MGT': 14.0,
    '2MR': 2.0, '3MR': 3.0, '5MR': 5.0, '8MR': 8.0, '14MR': 14.0,
    'GT2-2M': 2.0, 'GT2-3M': 3.0, 'GT2-5M': 5.0,
    'GT3-2M': 2.0, 'GT3-3M': 3.0, 'GT3-5M': 5.0, 'GT3-8M': 8.0, 'GT3-14M': 14.0,
    'GT4-8M': 8.0, 'GT4-14M': 14.0, 'GT5-8M': 8.0, 'GT5-14M': 14.0,
    # RPP
    'RPP3M': 3.0, 'RPP5M': 5.0, 'RPP8M': 8.0, 'RPP14M': 14.0,
    # T / AT
    'T2.5': 2.5, 'T5': 5.0, 'T10': 10.0, 'T20': 20.0,
    'AT5': 5.0, 'AT10': 10.0, 'AT20': 20.0,
    # 英制
    'MXL': 2.032, 'XL': 5.080, 'L': 9.525, 'H': 12.700,
    'XH': 22.225, 'XXH': 31.750,
}

# ---------------------------------------------------------------------------
# HTD 节距和软件齿数范围（非载荷设计范围）
# ---------------------------------------------------------------------------
HTD_MODELS = {
    '2M': {
        'pitch_mm': 2.0,
        'z_min': 10, 'z_max': 200,
        'z_typical': [14, 15, 16, 18, 20, 22, 24, 25, 26, 28, 30, 32, 34,
                      36, 38, 40, 44, 48, 56, 60, 64, 72, 80, 90, 100, 120],
    },
    '3M': {
        'pitch_mm': 3.0,
        'z_min': 10, 'z_max': 200,
        'z_typical': [10, 11, 12, 14, 15, 16, 18, 19, 20, 22, 24, 25, 26,
                      28, 30, 32, 36, 38, 40, 44, 48, 56, 60, 64, 72, 80,
                      90, 100, 120, 144, 168],
    },
    '5M': {
        'pitch_mm': 5.0,
        'z_min': 10, 'z_max': 216,
        'z_typical': [10, 12, 14, 15, 16, 18, 19, 20, 21, 22, 24, 25, 26,
                      27, 28, 30, 32, 34, 36, 38, 40, 42, 44, 45, 48, 50,
                      52, 56, 60, 64, 68, 72, 80, 84, 90, 96, 100, 110,
                      120, 140, 144, 168, 180, 192, 216],
    },
    '8M': {
        'pitch_mm': 8.0,
        'z_min': 10, 'z_max': 192,
        'z_typical': [10, 11, 12, 14, 15, 16, 18, 19, 20, 21, 22, 24, 25,
                      26, 27, 28, 30, 32, 34, 36, 38, 40, 44, 48, 50, 56,
                      60, 64, 72, 80, 84, 90, 96, 100, 112, 120, 128, 144,
                      160, 168, 192],
    },
    '14M': {
        'pitch_mm': 14.0,
        'z_min': 10, 'z_max': 192,
        'z_typical': [14, 19, 20, 21, 22, 24, 25, 26, 28, 30, 32, 34, 36,
                      38, 40, 42, 44, 48, 50, 56, 60, 64, 68, 72, 80, 84,
                      90, 96, 100, 112, 120, 128, 140, 144, 168, 192],
    },
    '20M': {
        'pitch_mm': 20.0,
        'z_min': 14, 'z_max': 160,
        'z_typical': [18, 20, 21, 22, 24, 25, 26, 28, 30, 32, 34, 36, 38,
                      40, 42, 44, 48, 50, 56, 60, 64, 72, 80, 84, 90, 96,
                      100, 112, 120, 140, 144, 160],
    },
}

# 系列 -> 型号表
MODEL_TABLE = {
    'HTD': HTD_MODELS,
    # 其余系列型号已声明但无数据，由 UI 置灰
    'GT': {mid: {'pitch_mm': pitch, 'z_min': 12, 'z_max': 400}
           for mid, pitch in (('2GT', 2.0), ('3GT', 3.0), ('5GT', 5.0))},
    'RPP': {},
    'T': {},
    'AT': {},
    'MXL': {},
}

# ---------------------------------------------------------------------------
# 查询接口
# ---------------------------------------------------------------------------


def family_ids():
    """返回全部系列 id，已实现的排在前面。"""
    impl = [k for k, v in FAMILIES.items() if v['implemented']]
    todo = [k for k, v in FAMILIES.items() if not v['implemented']]
    return impl + todo


def family(fid):
    """返回系列定义字典；不存在返回 None。"""
    return FAMILIES.get(fid)


def is_implemented(fid):
    f = FAMILIES.get(fid)
    return bool(f and f['implemented'])


def model_ids(fid):
    """返回该系列下的型号列表。"""
    return list(MODEL_TABLE.get(fid, {}).keys())


def model(fid, mid):
    """返回型号数据字典；不存在返回 None。"""
    return MODEL_TABLE.get(fid, {}).get(mid)


def pitch_mm(mid):
    """按型号取标准节距(mm)；查不到返回 None。"""
    return PITCH_TABLE_MM.get(mid)


def all_model_ids():
    """全部已声明型号（含未实现系列）。"""
    out = []
    for fid in FAMILIES:
        out.extend(FAMILIES[fid]['models'])
    return out


def model_family(mid):
    """反查型号属于哪个系列。"""
    for fid, f in FAMILIES.items():
        if mid in f['models']:
            return fid
    return None


def full_model_name(fid, mid):
    """生成可读的完整型号名，如 'HTD 5M'。"""
    f = FAMILIES.get(fid)
    if not f:
        return mid
    short = fid
    return '{0} {1}'.format(short, mid)


def belt_width_range_mm(mid):
    """返回该型号常用带宽范围(mm)，仅用于界面提示。"""
    table = {
        '2M': (3.0, 15.0),
        '3M': (6.0, 30.0),
        '5M': (9.0, 40.0),
        '8M': (12.0, 85.0),
        '14M': (20.0, 170.0),
        '20M': (30.0, 230.0),
    }
    return table.get(mid)


def describe(mid):
    """返回型号的一句话说明，用于界面提示。"""
    fid = model_family(mid)
    p = pitch_mm(mid)
    if fid is None or p is None:
        return '未知型号'
    f = FAMILIES[fid]
    return '{0}｜节距 {1:g} mm｜{2}'.format(f['name'], p, f['standard'])
