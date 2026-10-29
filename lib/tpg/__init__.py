# -*- coding: utf-8 -*-
"""同步带轮生成器 —— 核心计算库。

分层：
    profiles.py   齿形数据库（各系列同步带的节距与齿槽参数）
    geometry.py   HTD 名义尺寸几何求解及通用曲线工具
    sketch.py     草图生成（Fusion API）
    ui.py         命令对话框参数界面

注意：本插件**不包含任何图形/图片预览**。早期版本用过 Fusion 的
ImageCommandInput，但该控件在部分环境下会抛 "invalid argument imageFile"
并导致整个参数界面构建失败，故已彻底移除。所有几何结果以**数值文本**呈现。
"""

__version__ = '0.8.0'
