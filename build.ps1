# =============================================================================
# dynhosts EXE ビルドスクリプト
#
# 使い方:
#   .\build.ps1
#
# 出力:
#   dist\dynhosts.exe  — 単一実行ファイル
#   dist\dynhosts.zip  — 配布用 ZIP（EXE + config.yaml.example + README.md）
# =============================================================================

$ErrorActionPreference = "Stop"

# 依存パッケージと PyInstaller をインストール
python -m pip install -r requirements.txt pyinstaller

# ビルド
python -m PyInstaller dynhosts.spec --noconfirm

# 配布用 ZIP を作成
Copy-Item config.yaml.example dist\ -Force
Copy-Item README.md dist\ -Force
Compress-Archive `
    -Path dist\dynhosts.exe, dist\config.yaml.example, dist\README.md `
    -DestinationPath dist\dynhosts.zip -Force

Write-Host ""
Write-Host "ビルド完了:"
Write-Host "  dist\dynhosts.exe"
Write-Host "  dist\dynhosts.zip"
