# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['engineio.async_drivers.threading']
hiddenimports += collect_submodules('simple_websocket')
hiddenimports += collect_submodules('wsproto')


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'), ('static', 'static'),
        ('landgrab/templates', 'landgrab/templates'),
        ('landgrab/static', 'landgrab/static'),
        ('landgrab/data/world.txt', 'landgrab/data'),
        ('landgrab/data/korea.txt', 'landgrab/data'),
        ('landgrab/data/countries.json', 'landgrab/data'),
        ('landgrab/data/country_maps', 'landgrab/data/country_maps'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='server',
)
