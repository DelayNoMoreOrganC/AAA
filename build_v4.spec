# -*- mode: python ; coding: utf-8 -*-
# V4 打包配置：onefile + 资源内嵌（templates/prompts/config）
# app_paths.py is_frozen() 走 _MEIPASS 读取内嵌资源

block_cipher = None

a = Analysis(
    ['legal_archive_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 模板：bundled .doc + 卷内目录 + manifests
        ('templates/bundled', 'templates/bundled'),
        ('templates/manifests', 'templates/manifests'),
        # 提取提示词
        ('prompts', 'prompts'),
        # 配置示例
        ('config.json.example', '.'),
    ],
    hiddenimports=[
        'tkinterdnd2',
        'win32com',
        'win32com.client',
        'pythoncom',
        'pywintypes',
        'fitz',
        'docx',
        'rapidocr_onnxruntime',
        'archive_catalog',
        'document_segmenter',
        'pdf_doc_locator',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'flask', 'werkzeug'],
    # 排除环境残留的重量级库（项目不直接依赖，rapidocr 仅需 onnxruntime）
    # torch+torchvision 占 ~2GB，pyarrow/av/shapely/scipy/sklearn/transformers/pandas 各数百MB
    # 见 excludes 合并下方
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 二次排除重量级库（合并到 Analysis.excludes）
for _bad in ['torch', 'torchvision', 'torchaudio',
             'pyarrow', 'av', 'shapely', 'scipy', 'sklearn',
             'transformers', 'pandas', 'matplotlib', 'sympy',
             'networkx', 'jinja2', 'PIL.ImageTk']:
    if _bad not in a.excludes:
        a.excludes.append(_bad)

import PyInstaller
_filtered = []
for _b in a.binaries:
    _name = _b[0]
    if any(_bad in _name for _bad in ['torch', 'torchvision', 'torchaudio',
                                       'pyarrow', '/av.', 'av.dll', 'libav',
                                       'shapely', 'scipy', 'sklearn',
                                       'transformers', 'pandas', 'matplotlib',
                                       'sympy', 'networkx', 'jinja2']):
        continue
    _filtered.append(_b)
a.binaries = _filtered

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='案件档案归档V4',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
