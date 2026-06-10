# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# dynhosts PyInstaller ビルド定義
#
# 使い方:
#   pip install -r requirements.txt pyinstaller
#   pyinstaller dynhosts.spec --noconfirm
#
# 出力: dist/dynhosts.exe（単一ファイル・コンソール非表示）
# =============================================================================

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # settings_gui の「スタートアップ」タブが import main するため明示的に同梱
        'main',
        'core',
        'settings_gui',
        # pystray はバックエンドを動的選択するため明示が必要
        'pystray._win32',
        # カスタム DNS サーバー機能（dnspython）
        'dns.resolver',
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
    name='dynhosts',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # コンソールウィンドウを表示しない（ログは dynhosts.log へ）
    console=False,
    disable_windowed_traceback=False,
    # UAC 昇格はアプリ側で自前処理する（--no-elevate を有効にするため manifest では要求しない）
    uac_admin=False,
)
