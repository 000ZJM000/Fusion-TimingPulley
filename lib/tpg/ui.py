# -*- coding: utf-8 -*-
"""
命令对话框（参数界面）
======================

全部可调参数按分页组织：

    基本参数   齿形系列 / 型号 / 齿数 / 节距（可自定义）
    齿槽几何   齿顶圆弧半径 / 齿侧角 / 间隙 / 外径收缩 / 槽深
    轴孔键槽   轴孔直径 / 键槽 / 定位螺孔
    输出选项   草图名 / 替换同名 / 构造圆 / 标注文字 / 折线回退
    计算结果   实时数值汇总 + 轮廓预览图

设计原则：**所有能算的都不让用户输**（实时显示），**所有标准值都可覆盖**。
"""

import math
import os
import csv

import adsk.core
import adsk.fusion

from . import geometry as G
from . import profiles as P
from . import gt as GT

# 输入 id
ID_PROFILE = 'profile_family'
ID_MODEL = 'profile_model'
ID_TEETH = 'teeth'
ID_TEETH_LIST = 'teeth_list'
ID_PITCH = 'pitch'
ID_PITCH_AUTO = 'pitch_auto'
ID_TARGET_PLANE = 'target_plane'
ID_CENTER_POINT = 'center_point'
ID_RBT = 'r_bt_ratio'
ID_THETA = 'theta_deg'
ID_CLEAR = 'clearance'
ID_ODDROP = 'od_drop'
ID_DEPTH = 'depth_ratio'
ID_TIP_FILLET = 'tip_fillet'
ID_GT_SAMPLING = 'gt_sampling_mode'
ID_GT_SAMPLES = 'gt_samples_per_tooth'
ID_GT_TOLERANCE = 'gt_tolerance'
ID_GT_HINT = 'gt_sampling_hint'
ID_COMPACT_GT = 'compact_gt'
ID_SKETCH_NAME = 'sketch_name'
ID_REPLACE = 'replace'
ID_PITCH_CIRCLE = 'draw_pitch_circle'
ID_ROOT_CIRCLE = 'draw_root_circle'
ID_OUTER_CIRCLE = 'draw_outer_circle'
ID_MOUTH_LINE = 'draw_mouth_line'
ID_CENTER_LINE = 'draw_center_line'
ID_LABELS = 'draw_labels'
ID_FALLBACK = 'sampled_fallback'
ID_SUMMARY = 'summary'
ID_WARN = 'warn'
ID_STATS = 'stats'

_sep_i = [0]


def _sid(tag):
    _sep_i[0] += 1
    return '{0}_{1}'.format(tag, _sep_i[0])


def _set_value_input(inp, expr_str, float_val=None):
    """安全设置 Fusion 360 ValueCommandInput 的值。
    在真实 Fusion 360 API 中，ValueCommandInput.value 是只读属性，必须通过 .expression 设置！
    同时在桩测试环境中兼容 .value 赋值。
    """
    if inp is None:
        return
    try:
        inp.expression = str(expr_str)
    except Exception:
        pass
    if float_val is not None:
        try:
            inp.value = float_val
        except Exception:
            pass


