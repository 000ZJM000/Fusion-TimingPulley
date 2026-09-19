# -*- coding: utf-8 -*-
"""
齿形数据库（发布版）
====================

本模块描述 HTD 标准同步带/带轮的标准数据，不含几何求解逻辑。
几何求解在 geometry.py 中完成。
"""

GROOVE_HTD = 'htd'

FAMILIES = {
    'HTD': {
        'name': 'HTD（高扭矩圆弧齿）',
        'standard': 'ISO 13050 / JB/T 7512.2',
        'groove_model': GROOVE_HTD,
        'implemented': True,
        'models': ['2M', '3M', '5M', '8M', '14M', '20M'],
    },
}

PITCH_TABLE_MM = {
    '2M': 2.0,
    '3M': 3.0,
    '5M': 5.0,
    '8M': 8.0,
    '14M': 14.0,
    '20M': 20.0,
}

HTD_MODELS = {
    '2M': {
        'pitch_mm': 2.0,
        'h': 0.68, 'r_root': 0.315, 'r_tip': 0.35, 'r_flank': 0.30,
        'auto_r_tip': True, 'auto_r_flank': True,
        'belt_h': 0.75, 'r_belt_tip': 0.315, 'r_belt_root': 0.38,
        'z_min': 10, 'z_max': 200,
        'z_typical': [14, 15, 16, 18, 20, 22, 24, 25, 26, 28, 30, 32, 34,
                      36, 38, 40, 44, 48, 56, 60, 64, 72, 80, 90, 100, 120],
    },
    '3M': {
        'pitch_mm': 3.0,
        'h': 0.68, 'r_root': 0.315, 'r_tip': 0.35, 'r_flank': 0.30,
        'auto_r_tip': True, 'auto_r_flank': True,
        'belt_h': 0.75, 'r_belt_tip': 0.315, 'r_belt_root': 0.38,
        'z_min': 10, 'z_max': 200,
        'z_typical': [10, 11, 12, 14, 15, 16, 18, 19, 20, 22, 24, 25, 26,
                      28, 30, 32, 36, 38, 40, 44, 48, 56, 60, 64, 72, 80,
                      90, 100, 120, 144, 168],
    },
    '5M': {
        'pitch_mm': 5.0,
        'h': 0.68, 'r_root': 0.315, 'r_tip': 0.35, 'r_flank': 0.30,
        'auto_r_tip': True, 'auto_r_flank': True,
        'belt_h': 0.75, 'r_belt_tip': 0.315, 'r_belt_root': 0.38,
        'z_min': 10, 'z_max': 216,
        'z_typical': [10, 12, 14, 15, 16, 18, 19, 20, 21, 22, 24, 25, 26,
                      27, 28, 30, 32, 34, 36, 38, 40, 42, 44, 45, 48, 50,
                      52, 56, 60, 64, 68, 72, 80, 84, 90, 96, 100, 110,
                      120, 140, 144, 168, 180, 192, 216],
    },
    '8M': {
        'pitch_mm': 8.0,
        'h': 0.68, 'r_root': 0.315, 'r_tip': 0.35, 'r_flank': 0.30,
        'auto_r_tip': True, 'auto_r_flank': True,
        'belt_h': 0.75, 'r_belt_tip': 0.315, 'r_belt_root': 0.38,
        'z_min': 10, 'z_max': 192,
        'z_typical': [10, 11, 12, 14, 15, 16, 18, 19, 20, 21, 22, 24, 25,
                      26, 27, 28, 30, 32, 34, 36, 38, 40, 44, 48, 50, 56,
                      60, 64, 72, 80, 84, 90, 96, 100, 112, 120, 128, 144,
                      160, 168, 192],
    },
    '14M': {
        'pitch_mm': 14.0,
        'h': 0.68, 'r_root': 0.315, 'r_tip': 0.35, 'r_flank': 0.30,
        'auto_r_tip': True, 'auto_r_flank': True,
        'belt_h': 0.75, 'r_belt_tip': 0.315, 'r_belt_root': 0.38,
        'z_min': 10, 'z_max': 192,
        'z_typical': [14, 19, 20, 21, 22, 24, 25, 26, 28, 30, 32, 34, 36,
                      38, 40, 42, 44, 48, 50, 56, 60, 64, 68, 72, 80, 84,
                      90, 96, 100, 112, 120, 128, 140, 144, 168, 192],
    },
    '20M': {
        'pitch_mm': 20.0,
        'h': 0.68, 'r_root': 0.315, 'r_tip': 0.35, 'r_flank': 0.30,
        'auto_r_tip': True, 'auto_r_flank': True,
        'belt_h': 0.75, 'r_belt_tip': 0.315, 'r_belt_root': 0.38,
        'z_min': 14, 'z_max': 160,
        'z_typical': [18, 20, 21, 22, 24, 25, 26, 28, 30, 32, 34, 36, 38,
                      40, 42, 44, 48, 50, 56, 60, 64, 72, 80, 84, 90, 96,
                      100, 112, 120, 140, 144, 160],
    },
}

MODEL_TABLE = {
    'HTD': HTD_MODELS,
}


def family_ids():
    return list(FAMILIES.keys())


def family(fid):
    return FAMILIES.get(fid)


def is_implemented(fid):
    return fid in FAMILIES


def model_ids(fid):
    return list(MODEL_TABLE.get(fid, {}).keys())


def model(fid, mid):
    return MODEL_TABLE.get(fid, {}).get(mid)


def pitch_mm(mid):
    return PITCH_TABLE_MM.get(mid)


def all_model_ids():
    out = []
    for fid in FAMILIES:
        out.extend(FAMILIES[fid]['models'])
    return out


def model_family(mid):
    for fid, f in FAMILIES.items():
        if mid in f['models']:
            return fid
    return None


def full_model_name(fid, mid):
    f = FAMILIES.get(fid)
    if not f:
        return mid
    return '{0} {1}'.format(fid, mid)


def belt_width_range_mm(mid):
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
    fid = model_family(mid)
    p = pitch_mm(mid)
    if fid is None or p is None:
        return '未知型号'
    f = FAMILIES[fid]
    return '{0}｜节距 {1:g} mm｜{2}'.format(f['name'], p, f['standard'])
