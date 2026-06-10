# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# dynhosts PyInstaller ビルド定義
#
# 使い方:
#   pip install -r requirements.txt pyinstaller
#   python make_icon.py          # EXE アイコン（dynhosts.ico）を生成
#   pyinstaller dynhosts.spec --noconfirm
#
# 出力: dist/dynhosts/ フォルダ（onedir 形式・コンソール非表示）
#
# ※ onefile（単一 EXE）形式は Windows Defender 等に
#    トロイの木馬として誤検知されやすい（自己展開構造がヒューリスティック検知の
#    引き金になる）ため、onedir 形式で配布する。
# =============================================================================

from datetime import date

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

# -----------------------------------------------------------------------------
# バージョン情報
# 形式: <major>.<minor>.<ビルド日付 YYYYMMDD>  例: 1.0.20260610
# -----------------------------------------------------------------------------
VERSION_BASE = "1.0"

_today = date.today()
APP_VERSION = f"{VERSION_BASE}.{_today:%Y%m%d}"

# バイナリ版バージョンは 16bit×4 のため日付を「年」「月日」に分割する
# （例: 1.0.2026.610 — 文字列版には 1.0.20260610 をそのまま入れる）
_major, _minor = (int(x) for x in VERSION_BASE.split("."))
_filevers = (_major, _minor, _today.year, int(f"{_today:%m%d}"))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_filevers,
        prodvers=_filevers,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,      # Windows NT
        fileType=0x1,    # アプリケーション
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            # 0411 = 日本語, 04B0 = Unicode
            StringTable('041104B0', [
                StringStruct('FileDescription', 'dynhosts - hostsファイル自動更新ツール'),
                StringStruct('FileVersion', APP_VERSION),
                StringStruct('InternalName', 'dynhosts'),
                StringStruct('OriginalFilename', 'dynhosts.exe'),
                StringStruct('ProductName', 'dynhosts'),
                StringStruct('ProductVersion', APP_VERSION),
                StringStruct('CompanyName', 'wakax'),
                StringStruct('LegalCopyright', 'MIT License'),
            ]),
        ]),
        VarFileInfo([VarStruct('Translation', [0x0411, 1200])]),
    ],
)

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
    [],
    exclude_binaries=True,
    name='dynhosts',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # コンソールウィンドウを表示しない（ログは dynhosts.log へ）
    console=False,
    disable_windowed_traceback=False,
    # トレイアイコンと同じデザインの EXE アイコン（make_icon.py で生成）
    icon='dynhosts.ico',
    # バージョン情報リソース（上で動的生成）
    version=version_info,
    # UAC 昇格はアプリ側で自前処理する（--no-elevate を有効にするため manifest では要求しない）
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='dynhosts',
)