class Dialog(object):
    """命令对话框状态与控制。"""

    def __init__(self, design):
        self.design = design
        self.inputs = None
        self.el = {}              # id -> CommandInput
        self.is_dark = True
        self._suppress = False    # 抑制 inputChanged 递归
        self.units = 'mm'
        self.last_result = None
        self.last_error = ''

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------

    def create(self, inputs):
        self.inputs = inputs
        self._detect_theme()
        self._suppress = True
        try:
            self._build(inputs)
        finally:
            self._suppress = False
        self.update(read_only=False)

    def _detect_theme(self):
        try:
            th = adsk.core.Application.get().preferences.generalPreferences \
                .activeUserInterfaceTheme
            self.is_dark = (th == adsk.core.UserInterfaceThemes
                            .DarkBlueUserInterfaceTheme)
        except Exception:
            self.is_dark = True

    # -- 分页 -----------------------------------------------------------

    def _build(self, inputs):
        tab1 = inputs.addTabCommandInput(_sid('tab'), '基本参数')
        t1 = tab1.children
        self._build_basic(t1)

        tab2 = inputs.addTabCommandInput(_sid('tab'), '齿槽几何')
        self._build_groove(tab2.children)

        tab3 = inputs.addTabCommandInput(_sid('tab'), '输出选项')
        self._build_output(tab3.children)

        tab4 = inputs.addTabCommandInput(_sid('tab'), '结果与预览')
        self._build_result(tab4.children)

    # -- 基本参数 -------------------------------------------------------

    def _build_basic(self, inp):
        # 装配式两级选择器
        def _add_filter_safe(sel_input, filter_name):
            try:
                sel_input.addSelectionFilter(filter_name)
            except Exception:
                pass

        sel_plane = inp.addSelectionInput(
            ID_TARGET_PLANE, '放置平面', '放置平面（面/基准面，未选默认当前草图或XY面）')
        for f in ['PlanarFaces', 'ConstructionPlanes', 'Profiles', 'Sketches']:
            _add_filter_safe(sel_plane, f)
        sel_plane.setSelectionLimits(0, 1)
        self.el[ID_TARGET_PLANE] = sel_plane

        sel_center = inp.addSelectionInput(
            ID_CENTER_POINT, '圆心点', '圆心点（草图点/顶点/圆弧/圆边，未选默认原点）')
        for f in ['SketchPoints', 'Vertices', 'ConstructionPoints',
                  'CircularEdges', 'SketchCurves']:
            _add_filter_safe(sel_center, f)
        sel_center.setSelectionLimits(0, 1)
        self.el[ID_CENTER_POINT] = sel_center

        inp.addSeparatorCommandInput(_sid('sep'))

        fams = P.family_ids()
        dd = inp.addDropDownCommandInput(ID_PROFILE, '齿形系列',
                                         adsk.core.DropDownStyles.TextListDropDownStyle)
        for i, fid in enumerate(fams):
            f = P.family(fid)
            label = f['name'] if f['implemented'] else '{0}（未实现）'.format(f['name'])
            dd.listItems.add(label, i == 0)
        self.el[ID_PROFILE] = dd
        self._families = fams

        dd2 = inp.addDropDownCommandInput(ID_MODEL, '型号',
                                          adsk.core.DropDownStyles.TextListDropDownStyle)
        self._fill_models(dd2, fams[0])
        self.el[ID_MODEL] = dd2

        self.el[ID_PITCH_AUTO] = inp.addBoolValueInput(
            ID_PITCH_AUTO, '节距自动（按型号）', True, '', True)
        self.el[ID_PITCH] = inp.addValueInput(
            ID_PITCH, '节距 p', 'mm',
            adsk.core.ValueInput.createByString('5.0 mm'))
        self.el[ID_PITCH].isEnabled = False

        self.el[ID_TEETH] = inp.addIntegerSpinnerCommandInput(
            ID_TEETH, '齿数 z', 6, 400, 1, 20)

        inp.addTextBoxCommandInput(
            _sid('hint'), '',
            '提示：齿数为整数；节距取消自动后可直接输入任意值（含非标）。',
            2, True)

    def _fill_models(self, dd, fid):
        dd.listItems.clear()
        ids = P.model_ids(fid)
        f = P.family(fid)
        if not ids:
            # 未实现系列：把声明过的型号列出来但不可选
            dd.listItems.add('（该系列几何求解器待实现）', True)
            dd.isEnabled = False
            return
        dd.isEnabled = True
        for i, mid in enumerate(ids):
            dd.listItems.add(mid, i == 0)

    # -- 齿槽几何 -------------------------------------------------------

    def _build_groove(self, inp):
        sampling = inp.addDropDownCommandInput(
            ID_GT_SAMPLING, 'GT 采样方式', adsk.core.DropDownStyles.TextListDropDownStyle)
        sampling.listItems.add('按误差自动采样', True)
        sampling.listItems.add('指定每齿采样点数', False)
        self.el[ID_GT_SAMPLING] = sampling
        self.el[ID_GT_SAMPLES] = inp.addIntegerSpinnerCommandInput(
            ID_GT_SAMPLES, '每齿采样点数', 9, 513, 2, 33)
        self.el[ID_GT_TOLERANCE] = inp.addValueInput(
            ID_GT_TOLERANCE, 'GT 曲线误差上限', 'mm',
            adsk.core.ValueInput.createByString('0.001 mm'))
        self.el[ID_GT_HINT] = inp.addTextBoxCommandInput(
            ID_GT_HINT, '', '点数包含两端和槽底，取奇数。连续曲线模式不会保留采样折角；'
            '点数越多，对理论轮廓的逼近越精细。', 2, True)
        inp.addTextBoxCommandInput(
            _sid('hint'), '齿槽几何',
            'HTD 参数可以覆盖；修改后的齿形属于自定义几何。'
            '尺寸参考不等于整套标准符合性或啮合认证。', 3, True)

        mid = self.current_model()
        p = P.pitch_mm(mid) if mid else 3.0
        spec = G.get_htd_spec(p)

        self.el[ID_RBT] = inp.addValueInput(
            ID_RBT, '槽底圆弧半径系数 r_b/p', '',
            adsk.core.ValueInput.createByReal(spec['rb'] / p))
        inp.addTextBoxCommandInput(
            _sid('h'), '', '按各节距的独立尺寸表取值；非标节距按 5M 缩放，仅作自定义几何。', 2, True)

        self.el[ID_THETA] = inp.addValueInput(
            ID_THETA, '齿槽齿形角 2β（参考值）', 'deg',
            adsk.core.ValueInput.createByString('{0:g} deg'.format(spec.get('beta', 7.0) * 2.0)))
        inp.addTextBoxCommandInput(
            _sid('h'), '', '保持默认时按槽宽约束求解；手动角度按输入值执行，无解时拒绝生成。', 2, True)

        self.el[ID_CLEAR] = inp.addValueInput(
            ID_CLEAR, '单边间隙系数 c/p', '',
            adsk.core.ValueInput.createByReal(G.HTD['clearance']))
        inp.addTextBoxCommandInput(
            _sid('h'), '',
            '标准 0.00。按需调整额外单边加工/配合余量。', 1, True)

        self.el[ID_ODDROP] = inp.addValueInput(
            ID_ODDROP, '外径收缩系数 2δ/p', '',
            adsk.core.ValueInput.createByReal(spec['u'] * 2.0 / p))
        inp.addTextBoxCommandInput(
            _sid('h'), '',
            '外圆直径 = 节圆直径 − 2δ。标准两倍节顶距（2δ）：2M 0.508, 3M 0.762(或常用0.760), 5M 1.144, 8M 1.372mm。', 2, True)

        self.el[ID_DEPTH] = inp.addValueInput(
            ID_DEPTH, '槽深系数 h/p', '',
            adsk.core.ValueInput.createByReal(0.0))
        inp.addTextBoxCommandInput(
            _sid('h'), '',
            '0 表示采用尺寸表中的槽深。', 1, True)

        self.el[ID_TIP_FILLET] = inp.addValueInput(
            ID_TIP_FILLET, '齿顶倒角半径 r_t', 'mm',
            adsk.core.ValueInput.createByString('{0:.2f} mm'.format(spec.get('rt', 0.10 * p))))
        inp.addTextBoxCommandInput(
            _sid('h'), '',
            '以当前尺寸表为初值；无解时不会自动缩小输入的圆角。', 2, True)

    # -- 输出选项 -------------------------------------------------------

    def _build_output(self, inp):
        self.el[ID_SKETCH_NAME] = inp.addStringValueInput(
            ID_SKETCH_NAME, '草图名称', '同步带轮')
        self.el[ID_REPLACE] = inp.addBoolValueInput(
            ID_REPLACE, '覆盖同名草图（默认保留并自动重命名）', True, '', False)

        inp.addSeparatorCommandInput(_sid('sep'))
        self.el[ID_PITCH_CIRCLE] = inp.addBoolValueInput(
            ID_PITCH_CIRCLE, '绘制节圆（构造线）', True, '', True)
        self.el[ID_ROOT_CIRCLE] = inp.addBoolValueInput(
            ID_ROOT_CIRCLE, '绘制齿根圆（构造线）', True, '', True)
        self.el[ID_OUTER_CIRCLE] = inp.addBoolValueInput(
            ID_OUTER_CIRCLE, '绘制外圆（构造线）', True, '', False)
        self.el[ID_MOUTH_LINE] = inp.addBoolValueInput(
            ID_MOUTH_LINE, '绘制齿槽标称宽构造线（用于测量 1.90mm 等）', True, '', True)
        self.el[ID_CENTER_LINE] = inp.addBoolValueInput(
            ID_CENTER_LINE, '绘制齿槽对称中心线（构造线）', True, '', True)
        self.el[ID_LABELS] = inp.addBoolValueInput(
            ID_LABELS, '添加尺寸标注文字', True, '', False)

        inp.addSeparatorCommandInput(_sid('sep'))
        self.el[ID_FALLBACK] = inp.addBoolValueInput(
            ID_FALLBACK, '精确圆弧失败时改用折线近似', True, '', True)
        self.el[ID_COMPACT_GT] = inp.addBoolValueInput(
            ID_COMPACT_GT, 'GT 连续光滑曲线（推荐）', True, '', True)
        inp.addTextBoxCommandInput(
            _sid('h'), '', '按共轭公式构造光滑样条，避免采样点产生拉伸分面。'
            '关闭后使用折线；连续曲线失败时停止生成，不自动降级。', 3, True)

    # -- 结果与预览 -----------------------------------------------------

    def _build_result(self, inp):
        inp.addTextBoxCommandInput(
            _sid('h'), '计算结果',
            '所有数值由几何引擎实时解算，随参数即时更新。', 2, True)

        self.el[ID_SUMMARY] = inp.addTextBoxCommandInput(
            ID_SUMMARY, '', '', 8, True)
        self.el[ID_SUMMARY].isFullWidth = True
        self.el[ID_STATS] = inp.addTextBoxCommandInput(
            ID_STATS, '', '', 3, True)
        self.el[ID_STATS].isFullWidth = True
        self.el[ID_WARN] = inp.addTextBoxCommandInput(
            ID_WARN, '', '', 3, True)
        self.el[ID_WARN].isFullWidth = True

        # 说明：此处**不含任何预览控件**。
        # 早期版本用过 ImageCommandInput，但它在部分 Fusion 环境下会抛
        # "invalid argument imageFile" 并导致整个参数界面构建失败，
        # 故已彻底移除。所有结果均以数值文本呈现。
        inp.addSeparatorCommandInput(_sid('sep'))
        inp.addTextBoxCommandInput(
            _sid('h'), '',
            '生成后请在模型树中查看草图；几何尺寸以数值为准。', 1, True)

    # ------------------------------------------------------------------
    # 参数读取
    # ------------------------------------------------------------------

    def current_family(self):
        """当前选中的齿形系列 id。

        通过 listItems 的 isSelected 判断，不依赖 index 属性
        （不同 Fusion 版本对 selectedItem.index 的支持不一致）。
        """
        dd = self.el[ID_PROFILE]
        items = dd.listItems
        for i in range(items.count):
            it = items.item(i)
            if it.isSelected and i < len(self._families):
                return self._families[i]
        return self._families[0]

    def current_model(self):
        fid = self.current_family()
        ids = P.model_ids(fid)
        if not ids:
            return None
        dd = self.el[ID_MODEL]
        items = dd.listItems
        for i in range(items.count):
            it = items.item(i)
            if it.isSelected and it.name in ids:
                return it.name
        return ids[0]

    def read(self):
        """读取全部输入，返回参数字典。"""
        fid = self.current_family()
        mid = self.current_model()
        pitch_mm = None
        if mid:
            pitch_mm = P.pitch_mm(mid)

        pitch_auto = self.el[ID_PITCH_AUTO].value
        if not pitch_auto:
            pitch_mm = self.el[ID_PITCH].value * 10.0      # cm -> mm

        # Fusion 角度输入的数据库单位始终是 rad，不能按数值大小猜单位。
        raw_theta = self.el[ID_THETA].value
        if isinstance(raw_theta, str):
            s = raw_theta.lower().replace('deg', '').replace('度', '').strip()
            theta_deg = float(s)
        else:
            theta_deg = math.degrees(float(raw_theta))

        # 放置平面与圆心点实体读取
        def _get_selection_entity(inp):
            if inp is not None and getattr(inp, 'selectionCount', 0) > 0:
                try:
                    return inp.selection(0).entity
                except Exception:
                    return None
            return None

        target_plane = _get_selection_entity(self.el.get(ID_TARGET_PLANE))
        center_point = _get_selection_entity(self.el.get(ID_CENTER_POINT))

        tip_fillet_val = self.el[ID_TIP_FILLET].value
        if isinstance(tip_fillet_val, (int, float)):
            tip_fillet_mm = float(tip_fillet_val) * 10.0   # cm -> mm
        else:
            tip_fillet_mm = 0.25

        return {
            'family': fid,
            'model': mid,
            'pitch': pitch_mm,
            'teeth': int(self.el[ID_TEETH].value),
            'target_plane': target_plane,
            'center_point': center_point,
            'r_bt_ratio': self.el[ID_RBT].value,
            'theta_deg': theta_deg,
            'clearance_ratio': self.el[ID_CLEAR].value,
            'od_drop_ratio': self.el[ID_ODDROP].value,
            'depth_ratio': self.el[ID_DEPTH].value,
            'tip_fillet': tip_fillet_mm,
            'sketch_name': self.el[ID_SKETCH_NAME].value,
            'replace': self.el[ID_REPLACE].value,
            'draw_pitch_circle': self.el[ID_PITCH_CIRCLE].value,
            'draw_root_circle': self.el[ID_ROOT_CIRCLE].value,
            'draw_outer_circle': self.el[ID_OUTER_CIRCLE].value,
            'draw_mouth_line': self.el[ID_MOUTH_LINE].value if ID_MOUTH_LINE in self.el else False,
            'draw_center_line': self.el[ID_CENTER_LINE].value if ID_CENTER_LINE in self.el else False,
            'labels': self.el[ID_LABELS].value,
            'sampled_fallback': self.el[ID_FALLBACK].value,
            'gt_sampling_mode': ('point_count' if
                                self.el[ID_GT_SAMPLING].listItems.item(1).isSelected
                                else 'tolerance'),
            'gt_samples_per_tooth': int(self.el[ID_GT_SAMPLES].value),
            'gt_tolerance': self.el[ID_GT_TOLERANCE].value * 10.0,
            'compact_gt': self.el[ID_COMPACT_GT].value,
        }

    # ------------------------------------------------------------------
    # 求解
    # ------------------------------------------------------------------

    def solve(self, p=None):
        """按当前参数求解几何，返回 (result, error)。"""
        if p is None:
            p = self.read()
        pitch = p['pitch']
        if not pitch or pitch <= 0:
            return None, '节距无效（必须大于 0）'
        fid = p['family']
        if not P.is_implemented(fid):
            return None, ('齿形系列「{0}」的几何求解器尚未实现。\n'
                          '当前支持 HTD 名义尺寸模型和小节距 GT 理论共轭轮槽。'
                          .format((P.family(fid) or {}).get('name', fid)))
        if fid == 'GT':
            if pitch != P.pitch_mm(p['model']):
                return None, 'GT 理论共轭只接受型号对应的原厂节距，不能按比例缩放'
            fixed_count = p.get('gt_sampling_mode') == 'point_count'
            key = (p['model'], p['teeth'],
                   0.001 if fixed_count else p.get('gt_tolerance', 0.001),
                   p.get('gt_samples_per_tooth', 33) if fixed_count else None)
            if key != getattr(self, '_gt_cache_key', None):
                res = GT.solve_groove(*key)
                self._gt_cache_key, self._gt_cache_result = key, res
            res = self._gt_cache_result
            if not res.ok:
                return None, res.message
            if p.get('compact_gt', True):
                try:
                    GT.prepare_smooth_profile(res)
                except (ValueError, ArithmeticError) as error:
                    return None, '连续曲线计算失败：{0}'.format(error)
            res.target_plane, res.center_point = p.get('target_plane'), p.get('center_point')
            return res, ''
        try:
            spec = G.get_htd_spec(pitch)
            r_bt_ratio = p['r_bt_ratio']
            od_drop_val = p['od_drop_ratio'] * pitch
            flank_angle_deg = p['theta_deg']
            # 若参数未做自定义偏离，优先使用标准绝对尺寸
            std_rbt = spec['rb'] / pitch
            std_oddrop = spec['u'] * 2.0
            std_theta = spec.get('beta', 7.0) * 2.0
            if abs(r_bt_ratio - std_rbt) < 1e-10:
                r_bt_ratio = None
            if abs(od_drop_val - std_oddrop) < 1e-10:
                od_drop_val = None
            if abs(flank_angle_deg - std_theta) < 1e-8:
                flank_angle_deg = None

            res = G.solve_groove(
                pitch, p['teeth'],
                clearance=p['clearance_ratio'] * pitch,
                r_bt_ratio=r_bt_ratio,
                flank_angle_deg=flank_angle_deg,
                od_drop=od_drop_val,
                depth_ratio=None if p.get('depth_ratio') == 0 else p.get('depth_ratio'),
                tip_fillet=p.get('tip_fillet'))
        except Exception as err:
            return None, '几何求解异常：{0}'.format(err)
        if not res.ok:
            return None, res.message
        if res is not None:
            res.target_plane = p.get('target_plane')
            res.center_point = p.get('center_point')
        return res, ''

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------

    def update(self, read_only=True):
        """刷新联动状态、数值汇总与预览图。"""
        if self._suppress:
            return
        self._suppress = True
        try:
            self._refresh_enabled()
            self._refresh_text()
        finally:
            self._suppress = False

    def _refresh_enabled(self):
        fid = self.current_family()
        if fid != getattr(self, '_last_family', None):
            self._fill_models(self.el[ID_MODEL], fid)
            self._last_family = fid
        implemented = P.is_implemented(fid)
        self.el[ID_MODEL].isEnabled = implemented and bool(P.model_ids(fid))

        gt_mode = fid == 'GT'
        fixed_count = self.el[ID_GT_SAMPLING].listItems.item(1).isSelected
        for input_id in (ID_GT_SAMPLING, ID_GT_SAMPLES, ID_GT_TOLERANCE, ID_GT_HINT):
            self.el[input_id].isVisible = gt_mode
        self.el[ID_GT_SAMPLING].isEnabled = gt_mode
        self.el[ID_GT_SAMPLES].isEnabled = gt_mode and fixed_count
        self.el[ID_GT_TOLERANCE].isEnabled = gt_mode and not fixed_count
        self.el[ID_COMPACT_GT].isEnabled = gt_mode
        self.el[ID_FALLBACK].isEnabled = not (gt_mode and self.el[ID_COMPACT_GT].value)
        self.el[ID_PITCH_AUTO].isEnabled = not gt_mode
        if gt_mode:
            self.el[ID_PITCH_AUTO].value = True
        for input_id in (ID_RBT, ID_THETA, ID_CLEAR, ID_ODDROP, ID_DEPTH, ID_TIP_FILLET):
            self.el[input_id].isEnabled = implemented and not gt_mode
        pitch_auto = self.el[ID_PITCH_AUTO].value
        self.el[ID_PITCH].isEnabled = not pitch_auto
        if pitch_auto:
            mid = self.current_model()
            p = P.pitch_mm(mid) if mid else None
            if p:
                _set_value_input(self.el[ID_PITCH], '{0:.2f} mm'.format(p), p / 10.0)

        # 齿数范围按型号
        mid = self.current_model()
        m = P.model(fid, mid) if mid else None
        if m:
            zmin = m.get('z_min', 6)
            zmax = m.get('z_max', 400)
            try:
                cur = int(self.el[ID_TEETH].value)
            except Exception:
                cur = 20
            if cur < zmin:
                self.el[ID_TEETH].value = zmin
            elif cur > zmax:
                self.el[ID_TEETH].value = zmax

        # 型号切换联动：自动刷新为当前型号的国标标准推荐值
        if (fid, mid, self.el[ID_PITCH].value) != getattr(self, '_last_spec_key', None):
            p = P.pitch_mm(mid) if pitch_auto and mid else self.el[ID_PITCH].value * 10.0
            if not p:
                try:
                    p = self.el[ID_PITCH].value * 10.0
                except Exception:
                    p = 3.0
            if p and p > 0 and not gt_mode:
                spec = G.get_htd_spec(p)
                _set_value_input(self.el[ID_TIP_FILLET], '{0:.12g} mm'.format(spec['rt']), spec['rt'] / 10.0)
                _set_value_input(self.el[ID_RBT], '{0:.12g}'.format(spec['rb'] / p), spec['rb'] / p)
                _set_value_input(self.el[ID_ODDROP], '{0:.12g}'.format(spec['u'] * 2.0 / p), spec['u'] * 2.0 / p)
                theta_deg = spec.get('beta', 7.0) * 2.0
                _set_value_input(self.el[ID_THETA], '{0:g} deg'.format(theta_deg), math.radians(theta_deg))
            self._last_model_mid = mid
            self._last_spec_key = (fid, mid, self.el[ID_PITCH].value)

    def _refresh_text(self):
        res, err = self.solve()
        self.last_result = res
        self.last_error = err

        if res is None:
            self.el[ID_SUMMARY].text = '无法求解：\n{0}'.format(err)
            self.el[ID_STATS].text = ''
            self.el[ID_WARN].text = ''
            return

        if self.current_family() == 'GT':
            smooth = bool(res.smooth_curves) and self.el[ID_COMPACT_GT].value
            self.el[ID_SUMMARY].text = '\n'.join(
                '{0} = {1} {2}'.format(*row) for row in _gt_rows(res, self.read())[:10])
            self.el[ID_STATS].text = (
                '理论共轭轮槽；无加工间隙，不等同原厂制造槽形\n'
                '每齿 {0} 个插值点；曲线误差上界 {1:g} mm\n'
                '预计写入 {2} 条草图曲线'.format(
                    res.smooth_samples_per_tooth if smooth else res.samples_per_tooth,
                    res.smooth_error_bound if smooth else res.approximation_tolerance,
                    (2 * len(res.smooth_curves) + 1) * res.teeth if smooth else len(G.closed_chain(res))))
            self.el[ID_WARN].text = '\n'.join(res.warnings)
            return

        fit = G.belt_fit(res)
        lines = [
            '节距 p = {0:.4f} mm      齿数 z = {1}'.format(res.pitch, res.teeth),
            '节圆直径 Dp = {0:.4f} mm'.format(res.pitch_diameter),
            '外圆直径 Do = {0:.4f} mm   （= Dp − {1:.4f}）'.format(
                res.outer_diameter, res.pitch_diameter - res.outer_diameter),
            '齿根圆直径 Dr = {0:.4f} mm'.format(res.root_diameter),
            '槽深 h = {0:.4f} mm        齿槽宽 s = {1:.4f} mm'.format(
                res.groove_depth, 2.0 * res.groove_half_width),
            '齿顶宽 = {0:.4f} mm         周节 = {1:.4f} mm'.format(
                res.tip_width, res.pitch),
            '槽底圆弧 R = {0:.4f} mm     齿形角 2β ≈ {1:.1f}°（参考值）'.format(
                res.bottom_arc.radius, res.theta_deg),
            '齿顶倒角 r_t = {0:.4f} mm   节顶距 δ = {1:.4f} mm'.format(
                res.r_tip if res.r_tip is not None else 0.0,
                (res.pitch_diameter - res.outer_diameter) / 2.0),
        ]
        self.el[ID_SUMMARY].text = '\n'.join(lines)

        per_t = len(G.closed_chain(res)) // res.teeth
        self.el[ID_STATS].text = (
            '尺寸参考：齿顶径向间隙 {0:.5f} mm（额外余量 {1:.5f} mm）\n'
            '未作整套标准符合性及动态啮合校核\n'
            '轮廓段数 = {2} （= {3} × 齿数）'.format(
                fit['tip_gap'], res.clearance,
                per_t * res.teeth, per_t))

        warns = list(res.warnings) + [w[1] for w in fit['warnings']]
        if warns:
            self.el[ID_WARN].text = '注意：\n' + '\n'.join(
                '• ' + w for w in warns[:4])
        else:
            self.el[ID_WARN].text = ''

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def validate(self):
        """返回 (ok, message)。包含严谨的数值范围防呆拦截。"""
        for inp in self.el.values():
            if getattr(inp, 'isEnabled', True) and not getattr(inp, 'isValidExpression', True):
                return False, '参数表达式无效：{0}'.format(inp.name)
        p = self.read()
        if not p['sketch_name'] or not p['sketch_name'].strip():
            return False, '草图名称不能为空'

        pitch = p.get('pitch')
        if pitch is None or pitch <= 0:
            return False, '节距必须大于 0 mm'
        if pitch > 200.0:
            return False, '节距过大（已超过 200 mm）'

        teeth = p.get('teeth', 0)
        if teeth < 3:
            return False, '齿数必须至少为 3 齿'
        if teeth > 1000:
            return False, '齿数过大（已超过 1000 齿）'

        if p['family'] == 'GT':
            res, err = self.solve(p)
            return res is not None, err

        clearance = p.get('clearance_ratio', 0.0)
        if clearance < 0:
            return False, '单边间隙系数不能为负数'
        if clearance > 1.0:
            return False, '单边间隙过大（建议在 0.0 ~ 0.3 范围内）'

        od_drop = p.get('od_drop_ratio', 0.0)
        if od_drop < 0:
            return False, '外径收缩系数不能为负数'
        if od_drop > 2.0:
            return False, '外径收缩过大'

        r_bt_ratio = p.get('r_bt_ratio')
        if r_bt_ratio is not None and r_bt_ratio < 0:
            return False, '槽底圆弧半径系数不能为负数'

        theta_deg = p.get('theta_deg', 14.0)
        if theta_deg <= 0 or theta_deg >= 90:
            return False, '齿槽齿形角必须在 0° 到 90° 之间'

        tip_fillet = p.get('tip_fillet', 0.0)
        if tip_fillet < 0:
            return False, '齿顶倒角半径不能为负数'

        res, err = self.solve(p)
        if res is None:
            return False, err

        return True, ''


