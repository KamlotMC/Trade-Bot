# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Meowcoin Market Maker Bot."""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.yaml', '.'),
        ('.env.example', '.'),
        ('LEGAL_NOTICE.md', '.'),
        ('README.md', '.'),
    ],
    hiddenimports=[
        'market_maker',
        'market_maker.config',
        'market_maker.exchange_client',
        'market_maker.strategy',
        'market_maker.risk_manager',
        'market_maker.logger',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MeowcoinMarketMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
