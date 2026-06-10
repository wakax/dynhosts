# =============================================================================
# dynhosts EXE ビルドスクリプト
#
# 使い方:
#   .\build.ps1
#
# 出力:
#   dist\dynhosts\     — アプリ一式（onedir 形式）
#   dist\dynhosts.zip  — 配布用 ZIP（上記フォルダ + config.yaml.example + README.md）
# =============================================================================

$ErrorActionPreference = "Stop"

# 依存パッケージと PyInstaller をインストール
python -m pip install -r requirements.txt pyinstaller

# EXE アイコンを生成（トレイアイコンと同じデザイン）
python make_icon.py

# ビルド
python -m PyInstaller dynhosts.spec --noconfirm

# 配布用 ZIP を作成（ZIP のルートは dynhosts フォルダ 1 つ）
Copy-Item config.yaml.example dist\dynhosts\ -Force
Copy-Item README.md dist\dynhosts\ -Force
Compress-Archive `
    -Path dist\dynhosts `
    -DestinationPath dist\dynhosts.zip -Force

Write-Host ""
Write-Host "ビルド完了:"
Write-Host "  dist\dynhosts\dynhosts.exe"
Write-Host "  dist\dynhosts.zip"
