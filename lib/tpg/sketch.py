# -*- coding: utf-8 -*-
"""
Fusion 草图生成
===============

把 geometry.py 算出的几何写成 Fusion 草图。
本模块是**唯一**接触 Fusion API 的几何相关模块，所有计算都在 geometry.py 完成。

单位注意
--------

Fusion 内部长度单位是 **厘米**，而 geometry.py 全部使用 **毫米**。
本模块用 ``MM = 0.1`` 统一换算，所有传入 Fusion 的坐标/半径都已乘过该系数。

草图结构
--------

单个草图包含：

    ┌ 轮齿廓形（真实轮廓，构成可拉伸的闭合 Profile）
    │     每个齿距 7 段（含倒角）：右齿侧线 → 右槽底弧 → 左槽底弧 → 左齿侧线 → 左倒角弧 → 外圆弧 → 右倒角弧
    │     （槽底按标准关于对称轴分为左右两段，在中心最低点形成草图顶点，可精准标注槽深）
    │     整圈 7×齿数 段（无倒角时 5×齿数 段），首尾严格光滑相切闭合
    ├ 节圆          （构造线）
    ├ 齿根圆        （构造线）
    ├ 外圆          （构造线，可选）
    ├ 槽口标称宽线  （构造线，可选）
    └ 齿槽对称中心线（构造线，可选）
"""

import math
import time

import adsk.core
import adsk.fusion

from . import geometry as G
from . import gt as GT

# Fusion 内部长度单位为厘米
MM = 0.1

# 构造几何默认名称前缀
PREFIX_TMP = '__tpg_tmp_'


# ---------------------------------------------------------------------------
# 基础封装
# ---------------------------------------------------------------------------

def _pt(x_mm, y_mm, z_mm=0.0):
    """由毫米坐标构造 Point3D（内部转 cm）。"""
    return adsk.core.Point3D.create(x_mm * MM, y_mm * MM, z_mm * MM)


def _val(v):
    """由毫米数值构造 ValueInput。"""
    return adsk.core.ValueInput.createByReal(v * MM)


def find_sketch(component, name):
    """按名称查找草图；不存在返回 None。"""
    for i in range(component.sketches.count):
        sk = component.sketches.item(i)
        if sk.name == name:
            return sk
    return None


def delete_sketch(sketch):
    """安全删除草图。"""
    try:
        if sketch is not None and sketch.isValid:
            return sketch.deleteMe() is not False
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# 廓形绘制
# ---------------------------------------------------------------------------

def resolve_center_point(sketch, ent):
    """将选中的实体转化为草图平面的 2D 坐标 (cx, cy)（单位 mm）。"""
    if ent is None:
        return 0.0, 0.0
    if isinstance(ent, (tuple, list)) and len(ent) >= 2:
        return float(ent[0]), float(ent[1])
    try:
        pt_world = None
        # SketchCircle/SketchArc.worldGeometry is a Circle3D/Arc3D, not
        # Point3D. Prefer the actual center point, including assembly context.
        if hasattr(ent, 'centerSketchPoint') and ent.centerSketchPoint:
            center = ent.centerSketchPoint
            pt_world = getattr(center, 'worldGeometry', None)
            if pt_world is None:
                pt_world = center.geometry
        elif hasattr(ent, 'worldGeometry'):
            pt_world = ent.worldGeometry
        elif hasattr(ent, 'geometry'):
            pt_world = ent.geometry
        elif hasattr(ent, 'center'):
            pt_world = ent.center

        if hasattr(pt_world, 'center'):
            pt_world = pt_world.center
        if pt_world is not None:
            if hasattr(sketch, 'modelToSketchSpace'):
                pt_sk = sketch.modelToSketchSpace(pt_world)
                return pt_sk.x * 10.0, pt_sk.y * 10.0
            else:
                return getattr(pt_world, 'x', 0.0) * 10.0, getattr(pt_world, 'y', 0.0) * 10.0
    except Exception as err:
        raise ValueError('无法读取所选圆心点：{0}'.format(err))
    raise ValueError('所选实体不包含可用的点或圆心')


