# -*- coding: utf-8 -*-
"""
Fusion API 桩（测试用）
======================

在纯 Python 下模拟 ``adsk.core`` / ``adsk.fusion`` 的最小可用子集，
用于**离线执行** ui.py / sketch.py / 插件入口的代码路径，
在没有 Fusion 的环境里发现 API 误用、参数类型错误、逻辑缺陷。

    python tests/test_dryrun.py

桩只实现被测代码真正用到的接口；未实现的会抛错并打印调用位置，
便于定位问题。
"""

import math
import sys
import types


# ---------------------------------------------------------------------------
# adsk.core
# ---------------------------------------------------------------------------

def _install_core():
    core = types.ModuleType('adsk.core')

    class Point3D(object):
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x, self.y, self.z = float(x), float(y), float(z)

        @staticmethod
        def create(x, y, z):
            return Point3D(x, y, z)

        def __repr__(self):
            return 'P(%.4f,%.4f,%.4f)' % (self.x, self.y, self.z)

    class Vector3D(object):
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x, self.y, self.z = x, y, z

    class ValueInput(object):
        def __init__(self, kind, value):
            self.kind = kind
            self.value = value

        @staticmethod
        def createByReal(v):
            return ValueInput('real', float(v))

        @staticmethod
        def createByString(s):
            return ValueInput('string', s)

    class _EventHandler(object):
        def notify(self, args):
            pass

    class Event(object):
        def __init__(self):
            self._hs = []

        def add(self, handler):
            self._hs.append(handler)
            return True

        def remove(self, handler):
            if handler in self._hs:
                self._hs.remove(handler)
            return True

        def fire(self, args=None):
            for h in list(self._hs):
                h.notify(args)

    # --- 具体事件类型：add 带 handler 类型注解 ---
    # 说明：真实 Fusion 的 Event.add 带 `handler: XxxEventHandler` 注解，
    # 官方示例靠它做反射。这里同样加上注解，使干跑测试能真正走反射分支；
    # 同时**故意不提供** EventHandler 基类，以复现某些 Fusion 版本
    # "module 'adsk.core' has no attribute 'EventHandler'" 的情形。

    class _TypedEvent(Event):
        pass

    def _typed_event(name, handler_name):
        """动态创建一个带注解 add 的事件类。"""

        def add(self, handler):
            return Event.add(self, handler)
        add.__annotations__ = {'handler': handler_name}
        cls = type(name, (_TypedEvent,), {'add': add})
        return cls

    class CommandCreatedEventHandler(object):
        def __init__(self):
            pass

        def notify(self, args):
            pass

    class CommandEventHandler(object):
        def __init__(self):
            pass

        def notify(self, args):
            pass

    class InputChangedEventHandler(object):
        def __init__(self):
            pass

        def notify(self, args):
            pass

    class ValidateInputsEventHandler(object):
        def __init__(self):
            pass

        def notify(self, args):
            pass

    class CommandCreatedEvent(_typed_event('CommandCreatedEvent',
                                           'CommandCreatedEventHandler')):
        pass

    class CommandEvent(_typed_event('CommandEvent',
                                    'CommandEventHandler')):
        pass

    class InputChangedEvent(_typed_event('InputChangedEvent',
                                         'InputChangedEventHandler')):
        pass

    class ValidateInputsEvent(_typed_event('ValidateInputsEvent',
                                           'ValidateInputsEventHandler')):
        pass

    core.CommandCreatedEvent = CommandCreatedEvent
    core.CommandEvent = CommandEvent
    core.InputChangedEvent = InputChangedEvent
    core.ValidateInputsEvent = ValidateInputsEvent
    core.CommandCreatedEventHandler = CommandCreatedEventHandler
    core.CommandEventHandler = CommandEventHandler
    core.InputChangedEventHandler = InputChangedEventHandler
    core.ValidateInputsEventHandler = ValidateInputsEventHandler
    # 注意：不定义 core.EventHandler —— 复现真实运行时的缺失情况

    class Base(object):
        @staticmethod
        def cast(obj):
            return obj

    class DropDownStyles(object):
        TextListDropDownStyle = 'TextList'
        LabeledIconDropDownStyle = 'LabeledIcon'
        CheckBoxDropDownStyle = 'CheckBox'

    class UserInterfaceThemes(object):
        DarkBlueUserInterfaceTheme = 'dark'
        LightGrayUserInterfaceTheme = 'light'

    class HorizontalAlignments(object):
        LeftHorizontalAlignment = 'left'
        CenterHorizontalAlignment = 'center'
        RightHorizontalAlignment = 'right'

    class VerticalAlignments(object):
        BottomVerticalAlignment = 'bottom'
        MiddleVerticalAlignment = 'middle'
        TopVerticalAlignment = 'top'

    class DialogResults(object):
        DialogOK = 1

    class Selection(object):
        def __init__(self, entity):
            self.entity = entity

    class SelectionCommandInput(object):
        def __init__(self, cid, name, commandPrompt):
            self.id = cid
            self.name = name
            self.commandPrompt = commandPrompt
            self.filters = []
            self.minLimit = 0
            self.maxLimit = 0
            self._selections = []
            self.isEnabled = True
            self.isVisible = True

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
            self._selections.append(Selection(entity))

    class NurbsCurve3D(object):
        @staticmethod
        def createNonRational(controlPoints, degree, knots, isPeriodic):
            if (degree != 3 or isPeriodic or len(controlPoints) < 4 or
                    len(knots) != len(controlPoints) + degree + 1 or
                    any(a > b for a, b in zip(knots, knots[1:]))):
                raise ValueError('Invalid non-rational NURBS definition')
            curve = NurbsCurve3D()
            curve.controlPoints = list(controlPoints)
            curve.degree = degree
            curve.knots = list(knots)
            return curve

    core.NurbsCurve3D = NurbsCurve3D
    core.Point3D = Point3D
    core.Vector3D = Vector3D
    core.ValueInput = ValueInput
    core.Event = Event
    core.Selection = Selection
    core.SelectionCommandInput = SelectionCommandInput
    # 注意：**故意不提供** core.EventHandler ——
    # 某些 Fusion 版本没有这个通用基类（实测报
    # "module 'adsk.core' has no attribute 'EventHandler'"），
    # 这里复现该环境，强制插件走"按事件注解反射"的正确路径。
    core.Base = Base
    core.DropDownStyles = DropDownStyles
    core.UserInterfaceThemes = UserInterfaceThemes
    core.HorizontalAlignments = HorizontalAlignments
    core.VerticalAlignments = VerticalAlignments
    core.DialogResults = DialogResults
    core.Application = _application_class()
    return core