# ---------------------------------------------------------------------------
# 摘要文本（写入 Fusion 文本命令窗口 / 属性）
# ---------------------------------------------------------------------------

def summary_text(result, opts, messages):
    """生成可粘贴的生成摘要（也用作设计属性）。"""
    if getattr(result, 'profile_chain', None) is not None:
        lines = ['同步带轮生成器 — 生成摘要']
        lines.extend('{0}: {1} {2}'.format(*row) for row in _gt_rows(result, opts))
        lines.append('参数清单')
        lines.extend('  {0} = {1}'.format(k, opts[k]) for k in sorted(opts))
        lines.extend(str(m) for m in messages)
        return '\n'.join(lines)
    fit = G.belt_fit(result)
    lines = []
    lines.append('同步带轮生成器 — 生成摘要')
    lines.append('=' * 46)
    lines.append('齿形系列    : {0}'.format(opts.get('family', '')))
    lines.append('型号        : {0}'.format(opts.get('model', '')))
    lines.append('节距 p      : {0:.4f} mm'.format(result.pitch))
    lines.append('齿数 z      : {0}'.format(result.teeth))
    lines.append('-' * 46)
    lines.append('节圆直径 Dp : {0:.4f} mm'.format(result.pitch_diameter))
    lines.append('外圆直径 Do : {0:.4f} mm'.format(result.outer_diameter))
    lines.append('齿根圆 Dr   : {0:.4f} mm'.format(result.root_diameter))
    lines.append('槽深 h      : {0:.4f} mm'.format(result.groove_depth))
    lines.append('齿顶宽      : {0:.4f} mm'.format(result.tip_width))
    lines.append('-' * 46)
    lines.append('带齿顶圆弧  : {0:.4f} mm'.format(result.r_bt))
    lines.append('带齿侧圆弧  : {0:.4f} mm'.format(result.r_bf))
    lines.append('槽底圆弧 R  : {0:.4f} mm'.format(
        result.bottom_arc.radius if result.bottom_arc else 0.0))
    lines.append('齿顶倒角 rt : {0:.4f} mm'.format(
        result.r_tip if result.r_tip is not None else 0.0))
    lines.append('齿槽齿形角  : ≈{0:.1f}°（参考值）'.format(result.theta_deg))
    lines.append('-' * 46)
    lines.append('单边间隙    : {0:.4f} mm'.format(result.clearance))
    lines.append('齿顶间隙    : {0:.5f} mm'.format(fit['tip_gap']))
    lines.append('尺寸比较    : 槽底+{0:.5f} 圆心位移{1:.5f} 齿侧半径+{2:.5f}'
                 .format(fit['bottom_excess'], fit['center_shift'],
                         fit['flank_radius_excess']))
    lines.append('校核范围    : 名义尺寸比较，不含完整齿廓干涉或动态啮合')
    for warning in result.warnings:
        lines.append('提示        : ' + warning)
    lines.append('-' * 46)
    lines.append('参数清单')
    for k in sorted(opts.keys()):
        lines.append('  {0:<18}= {1}'.format(k, opts[k]))
    if messages:
        lines.append('-' * 46)
        lines.append('处理信息')
        for m in messages:
            lines.append('  ' + m)
    return '\n'.join(lines)