def _add_arc(sketch, arc, cx=0.0, cy=0.0):
    """把 geometry.Arc 写入草图，返回 SketchArc。支持圆心偏移 (cx, cy)。"""
    curves = sketch.sketchCurves
    return curves.sketchArcs.addByThreePoints(
        _pt(arc.start[0] + cx, arc.start[1] + cy),
        _pt(arc.mid[0] + cx, arc.mid[1] + cy),
        _pt(arc.end[0] + cx, arc.end[1] + cy))


def _add_line(sketch, line, cx=0.0, cy=0.0):
    """把 geometry.Line 写入草图，返回 SketchLine。支持圆心偏移 (cx, cy)。"""
    curves = sketch.sketchCurves
    return curves.sketchLines.addByTwoPoints(
        _pt(line.start[0] + cx, line.start[1] + cy),
        _pt(line.end[0] + cx, line.end[1] + cy))


def draw_profile(sketch, result, cx=0.0, cy=0.0, created=None):
    """绘制轮齿完整廓形，返回图元数量。

    使用 geometry.closed_chain() 获取已求解的 HTD 或 GT 曲线链。
    """
    chain = G.closed_chain(result)
    n = 0
    for ent in chain:
        if isinstance(ent, G.Arc):
            curve = _add_arc(sketch, ent, cx=cx, cy=cy)
        elif isinstance(ent, G.Line):
            curve = _add_line(sketch, ent, cx=cx, cy=cy)
        else:
            raise TypeError('不支持的轮廓图元：{0}'.format(type(ent).__name__))
        if created is not None:
            created.append(curve)
        n += 1
    return n


def draw_gt_compact(sketch, result, cx=0.0, cy=0.0, created=None):
    """Write C2 analytic-branch approximations with single interior knots.

    Keep genuine branch boundaries and the root vertex, not sampling corners.
    """
    splines = sketch.sketchCurves.sketchFixedSplines
    nurbs_type = adsk.core.NurbsCurve3D
    curves = GT.prepare_smooth_profile(result)
    halves = [(curve.control, curve.knots) for curve in curves]
    halves.extend(([(-x, y) for x, y in reversed(curve.control)],
                   [1 - knot for knot in reversed(curve.knots)])
                  for curve in reversed(curves))
    outer_arcs = G.tip_arcs(result)
    n = 0
    for index in range(result.teeth):
        angle = index * result.pitch_angle
        for control, knots in halves:
            points = [G._rot(point, angle) for point in control]
            nurbs = nurbs_type.createNonRational(
                [_pt(x + cx, y + cy) for x, y in points], 3, knots, False)
            if nurbs is None:
                raise RuntimeError('Fusion 未能创建连续曲线的 NURBS 定义')
            curve = splines.addByNurbsCurve(nurbs)
            if curve is None:
                raise RuntimeError('Fusion 未能创建固定样条')
            if created is not None:
                created.append(curve)
            n += 1
        curve = _add_arc(sketch, outer_arcs[index], cx=cx, cy=cy)
        if created is not None:
            created.append(curve)
        n += 1
    return n


def _begin_batch(component, sketch, is_existing):
    """Defer existing sketches only at their timeline position (Autodesk rule)."""
    before = sketch.isComputeDeferred
    timeline, marker = None, None
    can_defer = not is_existing
    if is_existing and not before:
        design = getattr(component, 'parentDesign', None)
        timeline = getattr(design, 'timeline', None)
        feature = getattr(sketch, 'timelineObject', None)
        if timeline is not None and feature is not None:
            marker = timeline.markerPosition
            try:
                can_defer = feature.rollTo(False) is True
            except Exception:
                timeline.markerPosition = marker
                timeline, marker = None, None
            if not can_defer and timeline is not None:
                timeline.markerPosition = marker
                timeline, marker = None, None
        else:
            timeline = None
    try:
        if can_defer and not before:
            sketch.isComputeDeferred = True
    except Exception:
        if timeline is not None:
            timeline.markerPosition = marker
        raise
    return before, timeline, marker, can_defer and not before


