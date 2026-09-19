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

import adsk.core
import adsk.fusion

from . import geometry as G
from . import profiles as P

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
            dd.listItems.add(f['name'], i == 0)
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
        dd.isEnabled = True
        for i, mid in enumerate(ids):
            dd.listItems.add(mid, i == 0)

    # -- 齿槽几何 -------------------------------------------------------

    def _build_groove(self, inp):
        inp.addTextBoxCommandInput(
            _sid('hint'), '齿槽几何',
            '轮槽 = 带齿廓形的法向等距偏置。以下参数默认取 HTD 标准值，'
            '全部可覆盖。', 3, True)

        mid = self.current_model()
        p = P.pitch_mm(mid) if mid else 3.0
        spec = G.get_htd_spec(p)

        self.el[ID_RBT] = inp.addValueInput(
            ID_RBT, '槽底圆弧半径系数 r_b/p', '',
            adsk.core.ValueInput.createByReal(spec['rb'] / p))
        inp.addTextBoxCommandInput(
            _sid('h'), '', 'JB/T 7512.2 标准值：2M 0.265, 3M 0.303, 5M 0.312, 8M 0.321, 14M 0.332, 20M 0.342。', 1, True)

        self.el[ID_THETA] = inp.addValueInput(
            ID_THETA, '齿槽齿形角 2β（参考值）', 'deg',
            adsk.core.ValueInput.createByString('{0:g} deg'.format(spec.get('beta', 7.0) * 2.0)))
        inp.addTextBoxCommandInput(
            _sid('h'), '', 'JB/T 7512.2 参考值 ≈14°（由标称槽宽 s、槽深与圆弧相切自动求解，通常保持默认）。', 2, True)

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
            '0 表示由标准国标槽深决定（推荐）。', 1, True)

        self.el[ID_TIP_FILLET] = inp.addValueInput(
            ID_TIP_FILLET, '齿顶倒角半径 r_t', 'mm',
            adsk.core.ValueInput.createByString('{0:.2f} mm'.format(spec.get('rt', 0.10 * p))))
        inp.addTextBoxCommandInput(
            _sid('h'), '',
            '标准推荐值（JB/T 7512.2 表1）：2M 0.15, 3M 0.30, 5M 0.50, 8M 0.80, 14M 1.40, 20M 2.00mm。', 1, True)

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

        # 齿侧角: Fusion 内部单位为弧度 (rad)。若值小于 3.2 判定为弧度并转为角度 deg
        raw_theta = self.el[ID_THETA].value
        if isinstance(raw_theta, str):
            s = raw_theta.lower().replace('deg', '').replace('度', '').strip()
            theta_deg = float(s)
        else:
            theta_deg = math.degrees(raw_theta) if abs(raw_theta) < 3.2 else float(raw_theta)

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
            return None, '不支持的齿形系列「{0}」'.format(fid)
        try:
            spec = G.get_htd_spec(pitch)
            r_bt_ratio = p['r_bt_ratio']
            od_drop_val = p['od_drop_ratio'] * pitch
            flank_angle_deg = p['theta_deg']
            # 若参数未做自定义偏离，优先使用标准绝对尺寸
            std_rbt = spec['rb'] / pitch
            std_oddrop = spec['u'] * 2.0
            std_theta = spec.get('beta', 7.0) * 2.0
            if abs(r_bt_ratio - std_rbt) < 5e-3:
                r_bt_ratio = None
            if abs(od_drop_val - std_oddrop) < 5e-3:
                od_drop_val = None
            if abs(flank_angle_deg - std_theta) < 0.1:
                flank_angle_deg = None

            res = G.solve_groove(
                pitch, p['teeth'],
                clearance=p['clearance_ratio'] * pitch,
                r_bt_ratio=r_bt_ratio,
                flank_angle_deg=flank_angle_deg,
                od_drop=od_drop_val,
                depth_ratio=p.get('depth_ratio'),
                tip_fillet=p.get('tip_fillet'))
        except Exception as err:
            return None, '几何求解异常：{0}'.format(err)
        if not res.ok:
            return None, res.message
        if res is not None:
            res.target_plane = p.get('target_plane')
            res.center_point = p.get('center_point')
            res.tip_fillet = p.get('tip_fillet')
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
        implemented = P.is_implemented(fid)
        self.el[ID_MODEL].isEnabled = implemented and bool(P.model_ids(fid))

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
        if mid != getattr(self, '_last_model_mid', None):
            p = P.pitch_mm(mid) if mid else None
            if not p:
                try:
                    p = self.el[ID_PITCH].value * 10.0
                except Exception:
                    p = 3.0
            if p and p > 0:
                spec = G.get_htd_spec(p)
                _set_value_input(self.el[ID_TIP_FILLET], '{0:.2f} mm'.format(spec.get('rt', 0.10 * p)), spec.get('rt', 0.10 * p) / 10.0)
                _set_value_input(self.el[ID_RBT], '{0:.4f}'.format(spec.get('rb', 0.312 * p) / p), spec.get('rb', 0.312 * p) / p)
                _set_value_input(self.el[ID_ODDROP], '{0:.4f}'.format(spec.get('u', 0.1144 * p) * 2.0 / p), spec.get('u', 0.1144 * p) * 2.0 / p)
                theta_deg = spec.get('beta', 7.0) * 2.0
                _set_value_input(self.el[ID_THETA], '{0:g} deg'.format(theta_deg), math.radians(theta_deg))
            self._last_model_mid = mid

    def _refresh_text(self):
        res, err = self.solve()
        self.last_result = res
        self.last_error = err

        if res is None:
            self.el[ID_SUMMARY].text = '无法求解：\n{0}'.format(err)
            self.el[ID_STATS].text = ''
            self.el[ID_WARN].text = ''
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

        per_t = 7 if (res.r_tip is not None and res.r_tip > 1e-9) else 5
        self.el[ID_STATS].text = (
            '啮合校核：齿顶间隙 {0:.5f} mm（设定 {1:.5f} mm）\n'
            '标准符合：JB/T 7512.2 / ISO 13050 直线齿侧平滑相切\n'
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
    lines.append('偏置复核    : 槽底+{0:.5f} 齿侧圆心{1:.5f} 齿侧半径+{2:.5f}'
                 .format(fit['bottom_excess'], fit['center_shift'],
                         fit['flank_radius_excess']))
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
        ('槽底圆弧超出量', '{0:.6f}'.format(fit['bottom_excess']), 'mm'),
        ('齿侧圆心偏移量', '{0:.6f}'.format(fit['center_shift']), 'mm'),
        ('齿侧圆弧超出量', '{0:.6f}'.format(fit['flank_radius_excess']), 'mm'),
        ('齿侧角', '{0:.4f}'.format(result.theta_deg), 'deg'),
        ('齿顶倒角半径', '{0:.6f}'.format(getattr(result, 'tip_fillet', None) or result.r_bf), 'mm'),
        ('外径收缩系数', '{0:.6f}'.format(result.od_drop / result.pitch), ''),
        ('齿顶圆弧系数', '{0:.6f}'.format(result.r_bt_ratio), ''),
    ]
    return rows


def write_csv(path, rows):
    """导出参数表为 CSV（UTF-8 BOM，便于 Excel 打开）。"""
    with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
        fh.write('参数,数值,单位\n')
        for name, value, unit in rows:
            fh.write('{0},{1},{2}\n'.format(name, value, unit))
    return path
