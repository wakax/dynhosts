# build.ps1 — dynhosts Go ビルドスクリプト
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","User")

$Root   = $PSScriptRoot
$OutDir = Join-Path $Root "dist\dynhosts"
$OutExe = Join-Path $OutDir "dynhosts.exe"

Write-Host "=== dynhosts Go ビルド ===" -ForegroundColor Cyan

# ── goversioninfo インストール ────────────────────────────────────────────
Write-Host "[1/4] goversioninfo ツールを確認中..."
$gopathBin = Join-Path (& go env GOPATH) "bin"
$env:PATH += ";$gopathBin"

if (-not (Get-Command goversioninfo -ErrorAction SilentlyContinue)) {
    Write-Host "  goversioninfo をインストールします..."
    go install github.com/josephspurrier/goversioninfo/cmd/goversioninfo@latest
}

# ── リソースファイル生成 ───────────────────────────────────────────────────
Write-Host "[2/4] Windows リソース (rsrc.syso) を生成中..."
$SysoPath        = Join-Path $Root "rsrc.syso"
$VersionInfoPath = Join-Path $Root "versioninfo.json"

Push-Location $Root
try {
    & goversioninfo -o $SysoPath $VersionInfoPath
    Write-Host "  rsrc.syso を生成しました（アイコン + マニフェスト + バージョン情報）。"
} finally {
    Pop-Location
}

# ── go mod tidy ───────────────────────────────────────────────────────────
Write-Host "[3/4] go mod tidy..."
Push-Location $Root
try {
    go mod tidy
} finally {
    Pop-Location
}

# ── ビルド ────────────────────────────────────────────────────────────────
Write-Host "[4/4] go build → $OutExe"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Push-Location $Root
try {
    go build -ldflags="-H windowsgui -s -w" -o $OutExe .
} finally {
    Pop-Location
}

# ── 補助ファイルをコピー ──────────────────────────────────────────────────
foreach ($f in @("README.md", "dynhosts.ico")) {
    $src = Join-Path $Root $f
    if (Test-Path $src) { Copy-Item $src $OutDir -Force }
}

Write-Host ""
Write-Host "ビルド完了: $OutExe" -ForegroundColor Green
Write-Host "配布物:     $OutDir"  -ForegroundColor Green