def _end_batch(sketch, state):
    before, timeline, marker, changed = state
    try:
        if changed:
            sketch.isComputeDeferred = before
    finally:
        if timeline is not None:
            timeline.markerPosition = marker


def draw_profile_sampled(sketch, result, tolerance=0.01, cx=0.0, cy=0.0,
                         created=None):
    """退化方案：把廓形离散成折线绘制。

    仅在精确圆弧绘制失败时使用（例如极端参数下圆弧无法闭合）。
    """
    chain = G.closed_chain(result)
    pts = G.sample_chain(chain, tolerance=tolerance)
    if len(pts) < 3:
        return 0
    lines = sketch.sketchCurves.sketchLines
    first = None
    prev = None
    n = 0
    for p in pts:
        cur = _pt(p[0] + cx, p[1] + cy)
        if prev is not None:
            ln = lines.addByTwoPoints(prev, cur)
            if created is not None:
                created.append(ln)
            if first is None:
                first = ln
            n += 1
        prev = cur
    # 闭合
    if first is not None and prev is not None:
        ln = lines.addByTwoPoints(prev, _pt(pts[0][0] + cx, pts[0][1] + cy))
        if created is not None:
            created.append(ln)
        n += 1
    return n


def draw_construction_circles(sketch, result, pitch=True, root=True,
                              outer=False, mouth=False, centerline=False,
                              cx=0.0, cy=0.0, created=None):
    """绘制构造圆与辅助构造线（节圆 / 齿根圆 / 外圆 / 槽口标称宽 / 对称中心线），返回草图曲线列表。

    构造线不参与轮廓，仅供标注与目视检查。
    """
    circles = sketch.sketchCurves.sketchCircles
    lines = sketch.sketchCurves.sketchLines
    out = []
    origin = _pt(cx, cy)

    def remember(curve):
        if created is not None:
            created.append(curve)
        curve.isConstruction = True
        return curve

    if pitch:
        c = remember(circles.addByCenterRadius(origin, result.pitch_radius * MM))
        out.append(('节圆', c))
    if root:
        c = remember(circles.addByCenterRadius(origin, result.groove_lowest * MM))
        out.append(('齿根圆', c))
    if outer:
        c = remember(circles.addByCenterRadius(origin, result.outer_radius * MM))
        out.append(('外圆', c))
    if mouth:
        p_flank_r = getattr(result, 'tip_flank_right', None)
        p_flank_l = getattr(result, 'tip_flank_left', None)
        if p_flank_r is None or p_flank_l is None:
            p_flank_r = getattr(result, 'theoretical_sharp_right', None)
            p_flank_l = getattr(result, 'theoretical_sharp_left', None)
        if p_flank_r is not None and p_flank_l is not None:
            p_l = _pt(p_flank_l[0] + cx, p_flank_l[1] + cy)
            p_r = _pt(p_flank_r[0] + cx, p_flank_r[1] + cy)
            m_line = remember(lines.addByTwoPoints(p_l, p_r))
            out.append(('槽口标称宽构造线', m_line))
    if centerline:
        # 绘制主齿槽对称中心线（沿 Y 轴，穿过原点、槽底中心点与外圆）
        y_low = result.groove_lowest - 1.0
        y_high = result.outer_radius + 1.0
        p_low = _pt(cx, cy + y_low)
        p_high = _pt(cx, cy + y_high)
        c_line = remember(lines.addByTwoPoints(p_low, p_high))
        out.append(('齿槽对称中心线', c_line))
    return out


def _remove_created(created):
    """Remove only this operation's entities, in reverse creation order."""
    failed = []
    for curve in reversed(created):
        try:
            if getattr(curve, 'isValid', True) and curve.deleteMe() is False:
                failed.append(curve)
        except Exception:
            failed.append(curve)
    if failed:
        raise RuntimeError('无法撤销本次添加的 {0} 个草图图元'.format(len(failed)))
    del created[:]


# ---------------------------------------------------------------------------
# 文字标注
# ---------------------------------------------------------------------------

