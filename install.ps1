# =============================================================================
# dynhosts セットアップスクリプト
# 実行方法: 右クリック → "PowerShell で実行" または管理者の PowerShell で:
#   Set-ExecutionPolicy -Scope Process Bypass; .\install.ps1
# =============================================================================

param(
    [switch]$Uninstall,       # タスクスケジューラからの削除のみ実行
    [switch]$SkipPipInstall   # pip インストールをスキップ
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "=== dynhosts セットアップ ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 管理者権限チェック
# ---------------------------------------------------------------------------
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[ERROR] このスクリプトは管理者権限で実行してください。" -ForegroundColor Red
    Write-Host "        右クリック → '管理者として実行' でPowerShellを開き直してください。"
    Read-Host "Press Enter to exit"
    exit 1
}

# ---------------------------------------------------------------------------
# アンインストールモード
# ---------------------------------------------------------------------------
if ($Uninstall) {
    Write-Host "タスクスケジューラからタスクを削除します..." -ForegroundColor Yellow
    python "$ScriptDir\main.py" --uninstall
    Write-Host "完了しました。" -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# Python 確認
# ---------------------------------------------------------------------------
Write-Host "[1/3] Python の確認..." -ForegroundColor Yellow

try {
    $pyVersion = python --version 2>&1
    Write-Host "      $pyVersion が見つかりました。" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python が見つかりません。" -ForegroundColor Red
    Write-Host "        https://www.python.org/ からインストールしてください。"
    Read-Host "Press Enter to exit"
    exit 1
}

# ---------------------------------------------------------------------------
# pip インストール
# ---------------------------------------------------------------------------
if (-not $SkipPipInstall) {
    Write-Host "[2/3] 依存パッケージのインストール..." -ForegroundColor Yellow
    python -m pip install -r "$ScriptDir\requirements.txt" --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] pip install に失敗しました。" -ForegroundColor Red
        exit 1
    }
    Write-Host "      インストール完了。" -ForegroundColor Green
} else {
    Write-Host "[2/3] pip インストールをスキップしました。" -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# タスクスケジューラ登録
# ---------------------------------------------------------------------------
Write-Host "[3/3] タスクスケジューラへの登録..." -ForegroundColor Yellow
python "$ScriptDir\main.py" --install --no-elevate

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== セットアップ完了 ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "次のステップ:"
    Write-Host "  1. config.yaml を編集して管理したい FQDN を登録してください。"
    Write-Host "  2. タスクスケジューラが自動的に定期更新を行います。"
    Write-Host "  3. システムトレイから手動更新する場合:"
    Write-Host "       python $ScriptDir\main.py"
    Write-Host ""
    Write-Host "設定ファイル: $ScriptDir\config.yaml"
    Write-Host "ログファイル: $ScriptDir\dynhosts.log"
    Write-Host ""
} else {
    Write-Host "[ERROR] タスクスケジューラへの登録に失敗しました。" -ForegroundColor Red
    exit 1
}

Read-Host "Press Enter to close"