def _application_class():
    class Application(object):
        _inst = None

        def __init__(self):
            self.userInterface = _ui_singleton()
            self.activeProduct = None
            self.preferences = _prefs_singleton()
            self.activeViewport = _viewport_singleton()

        @staticmethod
        def get():
            if Application._inst is None:
                Application._inst = Application()
            return Application._inst

    return Application


_UI = {}


def _ui_singleton():
    if 'ui' not in _UI:
        _UI['ui'] = UserInterface()
    return _UI['ui']


_PREFS = {}


def _prefs_singleton():
    if 'p' not in _PREFS:
        class _GP(object):
            activeUserInterfaceTheme = 'dark'

        class _Prefs(object):
            generalPreferences = _GP()
        _PREFS['p'] = _Prefs()
    return _PREFS['p']


_VIEWPORT = {}


def _viewport_singleton():
    if 'v' not in _VIEWPORT:
        class _VP(object):
            def fit(self):
                pass
        _VIEWPORT['v'] = _VP()
    return _VIEWPORT['v']


class UserInterface(object):
    """记录所有被创建的 UI 对象，便于断言。"""

    def __init__(self):
        self.commandDefinitions = _CommandDefinitions()
        self.workspaces = _Workspaces()
        self.messages = []
        self.msgbox_calls = []

    def messageBox(self, text, *a, **k):
        self.msgbox_calls.append(text)
        self.messages.append(text)

    def createCloudFolderDialog(self):
        raise NotImplementedError('createCloudFolderDialog')


class _CommandDefinitions(object):
    def __init__(self):
        self._d = {}

    def itemById(self, cid):
        return self._d.get(cid)

    def addButtonDefinition(self, cid, name, tooltip, resource_folder=''):
        d = CommandDefinition(cid, name, tooltip, resource_folder)
        d._owner = self
        self._d[cid] = d
        return d

    def _remove(self, cid):
        self._d.pop(cid, None)


class CommandDefinition(object):
    def __init__(self, cid, name, tooltip, folder):
        self.id = cid
        self.name = name
        self.tooltip = tooltip
        self.resourceFolder = folder
        self.commandCreated = _Core_event('CommandCreatedEvent',
                                          'CommandCreatedEventHandler')
        self.toolClipFilename = ''
        self.deleted = False
        self._owner = None

    def deleteMe(self):
        # 模拟 Fusion：从 CommandDefinitions 集合中移除
        self.deleted = True
        if self._owner is not None:
            self._owner._remove(self.id)