def draw_labels(sketch, items, cx=0.0, cy=0.0):
    """在草图上添加文字标注（尽力而为，失败不影响主流程）。

    items: [(文本, x_mm, y_mm, 字高_mm), ...]

    注意：``SketchTexts.createInput3`` 的第一个参数是表达式（纯文本用单引号括起），
    第二个参数是字高 ValueInput（内部长度单位 cm）。
    """
    texts = sketch.sketchTexts
    made = 0
    for text, x, y, h in items:
        try:
            expr = "'{0}'".format(str(text).replace("'", "''"))
            if hasattr(texts, 'createInput3'):
                inp = texts.createInput3(expr, _val(h))
            else:
                # Before November 2025, createInput2 used a numeric cm height
                # and accepted literal text without enclosing quotes.
                inp = texts.createInput2(str(text), h * MM)
            inp.setAsMultiLine(
                _pt(x + cx, y + cy),
                _pt(x + cx + max(h * 6.0, 1.0), y + cy + h),
                adsk.core.HorizontalAlignments.LeftHorizontalAlignment,
                adsk.core.VerticalAlignments.BottomVerticalAlignment,
                0.0)
            texts.add(inp)
            made += 1
        except Exception:
            pass
    return made


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def build(component, result, opts):
    """在 component 中生成同步带轮草图。

    参数
    ----
    component  adsk.fusion.Component，草图所属组件
    result     geometry.GrooveResult
    opts       dict：
        sketch_name         草图名称
        replace             同名草图是否先删除
        target_plane        放置平面/草图 (PlanarFace / ConstructionPlane / Sketch)，可选
        center_point        圆心点实体，可选
        center / (cx, cy)   圆心偏移 (mm)，可选
        draw_pitch_circle   是否绘制节圆
        draw_root_circle    是否绘制齿根圆
        draw_outer_circle   是否绘制外圆
        labels              是否绘制标注文字
        sampled_fallback    精确圆弧失败时是否退回折线

    返回 dict：{ 'sketch': Sketch, 'arc_count': int, 'profile_count': int,
                'messages': [str], 'ok': bool, 'center': (float, float) }
    """
    messages = []
    started = time.perf_counter()
    timings = {}
    if result is None or not result.ok:
        raise ValueError('无效的齿形求解结果，未修改草图')
    name = opts.get('sketch_name') or '同步带轮'

    target_plane = opts.get('target_plane')
    # Profile cannot be passed to Sketches.add; its parent sketch is usable.
    if target_plane is not None and not hasattr(target_plane, 'sketchCurves'):
        parent_sketch = getattr(target_plane, 'parentSketch', None)
        if parent_sketch is not None:
            target_plane = parent_sketch
    is_existing_sketch = (
        target_plane is not None and (
            isinstance(target_plane, adsk.fusion.Sketch) or
            hasattr(target_plane, 'sketchCurves')
        )
    )

    existing = None
    if is_existing_sketch:
        sketch = target_plane
    else:
        # Build the replacement first; keep the original until success.
        existing = find_sketch(component, name)
        if existing is not None:
            if not opts.get('replace', False):
                base_name = name
                idx = 1
                while find_sketch(component, '{0} ({1})'.format(base_name, idx)):
                    idx += 1
                name = '{0} ({1})'.format(base_name, idx)

        sketches = component.sketches
        plane = target_plane if target_plane is not None else component.xYConstructionPlane
        sketch = sketches.add(plane)
        sketch.name = name

    created = []
    arc_count = 0
    compact_used = False
    smooth_requested = bool(getattr(result, 'half_profile_points', None)) and opts.get('compact_gt', True)
    try:
        # 计算圆心偏移 (cx, cy)
        cx, cy = 0.0, 0.0
        center_arg = opts.get('center')
        if isinstance(center_arg, (tuple, list)) and len(center_arg) >= 2:
            cx, cy = float(center_arg[0]), float(center_arg[1])
        elif 'cx' in opts or 'cy' in opts:
            cx = float(opts.get('cx', 0.0))
            cy = float(opts.get('cy', 0.0))
        elif opts.get('center_point') is not None:
            cx, cy = resolve_center_point(sketch, opts['center_point'])
        if not (math.isfinite(cx) and math.isfinite(cy)):
            raise ValueError('圆心坐标必须是有限数值')

        batch = _begin_batch(component, sketch, is_existing_sketch)
        draw_started = time.perf_counter()
        try:
            try:
                if smooth_requested:
                    try:
                        arc_count = draw_gt_compact(sketch, result, cx=cx, cy=cy, created=created)
                        compact_used = True
                    except Exception as err:
                        _remove_created(created)
                        raise RuntimeError('GT 连续曲线写入失败，已撤销本次生成：{0}'.format(err)) from err
                else:
                    arc_count = draw_profile(sketch, result, cx=cx, cy=cy, created=created)
            except Exception as err:
                if smooth_requested or not opts.get('sampled_fallback', True):
                    raise
                # Remove the incomplete exact chain before drawing fallback.
                _remove_created(created)
                messages.append('精确圆弧绘制失败：{0}'.format(err))
                arc_count = draw_profile_sampled(
                    sketch, result, cx=cx, cy=cy, created=created,
                    tolerance=getattr(result, 'approximation_tolerance', 0.01))
                messages.append('已改用折线近似（{0} 段）'.format(arc_count))

            cons = draw_construction_circles(
                sketch, result,
                pitch=opts.get('draw_pitch_circle', True),
                root=opts.get('draw_root_circle', True),
                outer=opts.get('draw_outer_circle', False),
                mouth=opts.get('draw_mouth_line', False),
                centerline=opts.get('draw_center_line', False),
                cx=cx, cy=cy, created=created)

            # User geometry in an existing sketch must remain editable.
            fixed_spline_type = getattr(adsk.fusion, 'SketchFixedSpline', ())
            for curve in created:
                if isinstance(curve, fixed_spline_type):
                    continue
                try:
                    curve.isFixed = True
                except Exception:
                    pass
        finally:
            timings['draw_seconds'] = time.perf_counter() - draw_started
            compute_started = time.perf_counter()
            _end_batch(sketch, batch)
            timings['compute_seconds'] = time.perf_counter() - compute_started

        profile_started = time.perf_counter()
        profile_count = sketch.profiles.count
        timings['profile_seconds'] = time.perf_counter() - profile_started
        if profile_count == 0:
            raise ValueError('未生成有效轮廓（Profile 数为 0），已撤销本次生成')
        if existing is not None and opts.get('replace', False):
            if not delete_sketch(existing):
                raise RuntimeError('无法覆盖同名草图，已保留原草图')
    except Exception:
        if is_existing_sketch:
            _remove_created(created)
        else:
            delete_sketch(sketch)
        raise

    timings['total_seconds'] = time.perf_counter() - started
    return {
        'ok': profile_count > 0,
        'sketch': sketch,
        'arc_count': arc_count,
        'profile_count': profile_count,
        'messages': messages,
        'construction': cons,
        'center': (cx, cy),
        'compact_used': compact_used,
        'source_segment_count': len(G.closed_chain(result)),
        'timings': timings,
    }


def label_items(result, opts):
    """生成标注文字项目（草图坐标，mm）。"""
    items = []
    rp = result.pitch_radius
    items.append(('节圆 ⌀{0:.2f}'.format(result.pitch_diameter), 0.0, rp * 0.35, rp * 0.06))
    items.append(('外圆 ⌀{0:.2f}'.format(result.outer_diameter),
                  rp * 0.35, result.outer_radius * 0.72, rp * 0.05))
    items.append(('齿根 ⌀{0:.2f}'.format(result.root_diameter),
                  -rp * 0.75, -rp * 0.55, rp * 0.05))
    return items


def clear_temporary(component, prefix=PREFIX_TMP):
    """清理带指定前缀的临时草图。"""
    removed = 0
    to_del = []
    for i in range(component.sketches.count):
        sk = component.sketches.item(i)
        if sk.name.startswith(prefix):
            to_del.append(sk)
    for sk in to_del:
        if delete_sketch(sk):
            removed += 1
    return removed
