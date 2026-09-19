# -*- coding: utf-8 -*-
"""
干跑测试（用 Fusion API 桩离线执行）
====================================

在没有安装 Fusion 的环境里，用 tests/fusion_stub.py 提供的 API 桩
**真实执行** ui.py / sketch.py / 插件入口的代码路径，用于发现：

    * API 误用（方法名/参数个数/返回类型）
    * 单位换算错误
    * 参数联动与校验逻辑缺陷
    * 草图几何退化（三点共线、零长度直线、非正半径）

    python tests/test_dryrun.py
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, 'lib'))
sys.path.insert(0, _HERE)

import fusion_stub                       # noqa: E402

fusion_stub.install()

import adsk.core                        # noqa: E402
import adsk.fusion                      # noqa: E402

from tpg import geometry as G           # noqa: E402
from tpg import profiles as P           # noqa: E402
from tpg import sketch as SK            # noqa: E402
from tpg import ui as UI                # noqa: E402

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


app = adsk.core.Application.get()
ui = app.userInterface
design = adsk.fusion.Design()
app.activeProduct = design


# ---------------------------------------------------------------------------
# 1. 草图生成干跑
# ---------------------------------------------------------------------------

def test_handler_resolution():
    """回归测试：某些 Fusion 版本没有 adsk.core.EventHandler 基类。

    本插件的 _resolve_handler_type() 必须靠事件注解反射拿到正确的
    handler 基类，而不是依赖 EventHandler。
    """
    print('\n[0] handler 基类反射解析')

    # 前提：桩故意不提供通用 EventHandler（复现真实故障环境）
    check('桩未提供 EventHandler（复现故障环境）',
          not hasattr(adsk.core, 'EventHandler'),
          'Event跳存在，无法验证反射路径')

    root = os.path.dirname(_HERE)
    sys.path.insert(0, root)
    if 'TimingPulleyGenerator' in sys.modules:
        del sys.modules['TimingPulleyGenerator']
    import TimingPulleyGenerator as TPG

    cases = [
        (adsk.core.CommandCreatedEvent(), 'CommandCreatedEventHandler'),
        (adsk.core.CommandEvent(), 'CommandEventHandler'),
        (adsk.core.InputChangedEvent(), 'InputChangedEventHandler'),
        (adsk.core.ValidateInputsEvent(), 'ValidateInputsEventHandler'),
    ]
    for ev, expect in cases:
        got = TPG._resolve_handler_type(ev)
        check('解析 {0} -> {1}'.format(type(ev).__name__, expect),
              got is not None and got.__name__ == expect,
              'got={0}'.format(got))

    # 通用 Event（无注解）应退回 EventHandler / None，且不抛异常
    generic = adsk.core.Event()
    got = TPG._resolve_handler_type(generic)
    check('无注解事件安全退回（不抛异常）', True, 'got={0}'.format(got))

    # 实际上必须能注册成功并触发
    fired = []
    ev = adsk.core.CommandEvent()
    h = TPG._make_handler(ev, lambda a: fired.append(1), 'test')
    check('handler 注册成功', h is not None)
    ev.fire(_ExecArgs())
    check('注册的 handler 可被触发', fired == [1], str(fired))


def test_sketch_build():
    print('\n[1] 草图生成干跑')
    comp = design.rootComponent

    cases = [
        ('2M', 20, 'plain', dict()),
        ('3M', 24, 'plain', dict()),
        ('5M', 20, 'plain', dict()),
        ('5M', 20, 'offset_center', dict(center=(15.0, 25.0))),
        ('5M', 20, 'center_point', dict(center_point=adsk.fusion.SketchPoint(adsk.core.Point3D.create(1.0, 2.0, 0.0)))),
        ('5M', 20, 'outercircle', dict(draw_outer_circle=True)),
        ('8M', 30, 'cx_cy', dict(cx=10.0, cy=-20.0)),
        ('14M', 40, 'plain', dict()),
        ('20M', 30, 'plain', dict()),
    ]

    for mid, z, tag, extra in cases:
        m = P.model('HTD', mid)
        res = G.solve_groove(m['pitch_mm'], z)
        if not res.ok:
            check('求解 {0} z={1}'.format(mid, z), False, res.message)
            continue

        opts = {'sketch_name': '轮-{0}-{1}'.format(mid, z), 'replace': True,
                'draw_pitch_circle': True, 'draw_root_circle': True,
                'draw_outer_circle': False, 'labels': False,
                'sampled_fallback': True}
        opts.update(extra)

        label = '{0}-{1}T/{2}'.format(mid, z, tag)
        try:
            out = SK.build(comp, res, opts)
        except Exception as err:
            import traceback
            check('草图 ' + label, False,
                  '{0}\n{1}'.format(err, traceback.format_exc()))
            continue

        sk = out['sketch']
        n_curves = len(sk._arcs) + len(sk._lines)
        per_tooth = len(G.closed_chain(res)) // z
        expect = per_tooth * z
        check('草图 {0} 轮廓段数 = {1}z'.format(label, per_tooth), n_curves == expect,
              '{0} vs {1}'.format(n_curves, expect))
        check('草图 {0} 无异常信息'.format(label),
              all('失败' not in m_ for m_ in out['messages']),
              str(out['messages']))

        # 所有圆弧半径为正
        bad_r = [a for a in sk._arcs if a.radius is None or a.radius <= 0]
        check('草图 {0} 圆弧半径全为正'.format(label), not bad_r,
              '异常 {0} 段'.format(len(bad_r)))

        # 构造圆
        cons = [c for c in sk._circles if c.isConstruction]
        check('草图 {0} 构造圆存在'.format(label), len(cons) >= 2,
              '{0} 个'.format(len(cons)))

        # 固定约束（绿色全锁定）
        check('草图 {0} 全部圆弧已固定(isFixed)'.format(label),
              all(a.isFixed for a in sk._arcs))
        check('草图 {0} 全部直线已固定(isFixed)'.format(label),
              all(l.isFixed for l in sk._lines))
        check('草图 {0} 全部圆已固定(isFixed)'.format(label),
              all(c.isFixed for c in sk._circles))

        # 尺寸量级检查（cm）
        if sk._arcs:
            rmax = max(a.radius for a in sk._arcs if a.radius)
            ok_scale = rmax < res.outer_radius * 2.0
            check('草图 {0} 单位换算正确(≤cm级)'.format(label), ok_scale,
                  'max r={0:.4f}'.format(rmax))

        print('  {0:<22} 曲线={1:>4}  构造圆={2}  圆心=({3:.1f},{4:.1f})  轮廓={5}'.format(
            label, n_curves, len(cons), out['center'][0], out['center'][1],
            out['profile_count']))

    # 测试指定圆心偏移
    res5m = G.solve_groove(5.0, 20)
    out_shift = SK.build(comp, res5m, {'sketch_name': 'SHIFT', 'replace': True, 'center': (12.0, 34.0)})
    check('圆心偏移 (12.0, 34.0) 记录正确', out_shift['center'] == (12.0, 34.0))

    # 测试槽口理论宽构造线（用于测量 1.90mm 等标称尺寸）
    res3m = G.solve_groove(3.0, 20)
    out_mouth = SK.build(comp, res3m, {'sketch_name': 'MOUTH', 'replace': True, 'draw_mouth_line': True})
    mouth_cons = [l for l in out_mouth['sketch']._lines if l.isConstruction]
    check('绘制槽口理论宽构造线成功', len(mouth_cons) >= 1)

    # 测试已有草图绑定
    target_sk = comp.sketches.add(comp.xYConstructionPlane)
    out_target = SK.build(comp, res5m, {'target_plane': target_sk, 'center': (0.0, 0.0)})
    check('已有草图绑定成功', out_target['sketch'] is target_sk)

    # 同名替换
    before = comp.sketches.count
    res = G.solve_groove(5.0, 20)
    SK.build(comp, res, {'sketch_name': 'DUP', 'replace': True})
    SK.build(comp, res, {'sketch_name': 'DUP', 'replace': True})
    after = comp.sketches.count
    check('同名草图替换不累积', after - before == 1,
          '新增 {0} 个'.format(after - before))

    # 不替换时应自动改名
    SK.build(comp, res, {'sketch_name': 'KEEP', 'replace': False})
    SK.build(comp, res, {'sketch_name': 'KEEP', 'replace': False})
    names = [comp.sketches.item(i).name for i in range(comp.sketches.count)]
    check('不替换时自动改名', names.count('KEEP') == 1 and
          any(n.startswith('KEEP (') for n in names), str(names[-3:]))


# ---------------------------------------------------------------------------
# 2. 标注文字干跑
# ---------------------------------------------------------------------------

def test_labels():
    print('\n[2] 标注文字')
    comp = design.rootComponent
    res = G.solve_groove(5.0, 20)
    out = SK.build(comp, res, {'sketch_name': 'LBL', 'replace': True,
                               'draw_pitch_circle': False,
                               'draw_root_circle': False})
    n = SK.draw_labels(out['sketch'], SK.label_items(res, {}))
    check('标注文字写入成功', n > 0, '写入 {0} 条'.format(n))
    print('  写入 {0} 条标注'.format(n))


# ---------------------------------------------------------------------------
# 3. 对话框干跑
# ---------------------------------------------------------------------------

class _FakeInputs(object):
    """模拟 CommandInputs：记录所有创建的输入控件。"""

    #: 需要拒绝的图片目录前缀（用于测试候选目录回退）
    reject_image_dirs = ()

    def __init__(self):
        self.items = {}
        self._seq = 0

    def _reg(self, obj):
        self.items[obj.id] = obj
        return obj

    def addTabCommandInput(self, i, n, rf=''):
        t = _Tab(i, n)
        self._seq += 1
        t.children = _FakeInputs()
        self._seq += 1
        self.items[i] = t
        return t

    def addValueInput(self, i, n, u, v):
        return self._reg(_Value(i, n, u, v))

    def addSelectionInput(self, i, n, prompt):
        return self._reg(_Selection(i, n, prompt))

    def addBoolValueInput(self, i, n, cb, rf='', init=False):
        return self._reg(_Bool(i, n, init))

    def addStringValueInput(self, i, n, init=''):
        return self._reg(_Str(i, n, init))

    def addIntegerSpinnerCommandInput(self, i, n, lo, hi, step, init):
        return self._reg(_Int(i, n, init, lo, hi))

    def addDropDownCommandInput(self, i, n, style):
        return self._reg(_Drop(i, n))

    def addTextBoxCommandInput(self, i, n, t, rows, ro):
        return self._reg(_Text(i, n, t))

    def addSeparatorCommandInput(self, i):
        return self._reg(_Sep(i))

    def addImageCommandInput(self, i, n, f):
        # 真实 Fusion 会校验路径：空串或不存在都会抛
        #   RuntimeError: invalid argument imageFile
        if not f:
            raise RuntimeError('3 : invalid argument imageFile')
        if not os.path.isfile(f):
            raise RuntimeError('3 : invalid argument imageFile '
                               '(not found: {0})'.format(f))
        # 模拟"某些目录被 Fusion 拒绝"（例如路径含非 ASCII 字符）
        af = os.path.abspath(f).lower()
        for bad in _FakeInputs.reject_image_dirs:
            if bad and af.startswith(os.path.abspath(bad).lower()):
                raise RuntimeError('3 : invalid argument imageFile '
                                   '(rejected dir: {0})'.format(bad))
        return self._reg(_Img(i, n, f))


class _Base(object):
    def __init__(self, i, n):
        self.id = i
        self.name = n
        self.isEnabled = True
        self.isVisible = True


class _Tab(_Base):
    def __init__(self, i, n):
        _Base.__init__(self, i, n)
        self.children = None


class _Value(_Base):
    def __init__(self, i, n, u, v):
        _Base.__init__(self, i, n)
        self.unitType = u
        self.isValidExpression = True
        val = v.value if hasattr(v, 'value') else v
        if isinstance(val, str):
            val = val.strip()
            if val.endswith('deg'):
                self._v = math.radians(float(val[:-3].strip()))
            elif val.endswith('rad'):
                self._v = float(val[:-3].strip())
            elif val.endswith('mm'):
                self._v = float(val[:-2].strip()) / 10.0
            elif val.endswith('cm'):
                self._v = float(val[:-2].strip())
            else:
                self._v = float(val)
        else:
            self._v = float(val)

    @property
    def value(self):
        return self._v

    @value.setter
    def value(self, v):
        if hasattr(v, 'kind') or isinstance(v, getattr(adsk.core, 'ValueInput', ())):
            raise TypeError('Fusion 360 ValueCommandInput.value expects a float/double in database units, not ValueInput!')
        self._v = float(v)

    @property
    def expression(self):
        return str(self._v)

    @expression.setter
    def expression(self, val):
        if isinstance(val, str):
            val = val.strip()
            if val.endswith('deg'):
                self._v = math.radians(float(val[:-3].strip()))
            elif val.endswith('rad'):
                self._v = float(val[:-3].strip())
            elif val.endswith('mm'):
                self._v = float(val[:-2].strip()) / 10.0
            elif val.endswith('cm'):
                self._v = float(val[:-2].strip())
            else:
                self._v = float(val)
        else:
            self._v = float(val)


class _Bool(_Base):
    def __init__(self, i, n, init):
        _Base.__init__(self, i, n)
        self.value = bool(init)


class _Str(_Base):
    def __init__(self, i, n, init):
        _Base.__init__(self, i, n)
        self.value = init


class _Int(_Base):
    def __init__(self, i, n, init, lo, hi):
        _Base.__init__(self, i, n)
        self._v = int(init)
        self.minimumValue = lo
        self.maximumValue = hi

    @property
    def value(self):
        return self._v

    @value.setter
    def value(self, v):
        v = int(v)
        if v < self.minimumValue or v > self.maximumValue:
            raise ValueError('齿数 {0} 超出范围 [{1},{2}]'.format(
                v, self.minimumValue, self.maximumValue))
        self._v = v


class _DropItem(object):
    def __init__(self, name, selected):
        self.name = name
        self.isSelected = selected


class _DropItems(object):
    def __init__(self):
        self._l = []

    def add(self, name, selected=False):
        self._l.append(_DropItem(name, selected))

    def clear(self):
        self._l = []

    @property
    def count(self):
        return len(self._l)

    def item(self, i):
        return self._l[i]


class _Drop(_Base):
    def __init__(self, i, n):
        _Base.__init__(self, i, n)
        self.listItems = _DropItems()

    @property
    def selectedItem(self):
        for it in self.listItems._l:
            if it.isSelected:
                return it
        return self.listItems._l[0] if self.listItems._l else None


class _Text(_Base):
    def __init__(self, i, n, t):
        _Base.__init__(self, i, n)
        self.text = t
        self.isReadOnly = True


class _Sep(_Base):
    def __init__(self, i, n=''):
        _Base.__init__(self, i, n)


class _Img(_Base):
    def __init__(self, i, n, image_file=''):
        _Base.__init__(self, i, n)
        # 真实 Fusion：创建时就绑定该图片路径
        self.imageFile = image_file
        self.isFullWidth = False


class _Selection(_Base):
    def __init__(self, i, n, prompt):
        _Base.__init__(self, i, n)
        self.commandPrompt = prompt
        self.filters = []
        self.minLimit = 0
        self.maxLimit = 0
        self._selections = []

    def addSelectionFilter(self, f):
        self.filters.append(f)

    def setSelectionLimits(self, lower, upper=0):
        self.minLimit = lower
        self.maxLimit = upper

    @property
    def selectionCount(self):
        return len(self._selections)

    def selection(self, index):
        return self._selections[index]

    def clearSelection(self):
        self._selections = []

    def addSelection(self, entity):
        import adsk.core
        sel = getattr(adsk.core, 'Selection', None)
        if sel:
            self._selections.append(sel(entity))
        else:
            class _S(object):
                def __init__(self, e):
                    self.entity = e
            self._selections.append(_S(entity))


def _collect(inp, out):
    for k, v in inp.items.items():
        out[k] = v
        if isinstance(v, _Tab) and v.children is not None:
            _collect(v.children, out)


def test_dialog():
    print('\n[3] 对话框干跑')
    inputs = _FakeInputs()
    dlg = UI.Dialog(design)
    dlg.create(inputs)

    allitems = {}
    _collect(inputs, allitems)
    check('对话框创建成功', len(allitems) > 15,
          '控件数 {0}'.format(len(allitems)))

    # 各页签存在（基本参数、齿槽几何、输出选项、结果与预览，共 4 个）
    tabs = [v for v in allitems.values() if isinstance(v, _Tab)]
    check('页签数量 = 4', len(tabs) == 4, '{0}'.format(len(tabs)))

    # 装配式两级选择器检查
    check('放置平面选择控件存在', UI.ID_TARGET_PLANE in allitems)
    check('圆心点选择控件存在', UI.ID_CENTER_POINT in allitems)
    check('放置平面过滤器正确', 'PlanarFaces' in allitems[UI.ID_TARGET_PLANE].filters and
          'Sketches' in allitems[UI.ID_TARGET_PLANE].filters)
    check('圆心点过滤器正确', 'SketchPoints' in allitems[UI.ID_CENTER_POINT].filters and
          'CircularEdges' in allitems[UI.ID_CENTER_POINT].filters)

    # 齿顶倒角控件检查
    check('齿顶倒角控件存在', UI.ID_TIP_FILLET in allitems)

    # 默认应为 HTD 且选中第一个可用型号（2M），显式选定 5M 后验证
    def select_model(mid):
        dd = allitems[UI.ID_MODEL]
        for it in dd.listItems._l:
            it.isSelected = (it.name == mid)

    select_model('5M')
    dlg.update()

    check('5M 齿顶倒角默认推荐 0.50mm', abs(allitems[UI.ID_TIP_FILLET].value * 10.0 - 0.50) < 1e-4)

    p = dlg.read()
    check('切换型号后参数正确', p['model'] == '5M' and p['pitch'] == 5.0,
          str({k: p[k] for k in ('pitch', 'teeth', 'model')}))
    check('读取参数包含 tip_fillet', abs(p['tip_fillet'] - 0.50) < 1e-4)

    # 选面选圆心测试
    fake_face = 'FakePlanarFace'
    fake_pt = adsk.fusion.SketchPoint(adsk.core.Point3D.create(1.0, 2.0, 0.0))
    allitems[UI.ID_TARGET_PLANE].addSelection(fake_face)
    allitems[UI.ID_CENTER_POINT].addSelection(fake_pt)
    p_sel = dlg.read()
    check('选择放置平面读取正确', p_sel['target_plane'] == fake_face)
    check('选择圆心点读取正确', p_sel['center_point'] is fake_pt)
    allitems[UI.ID_TARGET_PLANE].clearSelection()
    allitems[UI.ID_CENTER_POINT].clearSelection()

    res, err = dlg.solve(p)
    check('5M 默认参数可解', res is not None, err)
    if res:
        check('5M-20T 尺寸正确',
              abs(res.pitch_diameter - 31.8310) < 0.01 and
              abs(res.outer_diameter - 30.6880) < 0.01,
              'Dp={0:.4f} Do={1:.4f}'.format(res.pitch_diameter,
                                             res.outer_diameter))

    # 校验通过
    ok, msg = dlg.validate()
    check('默认参数校验通过', ok, msg)

    # 汇总文本非空且含关键数值
    summary = allitems[UI.ID_SUMMARY].text
    check('汇总文本包含节圆直径', '31.83' in summary, summary[:80])
    check('汇总文本包含外圆直径', '30.68' in summary or '30.69' in summary, summary[:80])
    stats = allitems[UI.ID_STATS].text
    check('啮合校核文本存在', '间隙' in stats, stats[:60])

    # 界面必须**不含任何图片控件**：ImageCommandInput 在部分 Fusion 环境下
    # 会抛 "invalid argument imageFile" 并导致整个参数界面构建失败，
    # 因此本插件已彻底弃用该控件（及其所有相关代码）。
    imgs = [v for v in allitems.values() if isinstance(v, _Img)]
    check('界面不含图片控件', not imgs,
          '仍有 {0} 个图片控件'.format(len(imgs)))

    # --- 切换型号 ---
    for mid, pitch, zmin in (('2M', 2.0, 10), ('8M', 8.0, 10), ('20M', 20.0, 14)):
        dd = allitems[UI.ID_MODEL]
        for it in dd.listItems._l:
            it.isSelected = (it.name == mid)
        try:
            dlg.update()
        except Exception as err:
            check('切换到 {0}'.format(mid), False, str(err))
            continue
        p = dlg.read()
        res, err = dlg.solve(p)
        check('切换到 {0} 可解'.format(mid),
              res is not None and abs(res.pitch - pitch) < 1e-9, err)
        print('  {0:<6} 节距={1:<6g} 齿数={2:<4} Dp={3:.3f}'.format(
            mid, p['pitch'], p['teeth'],
            res.pitch_diameter if res else float('nan')))

    # 验证 8M 齿顶倒角推荐为 0.80mm
    dd = allitems[UI.ID_MODEL]
    for it in dd.listItems._l:
        it.isSelected = (it.name == '8M')
    dlg.update()
    check('8M 齿顶倒角联动推荐 0.80mm', abs(allitems[UI.ID_TIP_FILLET].value * 10.0 - 0.80) < 1e-4)

    # --- 齿数越界 ---
    for it in dd.listItems._l:
        it.isSelected = (it.name == '2M')
    dlg.update()
    try:
        allitems[UI.ID_TEETH].value = 5        # 低于 2M 的 z_min=10
        check('齿数越界被拒绝', False, '未抛错')
    except ValueError:
        check('齿数越界被拒绝', True)

    # --- 关闭节距自动 ---
    allitems[UI.ID_PITCH_AUTO].value = False
    dlg.update()
    check('关闭自动后节距可编辑', allitems[UI.ID_PITCH].isEnabled)
    allitems[UI.ID_PITCH].value = 0.75         # 7.5 mm
    dlg.update()
    p = dlg.read()
    check('自定义节距读取正确', abs(p['pitch'] - 7.5) < 1e-9,
          'pitch={0}'.format(p['pitch']))
    res, err = dlg.solve(p)
    check('自定义节距可解', res is not None, err)
    if res:
        print('  自定义节距 7.5mm z={0} Dp={1:.3f}'.format(
            p['teeth'], res.pitch_diameter))

    # --- 非法节距 ---
    allitems[UI.ID_PITCH].value = 0.0
    dlg.update()
    ok, msg = dlg.validate()
    check('节距 0 校验失败', not ok, '竟然通过')
    allitems[UI.ID_PITCH].value = 0.5
    dlg.update()

    # --- 非法/未知系列应被拒绝 ---
    p_bad = dlg.read()
    p_bad['family'] = 'UNKNOWN_FAMILY'
    res, err = dlg.solve(p_bad)
    check('未知系列给出明确提示', res is None and '不支持' in err, str(err))

    # --- 间隙极端值 ---
    allitems[UI.ID_CLEAR].value = 0.5          # 过小 -> 应拒绝
    dlg.update()
    res, err = dlg.solve()
    check('过小间隙被拒绝', res is None, '竟然可解')
    allitems[UI.ID_CLEAR].value = 0.05
    dlg.update()
    res, err = dlg.solve()
    check('标准间隙可解', res is not None, err)

    # --- 空草图名 ---
    allitems[UI.ID_SKETCH_NAME].value = '   '
    dlg.update()
    ok, msg = dlg.validate()
    check('空草图名校验失败', not ok, '竟然通过')
    allitems[UI.ID_SKETCH_NAME].value = '同步带轮'


# ---------------------------------------------------------------------------
# 4. 摘要与导出
# ---------------------------------------------------------------------------

def test_preview_dir_fallback():
    """回归测试：Fusion 拒绝某个候选目录时，预览控件仍能创建。

    真机曾报 "invalid argument imageFile"（即使 PNG 本身合法），
    怀疑与路径有关。插件因此准备了多个候选目录并逐个尝试。
    """
    print('\n[3b] 预览目录回退')
    inputs = _FakeInputs()

    # 先算出插件会优先使用哪个目录，然后把它整段拒掉
    probe = UI.Dialog(design)
    first = probe._img_dirs[0] if probe._img_dirs else None
    check('存在多个候选预览目录', len(probe._img_dirs) >= 2,
          str(probe._img_dirs))
    if not first:
        return

    _FakeInputs.reject_image_dirs = (first,)
    try:
        dlg = UI.Dialog(design)
        try:
            dlg.create(inputs)
        except Exception as err:
            check('首个目录被拒时仍能构建界面', False, str(err))
            return
        check('首个目录被拒时仍能构建界面', True)

        allitems = {}
        _collect(inputs, allitems)
        img = allitems.get(UI.ID_IMG)
        check('预览控件仍被创建', img is not None)
        if img is not None:
            used = os.path.abspath(img.imageFile).lower()
            check('预览图来自被接受的其他目录',
                  not used.startswith(os.path.abspath(first).lower()),
                  'used={0}'.format(img.imageFile))
            check('预览图文件存在且非空',
                  os.path.isfile(img.imageFile) and
                  os.path.getsize(img.imageFile) > 500,
                  str(img.imageFile))
            print('  首个目录被拒 -> 回退到: {0}'.format(
                os.path.dirname(img.imageFile)))
    finally:
        _FakeInputs.reject_image_dirs = ()


def test_no_image_control():
    """回归测试：整个参数界面不得使用图片控件。

    真机曾连续多次因 ``addImageCommandInput`` 抛
    "invalid argument imageFile" 导致界面构建失败（空路径、路径被拒、
    图片被拒等情形）。**该控件及其全部相关代码已被彻底删除。**

    本测试用"对所有图片调用都抛异常"的极端桩，验证界面依然能构建。
    """
    print('\n[3c] 无图片控件回归')

    class _HostileInputs(_FakeInputs):
        def addImageCommandInput(self, i, n, f):
            raise RuntimeError('3 : invalid argument imageFile')

    inputs = _HostileInputs()
    dlg = UI.Dialog(design)
    try:
        dlg.create(inputs)
    except Exception as err:
        check('图片 API 全部失败时界面仍能构建', False, str(err))
        return
    check('图片 API 全部失败时界面仍能构建', True)

    allitems = {}
    _collect(inputs, allitems)
    check('界面控件齐全（>15）', len(allitems) > 15,
          str(len(allitems)))
    check('未创建任何图片控件',
          not [v for v in allitems.values() if isinstance(v, _Img)],
          '出现了图片控件')

    # 参数联动仍正常
    dd = allitems[UI.ID_MODEL]
    for it in dd.listItems._l:
        it.isSelected = (it.name == '5M')
    dlg.update()
    res, err = dlg.solve()
    check('参数联动仍可解', res is not None, err)


def test_hot_reload():
    """回归测试：热重载必须真的从磁盘重新读取代码。

    背景：Fusion 会缓存已导入的 Python 模块，卸载插件（Stop）不会清掉。
    结果是改了源码却仍执行旧代码，甚至新旧模块混用导致 traceback 行号与
    源码对不上 —— 这曾让人误判问题所在。入口的 ``_reload_lib()`` 负责
    在每次启动时从磁盘重载，本测试验证它确实生效。

    做法：临时修改 lib 下某个模块的源码（一个常量），调用 _reload_lib()，
    确认读到的值变了，然后还原文件。
    """
    print('\n[6] 热重载')

    root = os.path.dirname(_HERE)
    sys.path.insert(0, root)
    if 'TimingPulleyGenerator' in sys.modules:
        del sys.modules['TimingPulleyGenerator']
    import TimingPulleyGenerator as TPG

    from tpg import profiles as _P
    orig_path = _P.__file__
    if orig_path.endswith('.pyc'):
        orig_path = orig_path[:-1]
    with open(orig_path, 'r', encoding='utf-8') as fh:
        orig_src = fh.read()

    marker_old = "PITCH_TABLE_MM = {"
    marker_new = "PITCH_TABLE_MM = {  # __hot_reload_probe__"
    check('测试锚点存在于 profiles.py', marker_old in orig_src
          and marker_new not in orig_src, '锚点异常')
    if marker_old not in orig_src:
        return

    try:
        # 1) 修改磁盘源码
        with open(orig_path, 'w', encoding='utf-8') as fh:
            fh.write(orig_src.replace(marker_old, marker_new, 1))

        # 2) 触发重载
        TPG._reload_lib()

        # 3) 新模块应包含改动
        with open(orig_path, 'r', encoding='utf-8') as fh:
            disk = fh.read()
        check('磁盘源码确实已改动', marker_new in disk)

        # 4) 重载后 tpg.profiles 是**新**模块对象
        import importlib
        fresh = importlib.import_module('tpg.profiles')
        check('重载后模块已更新', 'tpg.profiles' in sys.modules)
        check('重载后模块取自磁盘（非旧缓存）',
              getattr(fresh, '__file__', '') .endswith('profiles.py'),
              str(getattr(fresh, '__file__', None)))

        # 5) 关键：旧模块对象不再被 sys.modules 引用（确已替换）
        check('sys.modules 指向新生模块', sys.modules['tpg.profiles'] is fresh)

        # 6) 通过**新模块**执行，验证功能正常
        #（注意：不能用 TPG.G —— 测试里的本地名字仍指向重载前的旧对象，
        #  这正是"新旧模块混用"的典型陷阱，入口内部靠 _reload_lib 的
        #  global 赋值来避免。）
        gmod = importlib.import_module('tpg.geometry')
        check('通过 sys.modules 取到的是新生几何模块',
              gmod is sys.modules['tpg.geometry'])
        res = gmod.solve_groove(5.0, 20)
        check('重载后几何可解', res.ok, getattr(res, 'message', ''))
        check('重载后尺寸正确',
              abs(res.pitch_diameter - 31.8310) < 0.01,
              '{0:.4f}'.format(res.pitch_diameter))

        # 7) 入口暴露了版本号，便于确认加载的是哪个版本
        check('入口模块含版本号', bool(getattr(TPG, '__version__', '')),
              str(getattr(TPG, '__version__', None)))
        check('库版本号可读', bool(getattr(TPG, 'LIB_VERSION', '')),
              str(getattr(TPG, 'LIB_VERSION', None)))
        print('  插件 v{0} / 库 v{1}'.format(
            getattr(TPG, '__version__', '?'), getattr(TPG, 'LIB_VERSION', '?')))
    finally:
        with open(orig_path, 'w', encoding='utf-8') as fh:
            fh.write(orig_src)
        TPG._reload_lib()
        # 确认已还原
        with open(orig_path, 'r', encoding='utf-8') as fh:
            check('源码已还原', marker_new not in fh.read())


def test_selfheal_retry():
    """回归测试：首次构建界面失败时，应自动从磁盘重载并重建成功。

    真机曾出现「点了运行但 Fusion 仍执行内存里的旧代码」的情况 ——
    traceback 行号与源码对不上，改了源码也无效。现在
    ``_on_command_created`` 在首次构建失败后会调用 ``_reload_lib()``
    并重试一次，实现自愈，无需用户重启 Fusion。
    """
    print('\n[7] 失败自愈重试')

    root = os.path.dirname(_HERE)
    sys.path.insert(0, root)
    if 'TimingPulleyGenerator' in sys.modules:
        del sys.modules['TimingPulleyGenerator']
    import TimingPulleyGenerator as TPG

    # 让第一次 create() 抛异常，第二次（重载后）成功
    state = {'n': 0}

    class _FlakyInputs(_FakeInputs):
        def __init__(self):
            _FakeInputs.__init__(self)

    # 让**首次**构建失败。
    # 注意：必须打在 TPG.UI 上 —— 重载会替换 sys.modules 里的模块对象，
    # 所以第一次失败后，第二次会走全新的（未打桩的）Dialog.create 并成功。
    # 这正是"新旧模块混用"陷阱，也是本插件要解决的问题。
    target_UI = TPG.UI
    orig_create = target_UI.Dialog.create
    calls = {'n': 0}

    def flaky_create(self, inputs):
        calls['n'] += 1
        raise RuntimeError('3 : invalid argument imageFile（模拟首次构建失败）')

    target_UI.Dialog.create = flaky_create

    # 同时记录 _reload_lib 是否被调用（它会被重载替换，所以先包一层）
    orig_reload = TPG._reload_lib
    reload_calls = {'n': 0}

    def counting_reload():
        reload_calls['n'] += 1
        return orig_reload()

    TPG._reload_lib = counting_reload
    try:
        ui.msgbox_calls = []
        args = _CmdCreatedArgs()
        TPG._on_command_created(args)

        check('首次构建确实失败了（打桩生效）', calls['n'] >= 1,
              'create 被调用 {0} 次'.format(calls['n']))
        check('触发了从磁盘重载', reload_calls['n'] >= 1,
              'reload 被调用 {0} 次'.format(reload_calls['n']))
        check('重载后界面构建成功',
              TPG._dialog is not None and len(TPG._dialog.el) > 10,
              '控件数 {0}'.format(len(TPG._dialog.el)
                                  if TPG._dialog else 0))
        check('弹出了更新提示', any('自动重新加载' in m
                                    for m in ui.msgbox_calls),
              str(ui.msgbox_calls[:2]))
        print('  首次失败 {0} 次 -> 重载 {1} 次 -> 控件数 {2}'.format(
            calls['n'], reload_calls['n'],
            len(TPG._dialog.el) if TPG._dialog else 0))
    finally:
        target_UI.Dialog.create = orig_create
        TPG._reload_lib = orig_reload


def test_export():
    print('\n[4] 摘要与参数导出')
    res = G.solve_groove(5.0, 20)
    opts = {'family': 'HTD', 'model': '5M', 'teeth': 20}
    text = UI.summary_text(res, opts, ['测试信息'])
    check('摘要包含关键尺寸',
          '节圆直径' in text and '31.83' in text and '外圆直径' in text,
          text[:120])
    check('摘要包含参数清单', '参数清单' in text)
    print('  摘要 {0} 行'.format(len(text.splitlines())))

    rows = UI.param_rows(res, opts)
    check('参数表行数 >= 15', len(rows) >= 15, '{0}'.format(len(rows)))
    path = os.path.join(_HERE, 'out', 'params_5M20T.csv')
    out = UI.write_csv(path, rows)
    check('CSV 导出成功', os.path.isfile(out) and os.path.getsize(out) > 100,
          out)


# ---------------------------------------------------------------------------
# 5. 插件入口干跑
# ---------------------------------------------------------------------------

def test_entrypoint():
    print('\n[5] 插件入口干跑')
    root = os.path.dirname(_HERE)
    sys.path.insert(0, root)
    if 'TimingPulleyGenerator' in sys.modules:
        del sys.modules['TimingPulleyGenerator']
    try:
        import TimingPulleyGenerator as TPG
    except Exception as err:
        import traceback
        check('导入插件入口', False,
              '{0}\n{1}'.format(err, traceback.format_exc()))
        return

    try:
        TPG.run(None)
    except Exception as err:
        import traceback
        check('run() 执行', False,
              '{0}\n{1}'.format(err, traceback.format_exc()))
        return
    check('run() 执行成功', True)

    cmd = ui.commandDefinitions.itemById(TPG.CMD_ID)
    check('命令定义已创建', cmd is not None)
    if cmd:
        check('命令按钮已加入面板', not cmd.deleted)

    ws = ui.workspaces.itemById(TPG.WORKSPACE_ID)
    solid_p = ws.toolbarPanels.itemById('SolidCreatePanel')
    sketch_p = ws.toolbarPanels.itemById('SketchCreatePanel')
    check('SolidCreatePanel 包含按钮', solid_p is not None and solid_p.controls.itemById(TPG.CMD_ID) is not None)
    check('SketchCreatePanel 包含按钮', sketch_p is not None and sketch_p.controls.itemById(TPG.CMD_ID) is not None)

    # 触发命令创建事件
    if cmd:
        try:
            args = _CmdCreatedArgs()
            cmd.commandCreated.fire(args)
            check('commandCreated 事件处理成功', True)
            collected = {}
            _collect(args.command.inputs, collected)
            check('对话框构建后控件数 > 15', len(collected) > 15,
                  str(len(collected)))
        except Exception as err:
            import traceback
            check('commandCreated 事件处理成功', False,
                  '{0}\n{1}'.format(err, traceback.format_exc()))
            args = None

        # 测试草图模式下自动绑定激活草图
        active_sk = design.rootComponent.sketches.add(design.rootComponent.xYConstructionPlane)
        app.activeEditObject = active_sk
        try:
            args_active = _CmdCreatedArgs()
            cmd.commandCreated.fire(args_active)
            check('草图模式下自动绑定激活草图',
                  TPG._dialog is not None and
                  TPG._dialog.el[UI.ID_TARGET_PLANE].selectionCount == 1 and
                  TPG._dialog.el[UI.ID_TARGET_PLANE].selection(0).entity is active_sk)
        finally:
            app.activeEditObject = None

        # --- 触发 execute：完整生成路径 ---
        # 重新触发一次干净的 commandCreated，确保不残留前面测试选择的 active_sk
        args = _CmdCreatedArgs()
        cmd.commandCreated.fire(args)
        if args is not None:
            ui.msgbox_calls = []
            before = design.rootComponent.sketches.count
            try:
                args.command.execute.fire(_ExecArgs())
                after = design.rootComponent.sketches.count
                check('execute 事件处理成功', True)
                check('execute 生成了草图', after > before,
                      '新增 {0} 个'.format(after - before))
                check('execute 未弹出错误框',
                      not any('失败' in m or '出错' in m for m in ui.msgbox_calls),
                      str(ui.msgbox_calls[:2]))
                if ui.msgbox_calls:
                    print('  执行反馈: {0}'.format(
                        ui.msgbox_calls[0].splitlines()[0]))
                # 最后一张草图应含 4z 或 6z 段圆弧 (5M-20T 标准齿顶倒角 0.50mm 为 80 段)
                sk = design.rootComponent.sketches.item(after - 1)
                check('execute 草图圆弧段数正确', len(sk._arcs) in (80, 100, 120, 140),
                      '{0}'.format(len(sk._arcs)))
                check('execute 草图圆弧全部添加固定约束', all(a.isFixed for a in sk._arcs))
                check('execute 草图构造圆全部添加固定约束', all(c.isFixed for c in sk._circles))
            except Exception as err:
                import traceback
                check('execute 事件处理成功', False,
                      '{0}\n{1}'.format(err, traceback.format_exc()))

    # stop
    try:
        TPG.stop(None)
        check('stop() 执行成功', True)
    except Exception as err:
        import traceback
        check('stop() 执行成功', False,
              '{0}\n{1}'.format(err, traceback.format_exc()))

    check('stop() 后命令定义已删除',
          ui.commandDefinitions.itemById(TPG.CMD_ID) is None)
    if solid_p:
        check('stop() 后 SolidCreatePanel 命令按钮已删除',
              solid_p.controls.itemById(TPG.CMD_ID) is None)
    if sketch_p:
        check('stop() 后 SketchCreatePanel 命令按钮已删除',
              sketch_p.controls.itemById(TPG.CMD_ID) is None)


class _CmdCreatedArgs(object):
    def __init__(self):
        self.command = _Cmd()


class _ExecArgs(object):
    """模拟 CommandEventArgs（execute / destroy 事件）。"""

    def __init__(self):
        self.isCanceled = False
        self.executeFailed = False
        self.terminationReason = 'CompletedTerminationReason'


class _Cmd(object):
    def __init__(self):
        self.commandInputs = _FakeInputs()
        self.inputs = self.commandInputs
        self.isExecutedWhenPreEmpted = True
        # 用带 handler 类型注解的具体事件类，贴合真实 Fusion
        self.execute = adsk.core.CommandEvent()
        self.inputChanged = adsk.core.InputChangedEvent()
        self.validateInputs = adsk.core.ValidateInputsEvent()
        self.destroy = adsk.core.CommandEvent()
        self.executePreview = adsk.core.CommandEvent()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print('=' * 78)
    print('同步带轮生成器 — 干跑测试（Fusion API 桩）')
    print('=' * 78)

    out_dir = os.path.join(_HERE, 'out')
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    test_handler_resolution()
    test_sketch_build()
    test_labels()
    test_dialog()
    test_no_image_control()
    test_export()
    test_hot_reload()
    test_selfheal_retry()
    test_entrypoint()

    print('\n' + '=' * 78)
    print('通过 {0} 项，失败 {1} 项'.format(len(PASS), len(FAIL)))
    if FAIL:
        print('\n失败明细:')
        for f in FAIL[:30]:
            print('  x ' + f)
        return 1
    print('全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
