# -*- coding: utf-8 -*-
"""
同步带轮生成器 — Fusion 360 插件入口
====================================

结构
----

    TimingPulleyGenerator.py       本文件：Fusion 生命周期 + 命令编排 + 热重载
    TimingPulleyGenerator.manifest 插件清单
    lib/tpg/profiles.py            齿形数据库（各系列标准数据）
    lib/tpg/geometry.py            几何求解引擎（纯 Python，可离线自检）
    lib/tpg/sketch.py              Fusion 草图生成
    lib/tpg/ui.py                  命令对话框与参数界面
    tests/test_geometry.py         几何自检（不需要 Fusion）
    tests/test_dryrun.py           干跑测试（用 Fusion API 桩执行 UI/草图/入口）
    tools/make_icons.py            生成按钮图标

**本插件不含任何图形/图片预览**（见 README「关于预览」）。

安装
----

把整个 ``TimingPulleyGenerator`` 目录复制到 Fusion 的插件目录：

    %APPDATA%\\Autodesk\\Autodesk Fusion 360\\API\\AddIns\\

然后在 Fusion 中：工具 → 脚本和附加模块 → 附加模块 → 选中本插件 → 运行。

开发时改完代码只需在「脚本和附加模块」里**停止 → 运行**即可生效：
入口的 ``_reload_lib()`` 会从磁盘强制重载全部库模块，不需要重启 Fusion。

当前实现范围
------------

**HTD 系列（2M / 3M / 5M / 8M / 14M / 20M）已完整实现**，齿槽几何全部可调。
GT / RPP / T / AT / MXL 等系列已在 ui 中列出规格与型号，几何求解器待补
（见 README「扩展新齿形系列」）。
"""

import importlib
import os
import sys
import traceback

import adsk.core
import adsk.fusion

# 本插件的版本号。**每次修改代码后必须递增**，用于确认 Fusion 加载的确实是
# 新版本（启动时会打印到文本命令窗口）。
__version__ = '0.5.0'

# ---------------------------------------------------------------------------
# 热重载：每次启动都从磁盘重新加载本插件的全部模块
# ---------------------------------------------------------------------------
#
# 为什么必须这样做：Fusion 把已导入的 Python 模块缓存在内存里，卸载插件
# （Stop）**不会**清掉它们；下次运行（Run）拿到的仍是旧的模块对象。结果是
# 改了代码却看不到效果，甚至新旧模块混用导致 traceback 行号与源码对不上 ——
# 这会让人误判问题所在，非常浪费时间。
#
# 因此这里在导入前彻底清理本插件的模块，并让 Python 丢弃目录缓存，
# 保证每次「停止 → 运行」都加载最新的源码，无需重启 Fusion。
#
_PKG = 'tpg'          # lib 下的包名
_MODULE_PREFIX = _PKG + '.'


def _purge_modules():
    """从 sys.modules 移除本插件的所有模块，并让导入系统丢弃目录缓存。"""
    try:
        for name in [n for n in list(sys.modules)
                     if n == _PKG or n.startswith(_MODULE_PREFIX)]:
            sys.modules.pop(name, None)
    except Exception:
        pass
    try:
        # 清掉 Finder 缓存的目录列表与已编译字节码条目，
        # 使新文件/被删除的文件立刻生效。
        importlib.invalidate_caches()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 路径准备：把 lib 加入 sys.path，使 `import tpg` 可用
# ---------------------------------------------------------------------------

_ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_ADDIN_DIR, 'lib')
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

# 先清理，再导入 —— 保证拿到的是磁盘上的最新代码
_purge_modules()

from tpg import geometry as G          # noqa: E402
from tpg import profiles as P          # noqa: E402
from tpg import sketch as SK           # noqa: E402
from tpg import ui as UI               # noqa: E402
from tpg import __version__ as LIB_VERSION   # noqa: E402


def _reload_lib():
    """清理并重新导入本插件的库模块，把新模块绑定到本模块的全局名字上。

    在 ``run()`` 开头调用，保证每次「停止 → 运行」都执行磁盘上的最新代码。
    这样开发时无需重启 Fusion，也避免新旧模块混用导致的诡异错误。
    """
    global G, P, SK, UI, LIB_VERSION
    try:
        _purge_modules()
        G = importlib.import_module('tpg.geometry')
        P = importlib.import_module('tpg.profiles')
        SK = importlib.import_module('tpg.sketch')
        UI = importlib.import_module('tpg.ui')
        LIB_VERSION = importlib.import_module('tpg').__version__
    except Exception:
        _log('库模块重载失败，继续使用已加载版本:\n{0}'
             .format(traceback.format_exc()))