def param_rows(result, opts):
    """返回参数表（供 CSV/表格导出）。"""
    if getattr(result, 'profile_chain', None) is not None:
        return _gt_rows(result, opts)
    fit = G.belt_fit(result)
    rows = [
        ('齿形系列', opts.get('family', ''), ''),
        ('型号', opts.get('model', ''), ''),
        ('节距', '{0:.6f}'.format(result.pitch), 'mm'),
        ('齿数', str(result.teeth), ''),
        ('节圆直径', '{0:.6f}'.format(result.pitch_diameter), 'mm'),
        ('外圆直径', '{0:.6f}'.format(result.outer_diameter), 'mm'),
        ('齿根圆直径', '{0:.6f}'.format(result.root_diameter), 'mm'),
        ('槽深', '{0:.6f}'.format(result.groove_depth), 'mm'),
        ('槽口宽', '{0:.6f}'.format(2.0 * result.groove_half_width), 'mm'),
        ('齿顶宽', '{0:.6f}'.format(result.tip_width), 'mm'),
        ('带齿顶圆弧半径', '{0:.6f}'.format(result.r_bt), 'mm'),
        ('带齿侧圆弧半径', '{0:.6f}'.format(result.r_bf), 'mm'),
        ('槽底圆弧半径', '{0:.6f}'.format(
            result.bottom_arc.radius if result.bottom_arc else 0.0), 'mm'),
        ('槽侧圆弧半径', '{0:.6f}'.format(
            result.flank_arc.radius if result.flank_arc else 0.0), 'mm'),
        ('单边间隙', '{0:.6f}'.format(result.clearance), 'mm'),
        ('齿顶间隙', '{0:.6f}'.format(fit['tip_gap']), 'mm'),
        ('槽底圆弧半径差', '{0:.6f}'.format(fit['bottom_excess']), 'mm'),
        ('槽底圆心偏移量', '{0:.6f}'.format(fit['center_shift']), 'mm'),
        ('齿侧圆弧超出量', '{0:.6f}'.format(fit['flank_radius_excess']), 'mm'),
        ('齿侧角', '{0:.4f}'.format(result.theta_deg), 'deg'),
        ('齿顶倒角半径', '{0:.6f}'.format(result.r_tip), 'mm'),
        ('外径收缩系数', '{0:.6f}'.format(result.od_drop / result.pitch), ''),
        ('齿顶圆弧系数', '{0:.6f}'.format(result.r_bt_ratio), ''),
        ('校核范围', '仅名义尺寸比较，未作完整啮合校核', ''),
    ]
    return rows