def _Core_event(ev_name=None, handler_name=None):
    """取一个带注解的具体事件实例；未指定时退回通用 Event。"""
    import adsk.core as core
    if ev_name:
        cls = getattr(core, ev_name, None)
        if cls is not None:
            return cls()
    return core.Event()


class _Workspaces(object):
    def __init__(self):
        self._w = {}

    def itemById(self, wid):
        if wid not in self._w:
            self._w[wid] = Workspace(wid)
        return self._w[wid]


class Workspace(object):
    def __init__(self, wid):
        self.id = wid
        self.toolbarPanels = _ToolbarPanels()


class _ToolbarPanels(object):
    def __init__(self):
        self._p = {}

    def itemById(self, pid):
        if pid not in self._p:
            self._p[pid] = ToolbarPanel(pid)
        return self._p[pid]


class ToolbarPanel(object):
    def __init__(self, pid):
        self.id = pid
        self.controls = _Controls()


class _Control(object):
    def __init__(self, cid, parent):
        self.id = cid
        self._parent = parent
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        if self.id in self._parent._c:
            del self._parent._c[self.id]


class _Controls(object):
    def __init__(self):
        self._c = {}

    def addCommand(self, cmd_def, *a, **k):
        ctrl = _Control(cmd_def.id, self)
        self._c[cmd_def.id] = ctrl
        return ctrl

    def itemById(self, cid):
        return self._c.get(cid)


# ---------------------------------------------------------------------------
# adsk.fusion
# ---------------------------------------------------------------------------

