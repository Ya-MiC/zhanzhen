# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 产出单文件 dist/zhanzhen.exe（Windows 免安装版）。

用法（在仓库根目录）：
    pip install -r requirements.txt pyinstaller
    pyinstaller zhanzhen.spec

要点：
- onefile：EXE 里直接收编 binaries/datas，双击即用；
- datas 把 web/ 与 rules_builtin.yaml 带进解包目录(sys._MEIPASS)；
  另放一份 zhanzhen/__init__.py 进 zhanzhen/ 目录 —— webapp.py 用
  `dirname(__file__)/../web` 定位页面，而包代码编译进 PYZ 后该目录物理不存在，
  放一个真实文件可确保目录被创建，页面路径才能解析到 _MEIPASS/web；
- hiddenimports 补齐 uvicorn 运行期按字符串动态加载的模块，
  以及 webapp 函数体内延迟 import 的懒依赖（静态分析扫不到的兜底）。
"""

import os

ROOT = SPECPATH  # spec 所在目录 = 仓库根

a = Analysis(
    [os.path.join(ROOT, 'zhanzhen', 'desktop.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'web'), 'web'),
        (os.path.join(ROOT, 'rules_builtin.yaml'), '.'),
        # 占位数据文件：保证解包后存在 zhanzhen/ 物理目录（见文件头说明）
        (os.path.join(ROOT, 'zhanzhen', '__init__.py'), 'zhanzhen'),
    ],
    hiddenimports=[
        # ---- uvicorn 动态加载的组件（源码里是字符串拼接，需显式声明）----
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # ---- webapp 的懒依赖（函数体内 import，运行期才加载）----
        'zhanzhen.database',
        'zhanzhen.billing',
        'zhanzhen.auth',
        'zhanzhen.store',
        'zhanzhen.storage',
        'zhanzhen.importers',
        'zhanzhen.ocr_router',
        'zhanzhen.report_engine',
        'zhanzhen.ai_assistant',
        'zhanzhen.rules12',
        'yaml',          # rules_builtin.yaml 参数加载（PyYAML）
        'openpyxl',      # 序时账 Excel 导出 / 账套导入
        'jinja2',        # 报告引擎 v2 模板
        'pdfplumber',    # PDF 文本层提取（OCR 一级降级链）
        'pypdf',         # PDF 解析
    ],
    excludes=[
        # 体积巨大且 exe 场景默认不用的可选依赖；代码已做优雅降级
        'paddleocr',
        'paddle',
        'weasyprint',
        'matplotlib',
        'tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='zhanzhen',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # 保留控制台窗口：显示访问地址与日志，Ctrl+C 可退出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