# ---------------------------------------------------------------------------
# 自愈式加载
# ---------------------------------------------------------------------------
#
# 上面这些代码只有在 Fusion **真正重新执行本文件** 时才会跑到。但实测中发现：
# 有时点「停止 / 运行」并不会重新执行入口文件 —— 于是命令按钮仍然指向第一次
# 加载时创建的那个 commandCreated 回调，跑的是内存里的旧代码，改了源码也
# 看不出变化（traceback 的行号还会和源码对不上，极易误导排查方向）。
#
# 对策：在文件末尾检查 Fusion 内存里的模块与本文件是否一致，不一致就把自己
# 重新执行一遍。这样**即使 Fusion 复用了旧模块对象，只要它执行到本文件，
# 后续逻辑也一定是磁盘上的最新代码**。
# ---------------------------------------------------------------------------

def _loaded_version_in_memory():
    """取 Fusion 内存中记录的本模块版本号（没有则返回 None）。"""
    try:
        mod = sys.modules.get(__name__)
        if mod is None:
            return None
        return getattr(mod, '__version__', None)
    except Exception:
        return None


def _rerun_self():
    """把本文件重新执行到一个**全新的模块对象**里，并用它覆盖 sys.modules。

    这样既拿到最新代码，又不会留下新旧混用的状态（旧对象无人引用后被回收）。
    任何异常都会被吞掉并记录，绝不影响插件的正常加载。
    """
    try:
        import types
        src = open(os.path.abspath(__file__), 'r', encoding='utf-8').read()
        fresh = types.ModuleType(__name__)
        fresh.__file__ = os.path.abspath(__file__)
        fresh.__package__ = ''
        fresh.__builtins__ = __builtins__
        sys.modules[__name__] = fresh          # 先注册，供内部 import 使用
        code = compile(src, os.path.abspath(__file__), 'exec')
        exec(code, fresh.__dict__)
        _log('检测到入口文件已更新，已从磁盘重新加载 '
             '(v{0} -> v{1})'.format(_loaded_version_in_memory(),
                                     getattr(fresh, '__version__', '?')))
    except Exception:
        _log('自愈重载失败（继续使用当前代码）:\n{0}'
             .format(traceback.format_exc()))

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CMD_ID = 'TimingPulleyGenerator_Create'
CMD_NAME = '同步带轮'
CMD_TOOLTIP = '生成同步带轮草图（当前完整支持 HTD 2M/3M/5M/8M/14M/20M）'

PANEL_IDS = ['SolidCreatePanel', 'SketchCreatePanel']
WORKSPACE_ID = 'FusionSolidEnvironment'

_app = adsk.core.Application.get()
_ui = _app.userInterface

_handlers = []
_dialog = None          # type: UI.Dialog


# ---------------------------------------------------------------------------
# 插件生命周期
# ---------------------------------------------------------------------------

def run(context):
    """插件加载入口。"""
    try:
        # 再次清理并重新导入，确保「停止 → 运行」后跑的是最新代码。
        # （模块级已经清过一次；这里再清一次是为了让 handler 里引用的
        #   G / UI / SK 等名字也指向新模块 —— 只需重新绑定即可。）
        _reload_lib()

        _log('{0} 插件启动（插件 v{1} / 库 v{2}）'.format(
            CMD_NAME, __version__, LIB_VERSION))
        _log('模块路径: {0}'.format(_LIB_DIR))

        # 清空上一轮可能残留的处理器引用（重复启动时不累积）
        del _handlers[:]

        # 清理可能残留的命令定义
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

        icon_folder = os.path.join(_ADDIN_DIR, 'resources', 'command')
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME, CMD_TOOLTIP, icon_folder)

        _handlers.append(_make_handler(cmd_def.commandCreated, _on_command_created))

        ws = _ui.workspaces.itemById(WORKSPACE_ID)
        if ws is None:
            _log('未找到工作区 {0}'.format(WORKSPACE_ID))
            return

        for pid in PANEL_IDS:
            panel = ws.toolbarPanels.itemById(pid)
            if panel is None:
                _log('未找到面板 {0}'.format(pid))
                continue
            ctrl = panel.controls.itemById(CMD_ID)
            if not ctrl:
                panel.controls.addCommand(cmd_def)
            _log('{0} 已加入 {1}'.format(CMD_NAME, pid))
    except Exception:
        _log('run 失败:\n{0}'.format(traceback.format_exc()))
        if _ui:
            _ui.messageBox('同步带轮生成器加载失败：\n{0}'
                           .format(traceback.format_exc()))