def _gt_rows(result, opts):
    """GT 只报告实际计算量，不套用 HTD 带齿/圆弧校核指标。"""
    smooth = bool(result.smooth_curves) and opts.get('compact_gt', True)
    return [
        ('齿形系列', 'GT 理论共轭', ''),
        ('型号', opts.get('model', ''), ''),
        ('节距', '{0:.6f}'.format(result.pitch), 'mm'),
        ('齿数', str(result.teeth), ''),
        ('节圆直径', '{0:.6f}'.format(result.pitch_diameter), 'mm'),
        ('外圆直径', '{0:.6f}'.format(result.outer_diameter), 'mm'),
        ('齿根圆直径', '{0:.6f}'.format(result.root_diameter), 'mm'),
        ('槽深', '{0:.6f}'.format(result.groove_depth), 'mm'),
        ('齿顶外圆弧长', '{0:.6f}'.format(result.tip_width), 'mm'),
        ('节线差', '{0:.6f}'.format(result.od_drop / 2.0), 'mm'),
        ('加工间隙', '0（理论模型）', 'mm'),
        ('采样方式', '指定点数' if result.sampling_mode == 'point_count' else '按误差自动', ''),
        ('曲线类型', 'C2 连续三次 NURBS' if smooth else '采样折线', ''),
        ('每齿插值点数', result.smooth_samples_per_tooth if smooth else result.samples_per_tooth, ''),
        ('曲线误差上界', '{0:.9f}'.format(
            result.smooth_error_bound if smooth else result.approximation_tolerance), 'mm'),
        ('采样折线及外圆段数', len(G.closed_chain(result)), ''),
        ('计算方法', str(result.standard_note), ''),
        ('资料来源', str(result.source), ''),
        ('适用限制', '理论共轭；未包含原厂制造公差或动态变形补偿', ''),
    ]


def write_csv(path, rows):
    """导出参数表为 CSV（UTF-8 BOM，便于 Excel 打开）。"""
    with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(('参数', '数值', '单位'))
        writer.writerows(rows)
    return path
