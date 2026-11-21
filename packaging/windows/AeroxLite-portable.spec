# -*- mode: python ; coding: utf-8 -*-
# Portable single-file AeroxLite.exe (release extra; the installer uses the folder build).
#   python -m PyInstaller --distpath build\portable --workpath build\work-portable packaging\windows\AeroxLite-portable.spec
import os

SRC = os.path.abspath(os.path.join(SPECPATH, '..', '..', 'src'))
# Standard-library parts the app never uses (smaller download, faster start, less memory).
EXCLUDES = ['unittest', 'pydoc', 'doctest', 'pdb', 'test', 'tkinter.test', 'idlelib', 'lib2to3',
            'distutils', 'setuptools', 'pip', 'ensurepip', 'venv', 'xmlrpc', 'sqlite3', 'curses',
            'turtle', 'turtledemo', 'PIL.ImageQt', 'numpy',
            # image formats / colour management the app never uses (the AVIF codec alone is ~7.5 MB)
            'PIL._avif', 'PIL.AvifImagePlugin', 'PIL._webp', 'PIL.WebPImagePlugin', 'PIL._imagingcms', 'PIL.ImageCms',
            # no network access: drops OpenSSL (~6 MB); hashlib falls back to its built-in hashes
            'ssl', '_ssl', '_hashlib']


def trim_datas(datas):
    """Tcl's time-zone database is only used by Tcl's own clock command, which the app does not use."""
    return [d for d in datas if '_tcl_data/tzdata' not in d[0].replace('\\', '/')]

a = Analysis(
    [os.path.join(SRC, 'aerox_lite.py')],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=['generic', 'generic_ui', 'model_art', 'rivalcfg', 'calibration', 'rclick', 'smartbattery', 'helpers', 'PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,
)
a.datas = trim_datas(a.datas)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AeroxLite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
