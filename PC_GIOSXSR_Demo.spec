# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = [
    'qasync',
    'bleak',
    'bleak.backends.winrt',
    'bleak.backends.winrt.scanner',
    'bleak.backends.winrt.client',
    'bleak.backends.winrt.characteristic',
    'bleak.backends.winrt.descriptor',
    'bleak.backends.winrt.service',
    'bleak.backends.winrt.util',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'asyncio',
]
hiddenimports += collect_submodules('winrt')
hiddenimports += collect_submodules('winrt.windows')
hiddenimports += collect_submodules('winrt.windows.devices')
hiddenimports += collect_submodules('winrt.windows.devices.bluetooth')
hiddenimports += collect_submodules('winrt.windows.devices.bluetooth.advertisement')
hiddenimports += collect_submodules('winrt.windows.devices.bluetooth.genericattributeprofile')
hiddenimports += collect_submodules('winrt.windows.devices.enumeration')
hiddenimports += collect_submodules('winrt.windows.foundation')
hiddenimports += collect_submodules('winrt.windows.foundation.collections')
hiddenimports += collect_submodules('winrt.windows.storage')
hiddenimports += collect_submodules('winrt.windows.storage.streams')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PC_GIOSXSR_Demo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
