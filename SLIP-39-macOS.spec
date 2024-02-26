# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files('shamir_mnemonic')
datas += collect_data_files('slip39')

block_cipher = None

a = Analysis(
    ['SLIP-39.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['slip39'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SLIP-39',
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
    codesign_identity='EAA134BE299C43D27E33E2B8645FF4CF55DE8A92',
    entitlements_file=None,
    icon='images/SLIP-39.icns',
)

app = BUNDLE(
    exe,
    name='SLIP-39.app',
    icon='images/SLIP-39.icns',
    version='11.2.1',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'LSBackgroundOnly': False,
        'NSRequiresAquaSystemAppearance': 'No',
        'CFBundleSupportedPlatforms': ['MacOSX'],
        'CFBundleIdentifier': 'ca.kundert.perry.SLIP39',
        'CFBundleVersion':'11.2.1',
        'CFBundlePackageType':'APPL',
        'LSApplicationCategoryType':'public.app-category.utilities',
        'LSMinimumSystemVersion':'10.15',
        'NSHumanReadableCopyright':"Copyright © 2023 Perry Kundert.",
        'ITSAppUsesNonExemptEncryption': False,
    },
    bundle_identifier='ca.kundert.perry.SLIP39',
)