def stop(context):
    """插件卸载入口：移除按钮与命令定义。"""
    try:
        _log('{0} 插件停止'.format(CMD_NAME))

        ws = _ui.workspaces.itemById(WORKSPACE_ID)
        if ws:
            for pid in PANEL_IDS:
                panel = ws.toolbarPanels.itemById(pid)
                if panel:
                    ctrl = panel.controls.itemById(CMD_ID)
                    if ctrl:
                        ctrl.deleteMe()

        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        _log('stop 失败:\n{0}'.format(traceback.format_exc()))
    finally:
        del _handlers[:]
        globals()['_dialog'] = None


def _log(msg):
    try:
        print('[同步带轮] {0}'.format(msg))
    except Exception:
        pass


def _resolve_handler_type(event):
    """求某个 Event 需要的 handler 基类。

    不同 Fusion 版本暴露的 handler 类差别很大（例如某些版本没有
    ``adsk.core.EventHandler`` 基类），因此**不硬编码**，改为运行时探测：

    1. 读 ``event.add`` 的参数类型注解 —— 这是 Autodesk 官方示例
       （fusionAddInUtils.event_utils.add_handler）采用的做法，最可靠；
    2. 退回到按事件对象类名推断（CommandCreatedEvent -> CommandCreatedEventHandler）;
    3. 再退回 ``adsk.core.EventHandler``。

    返回基类或 None（None 表示无法确定，调用方跳过该事件）。
    """
    # --- 1. 反射注解 ---
    try:
        ann = getattr(event.add, '__annotations__', None)
        if ann:
            name = ann.get('handler')
            if isinstance(name, str):
                cls = getattr(adsk.core, name, None)
                if cls is not None:
                    return cls
            elif name is not None:
                return name
    except Exception:
        pass

    # --- 2. 按事件类名推断 ---
    try:
        ev_name = type(event).__name__          # 如 CommandCreatedEvent
        if ev_name.endswith('Event'):
            cand = ev_name[:-len('Event')] + 'EventHandler'
            cls = getattr(adsk.core, cand, None)
            if cls is not None:
                return cls
    except Exception:
        pass

    # --- 3. 通用基类 ---
    return getattr(adsk.core, 'EventHandler', None)


def _make_handler(event, func, name=None):
    """创建并保存事件处理器。

    必须保持引用，否则会被 Python GC 回收导致事件不再触发。
    返回处理器，取不到可用基类时返回 None。
    """
    base = _resolve_handler_type(event)
    if base is None:
        _log('警告：无法确定 {0} 的 handler 基类，该事件未注册'
             .format(type(event).__name__))
        return None

    label = name or type(event).__name__

    class _H(base):
        def __init__(self):
            try:
                super().__init__()
            except Exception:
                pass

        def notify(self, args):
            try:
                func(args)
            except Exception:
                tb = traceback.format_exc()
                _log('事件处理异常 ({0}):\n{1}'.format(label, tb))
                try:
                    _ui.messageBox('同步带轮生成器出错：\n{0}'.format(tb))
                except Exception:
                    pass

    handler = _H()
    try:
        event.add(handler)
    except Exception:
        _log('注册事件 {0} 失败:\n{1}'.format(label, traceback.format_exc()))
        return None
    return handler


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------