def _install_fusion():
    import adsk.core as _core
    Base = _core.Base
    fusion = types.ModuleType('adsk.fusion')

    class DesignIntentTypes(object):
        PartDesignIntentType = 'part'
        AssemblyDesignIntentType = 'assembly'
        HybridDesignIntentType = 'hybrid'

    class FeatureOperations(object):
        NewBodyFeatureOperation = 'new'
        JoinFeatureOperation = 'join'
        CutFeatureOperation = 'cut'

    class ExtentDirections(object):
        PositiveExtentDirection = 'pos'
        NegativeExtentDirection = 'neg'

    class PatternComputeOptions(object):
        IdenticalPatternCompute = 'identical'

    # --- 草图几何 -----------------------------------------------------
    class SketchEntity(object):
        def __init__(self):
            self.isConstruction = False
            self.isFixed = False

    class SketchPoint(SketchEntity):
        def __init__(self, geom):
            SketchEntity.__init__(self)
            self.worldGeometry = geom
            self.geometry = geom

    class SketchCurve(SketchEntity):
        def __init__(self):
            SketchEntity.__init__(self)
            self.startSketchPoint = None
            self.endSketchPoint = None
            self._collection = None
            self.isValid = True

        def deleteMe(self):
            if self._collection is not None and self in self._collection:
                self._collection.remove(self)
            self.isValid = False
            return True

    class SketchArc(SketchCurve):
        def __init__(self, p0, p1, p2):
            SketchCurve.__init__(self)
            self.p0, self.p1, self.p2 = p0, p1, p2
            self.startSketchPoint = SketchPoint(p0)
            self.endSketchPoint = SketchPoint(p2)
            # 用三点定圆校验共线性（退化圆弧会被 Fusion 拒绝）
            self.radius, self.center = _circumcircle(p0, p1, p2)

    class SketchCircle(SketchCurve):
        def __init__(self, center, radius):
            SketchCurve.__init__(self)
            self.center = center
            self.radius = radius
            self.startSketchPoint = SketchPoint(center)
            self.centerSketchPoint = SketchPoint(center)

    class SketchLine(SketchCurve):
        def __init__(self, p0, p1):
            SketchCurve.__init__(self)
            self.startSketchPoint = SketchPoint(p0)
            self.endSketchPoint = SketchPoint(p1)
            self.length = _dist(p0, p1)

    class SketchFixedSpline(SketchCurve):
        def __init__(self, geometry):
            SketchCurve.__init__(self)
            self.geometry = geometry
            self.isFixed = True
            self.startSketchPoint = SketchPoint(geometry.controlPoints[0])
            self.endSketchPoint = SketchPoint(geometry.controlPoints[-1])

    class _Coll(object):
        def __init__(self, items=None):
            self._i = list(items or [])

        @property
        def count(self):
            return len(self._i)

        def item(self, i):
            return self._i[i]

        def __len__(self):
            return len(self._i)

        def __getitem__(self, i):
            return self._i[i]

        def __iter__(self):
            return iter(self._i)

        def add(self, x):
            self._i.append(x)

        def clear(self):
            self._i = []

    class SketchArcs(object):
        def __init__(self, sketch):
            self._s = sketch

        def __iter__(self):
            return iter(self._s._arcs)

        @property
        def count(self):
            return len(self._s._arcs)

        def item(self, i):
            return self._s._arcs[i]

        def addByThreePoints(self, p0, p1, p2):
            a = SketchArc(p0, p1, p2)
            if a.radius is None:
                raise ValueError('三点共线，无法构造圆弧: %r %r %r' % (p0, p1, p2))
            a._collection = self._s._arcs
            self._s._arcs.append(a)
            return a

        def addByCenterStartSweep(self, c, s, sweep):
            a = SketchArc(c, s, s)
            a._collection = self._s._arcs
            self._s._arcs.append(a)
            return a

    class SketchCircles(object):
        def __init__(self, sketch):
            self._s = sketch

        def __iter__(self):
            return iter(self._s._circles)

        @property
        def count(self):
            return len(self._s._circles)

        def item(self, i):
            return self._s._circles[i]

        def addByCenterRadius(self, c, r):
            if r <= 0:
                raise ValueError('圆半径必须为正，得到 %r' % r)
            cc = SketchCircle(c, r)
            cc._collection = self._s._circles
            self._s._circles.append(cc)
            return cc

    class SketchLines(object):
        def __init__(self, sketch):
            self._s = sketch

        def __iter__(self):
            return iter(self._s._lines)

        @property
        def count(self):
            return len(self._s._lines)

        def item(self, i):
            return self._s._lines[i]

        def addByTwoPoints(self, p0, p1):
            if _dist(p0, p1) < 1e-12:
                raise ValueError('零长度直线: %r %r' % (p0, p1))
            ln = SketchLine(p0, p1)
            ln._collection = self._s._lines
            self._s._lines.append(ln)
            return ln

    class SketchFixedSplines(object):
        def __init__(self, sketch):
            self._s = sketch

        def addByNurbsCurve(self, curve):
            spline = SketchFixedSpline(curve)
            spline._collection = self._s._splines
            self._s._splines.append(spline)
            return spline

    class _Curves(object):
        def __init__(self, sketch):
            self.sketchArcs = SketchArcs(sketch)
            self.sketchCircles = SketchCircles(sketch)
            self.sketchLines = SketchLines(sketch)
            self.sketchFixedSplines = SketchFixedSplines(sketch)

    class SketchTextInput(object):
        def __init__(self, expr, height):
            self.expression = expr
            self.height = height

        def setAsMultiLine(self, corner, diagonal, hAlign, vAlign, spacing):
            self.corner = corner
            self.diagonal = diagonal
            return True

    class SketchTexts(object):
        def __init__(self, sketch):
            self._s = sketch

        def createInput3(self, expr, height):
            if not (expr.startswith("'") and expr.endswith("'")):
                raise ValueError(
                    'SketchTexts.createInput3 的表达式必须用单引号括起：%r' % expr)
            if not isinstance(height, _core.ValueInput):
                raise TypeError(
                    'SketchTexts.createInput3 的 height 必须为 ValueInput，得到：%r' % (type(height),))
            return SketchTextInput(expr, height)

        def add(self, inp):
            self._s._texts.append(inp)
            return inp

    class Profile(object):
        def __init__(self, loops):
            self.profileLoops = _Coll(loops)

    class GeometricConstraint(object):
        def __init__(self, entity):
            self.entity = entity

    class GeometricConstraints(object):
        def __init__(self, sketch):
            self._s = sketch
            self._constraints = []

    class Profiles(object):
        """粗略模拟 Fusion 的轮廓识别。

        真实 Fusion 会从闭合曲线求解 Profile。这里做简化推断：
        若草图里存在 4×n 或 6×n 段的闭合圆弧链，则认为有 1 个主轮廓；
        若另有轴孔圆（且键槽），再各加 1。
        仅用于让上层代码走通"profiles.count"分支。
        """

        def __init__(self, sketch):
            self._s = sketch

        @property
        def count(self):
            sk = self._s
            total_curves = len(sk._arcs) + len(sk._lines) + len(sk._splines)
            if total_curves < 12:
                return 0
            n = 1
            # 轴孔：非构造圆
            n += len([c for c in sk._circles if not c.isConstruction])
            return n

        def item(self, i):
            return Profile([])

    class Sketch(Base):
        def __init__(self, name=''):
            self.name = name
            self.owner = None
            self._arcs = []
            self._circles = []
            self._lines = []
            self._splines = []
            self._texts = []
            self.isComputeDeferred = False
            self.sketchCurves = _Curves(self)
            self.sketchTexts = SketchTexts(self)
            self.geometricConstraints = GeometricConstraints(self)
            self.profiles = Profiles(self)
            self.isValid = True

        @property
        def sketchPoints(self):
            pts = []
            for a in self._arcs:
                if getattr(a, 'startSketchPoint', None):
                    pts.append(a.startSketchPoint)
                if getattr(a, 'endSketchPoint', None):
                    pts.append(a.endSketchPoint)
            for c in self._circles:
                if getattr(c, 'centerSketchPoint', None):
                    pts.append(c.centerSketchPoint)
            for l in self._lines:
                if getattr(l, 'startSketchPoint', None):
                    pts.append(l.startSketchPoint)
                if getattr(l, 'endSketchPoint', None):
                    pts.append(l.endSketchPoint)
            return _Coll(pts)

        def modelToSketchSpace(self, pt):
            return _core.Point3D.create(pt.x, pt.y, 0.0)

        def deleteMe(self):
            # 模拟 Fusion：从所属 Sketches 集合中移除
            self.isValid = False
            if self.owner is not None:
                self.owner._remove(self)

    class Sketches(object):
        def __init__(self, comp):
            self._c = comp
            self._items = []

        @property
        def count(self):
            return len(self._items)

        def item(self, i):
            return self._items[i]

        def add(self, plane):
            sk = Sketch('Sketch%d' % (len(self._items) + 1))
            sk.owner = self
            self._items.append(sk)
            return sk

        def _remove(self, sk):
            if sk in self._items:
                self._items.remove(sk)

    class ConstructionPlane(object):
        pass

    class Component(Base):
        def __init__(self, name='Component'):
            self.name = name
            self.sketches = Sketches(self)
            self.xYConstructionPlane = ConstructionPlane()
            self.occurrences = _Coll()
            self.features = _Features()
            self.parentDesign = None
            self.attributes = _Attributes()

        def __repr__(self):
            return 'Component(%s)' % self.name

    class _Attributes(object):
        def __init__(self):
            self._d = {}

        def itemByName(self, g, n):
            return self._d.get((g, n))

        def add(self, g, n, v):
            a = _Attr(g, n, v)
            self._d[(g, n)] = a
            return a

    class _Attr(object):
        def __init__(self, g, n, v):
            self.groupName = g
            self.name = n
            self.value = v

    class _Features(object):
        pass

    class Design(Base):
        def __init__(self):
            self.rootComponent = Component('Root')
            self.rootComponent.parentDesign = self
            self.attributes = _Attributes()
            self.designIntent = DesignIntentTypes.PartDesignIntentType
            self.timeline = None

        @property
        def unitsManager(self):
            return _UnitsManager()

    class _UnitsManager(object):
        def formatValue(self, value, units='mm', precision=-1, *a, **k):
            return '%.4f %s' % (value, units)

        def convertUnits(self, v, f, t):
            return v

    fusion.Design = Design
    fusion.Component = Component
    fusion.Sketch = Sketch
    fusion.SketchPoint = SketchPoint
    fusion.SketchFixedSpline = SketchFixedSpline
    fusion.SketchCurve = SketchCurve
    fusion.SketchArc = SketchArc
    fusion.SketchCircle = SketchCircle
    fusion.SketchLine = SketchLine
    fusion.ConstructionPlane = ConstructionPlane
    fusion.Profile = Profile
    fusion.GeometricConstraint = GeometricConstraint
    fusion.GeometricConstraints = GeometricConstraints
    fusion.DesignIntentTypes = DesignIntentTypes
    fusion.FeatureOperations = FeatureOperations
    fusion.ExtentDirections = ExtentDirections
    fusion.PatternComputeOptions = PatternComputeOptions
    return fusion


# ---------------------------------------------------------------------------
# 几何工具
# ---------------------------------------------------------------------------

def _dist(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _circumcircle(p0, p1, p2):
    """三点外接圆；共线返回 (None, None)。"""
    ax, ay = p0.x, p0.y
    bx, by = p1.x, p1.y
    cx, cy = p2.x, p2.y
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-18:
        return None, None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    return r, (ux, uy)


def install():
    """把桩模块注册到 sys.modules（必须在 import tpg 之前调用）。"""
    adsk = types.ModuleType('adsk')
    sys.modules['adsk'] = adsk          # 先注册，供 _install_fusion 内部导入
    core = _install_core()
    adsk.core = core
    sys.modules['adsk.core'] = core
    fusion = _install_fusion()
    adsk.fusion = fusion
    sys.modules['adsk.fusion'] = fusion
    return core, fusion