def _on_command_created(args):
    """用户点击按钮后构建对话框。"""
    global _dialog

    cmd = args.command
    cmd.isExecutedWhenPreEmpted = False
    inputs = cmd.commandInputs

    design = adsk.fusion.Design.cast(_app.activeProduct)
    if design is None:
        _ui.messageBox('请先打开一个零件（Design）文档。')
        return

    _handlers.append(_make_handler(cmd.execute, _on_execute))
    _handlers.append(_make_handler(cmd.inputChanged, _on_input_changed))
    _handlers.append(_make_handler(cmd.validateInputs, _on_validate))
    _handlers.append(_make_handler(cmd.destroy, _on_destroy))

    if _try_create_dialog(design, inputs):
        return

    # 首次构建失败：很可能是 Fusion 复用了内存里的旧模块。此时从磁盘重新加载全部代码再试一次
    _log('首次构建界面失败，尝试从磁盘重载后重建 ...')
    try:
        _reload_lib()
        _refresh_ui_refs()
        if _try_create_dialog(design, inputs):
            _log('重载后构建成功')
            _ui.messageBox(
                '检测到插件代码已更新，已自动重新加载并构建界面。\n\n'
                '当前版本：插件 v{0} / 库 v{1}'.format(__version__,
                                                      LIB_VERSION))
            return
    except Exception:
        _log('重载后重建仍失败:\n{0}'.format(traceback.format_exc()))

    _log('构建参数界面失败（重载后仍失败）')
    err_detail = _last_create_error if _last_create_error else '请查看「视图 → 文本命令」窗口中的详细日志。'
    _ui.messageBox('构建参数界面失败：\n\n{0}\n\n当前版本：插件 v{1} / 库 v{2}'.format(
        err_detail, __version__, LIB_VERSION))


def _save_error_log(tb_str):
    try:
        p = os.path.join(_ADDIN_DIR, 'last_error.log')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(tb_str)
    except Exception:
        pass


_last_create_error = ''


def _bind_active_sketch(dialog):
    """若当前处于草图编辑模式（app.activeEditObject 为 Sketch），自动绑定至 target_plane。"""
    try:
        active_obj = getattr(_app, 'activeEditObject', None)
        if active_obj is not None and (
            isinstance(active_obj, adsk.fusion.Sketch) or
            hasattr(active_obj, 'sketchCurves') or
            getattr(active_obj, 'objectType', '').endswith('Sketch')
        ):
            sel_plane = dialog.el.get(UI.ID_TARGET_PLANE)
            if sel_plane is not None and hasattr(sel_plane, 'addSelection'):
                try:
                    sel_plane.addSelection(active_obj)
                    _log('已自动绑定当前激活草图: {0}'.format(getattr(active_obj, 'name', '草图')))
                except Exception:
                    pass
    except Exception:
        pass


def _try_create_dialog(design, inputs):
    """尝试用当前已加载的 UI 模块构建对话框；成功返回 True。"""
    global _dialog, _last_create_error
    try:
        _dialog = UI.Dialog(design)
        _dialog.create(inputs)
        _bind_active_sketch(_dialog)
        _log('参数界面构建成功（插件 v{0} / 库 v{1}）'.format(
            __version__, LIB_VERSION))
        return True
    except Exception:
        _last_create_error = traceback.format_exc()
        _log('构建对话框失败:\n{0}'.format(_last_create_error))
        _save_error_log(_last_create_error)
        return False


def _refresh_ui_refs():
    """重载库模块后，刷新本模块内引用的 UI 名字。"""
    global UI
    UI = importlib.import_module('tpg.ui')


def _on_input_changed(args):
    if _dialog is None:
        return
    try:
        _dialog.update()
    except Exception:
        _log('刷新界面失败:\n{0}'.format(traceback.format_exc()))


def _on_validate(args):
    if _dialog is None:
        args.areInputsValid = False
        return
    try:
        ok, msg = _dialog.validate()
        if not ok:
            args.areInputsValid = False
            try:
                _dialog.el[UI.ID_WARN].text = '无法生成：\n{0}'.format(msg)
            except Exception:
                pass
        else:
            args.areInputsValid = True
            try:
                _dialog.el[UI.ID_WARN].text = ''
            except Exception:
                pass
    except Exception:
        args.areInputsValid = False
        _log('校验失败:\n{0}'.format(traceback.format_exc()))


def _on_destroy(args):
    global _dialog
    del _handlers[1:]        # 仅保留 run() 中注册的命令定义处理器 (索引 0)
    _dialog = None


def _on_execute(args):
    """执行生成。"""
    if _dialog is None:
        return

    design = adsk.fusion.Design.cast(_app.activeProduct)
    if design is None:
        _ui.messageBox('当前文档不是零件文档。')
        return

    try:
        opts = _dialog.read()

        # 若未在对话框中选面，但当前正处于草图编辑状态，自动绑定当前草图
        if opts.get('target_plane') is None:
            active_obj = getattr(_app, 'activeEditObject', None)
            if active_obj is not None and (
                isinstance(active_obj, adsk.fusion.Sketch) or
                hasattr(active_obj, 'sketchCurves') or
                getattr(active_obj, 'objectType', '').endswith('Sketch')
            ):
                opts['target_plane'] = active_obj

        res, err = _dialog.solve(opts)
        if res is None:
            _ui.messageBox('无法生成：\n{0}'.format(err))
            return

        component = _resolve_component(design)

        build_opts = {
            'sketch_name': opts['sketch_name'],
            'replace': opts['replace'],
            'target_plane': opts.get('target_plane'),
            'center_point': opts.get('center_point'),
            'draw_pitch_circle': opts['draw_pitch_circle'],
            'draw_root_circle': opts['draw_root_circle'],
            'draw_outer_circle': opts['draw_outer_circle'],
            'draw_mouth_line': opts.get('draw_mouth_line', False),
            'draw_center_line': opts.get('draw_center_line', False),
            'labels': opts['labels'],
            'sampled_fallback': opts['sampled_fallback'],
        }

        out = SK.build(component, res, build_opts)

        # 可选标注文字
        if opts['labels']:
            try:
                SK.draw_labels(out['sketch'], SK.label_items(res, build_opts))
            except Exception:
                pass

        # 记录参数到设计属性（便于日后追溯）
        try:
            _save_attributes(design, res, opts, out['messages'])
        except Exception:
            pass

        # 视图适应
        try:
            _app.activeViewport.fit()
        except Exception:
            pass

        msgs = list(out['messages'])
        if not out['ok']:
            msgs.append('未生成有效轮廓，请检查参数或草图曲线。')
        if msgs:
            _ui.messageBox('生成完成，但有提示：\n\n' + '\n'.join(msgs))
        else:
            _ui.messageBox(
                '已生成同步带轮草图「{0}」\n\n'
                '节圆 ⌀{1:.3f} mm ／ 外圆 ⌀{2:.3f} mm ／ 齿数 {3}\n'
                '轮廓圆弧 {4} 段'.format(
                    out['sketch'].name, res.pitch_diameter,
                    res.outer_diameter, res.teeth, out['arc_count']))

        _log('生成完成: {0} 段圆弧, {1} 个轮廓'.format(
            out['arc_count'], out['profile_count']))

    except Exception:
        tb = traceback.format_exc()
        _log('执行失败:\n{0}'.format(tb))
        _ui.messageBox('生成失败：\n{0}'.format(tb))


def _resolve_component(design):
    """决定草图建在哪个组件。

    零件文档 → 根组件；装配/混合文档 → 根组件（保持简单可预期）。
    """
    return design.rootComponent


def _save_attributes(design, res, opts, messages):
    """把生成参数写入设计属性，方便日后核对/复现。"""
    import json
    attrs = design.attributes
    payload = {
        'version': 1,
        'result': res.as_dict(),
        'options': dict((k, str(v)) for k, v in opts.items()),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    existing = attrs.itemByName('TimingPulleyGenerator', 'LastRun')
    if existing:
        existing.value = text
    else:
        attrs.add('TimingPulleyGenerator', 'LastRun', text)


# ---------------------------------------------------------------------------
# 自愈触发（必须放在文件**最末尾**）
# ---------------------------------------------------------------------------
#
# 情形 A：Fusion 重新执行了本文件 → 此时本文件的对象还没进 sys.modules，
#         说明代码本来就是最新的，什么都不用做。
# 情形 B：Fusion 复用了内存里的旧模块 → sys.modules 里的对象版本号与磁盘
#         不符，此时把自己重新执行一遍，确保后续逻辑用的是最新代码。
#
_MEM_VER = _loaded_version_in_memory()
if _MEM_VER is not None and _MEM_VER != __version__:
    _rerun_self()
