# build.ps1 — dynhosts Go ビルドスクリプト
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","User")

$Root   = $PSScriptRoot
$OutDir = Join-Path $Root "dist\dynhosts"
$OutExe = Join-Path $OutDir "dynhosts.exe"

Write-Host "=== dynhosts Go ビルド ===" -ForegroundColor Cyan

# ── rsrc インストール ──────────────────────────────────────────────────────
Write-Host "[1/4] rsrc ツールを確認中..."
$gopathBin = Join-Path (& go env GOPATH) "bin"
$env:PATH += ";$gopathBin"

if (-not (Get-Command rsrc -ErrorAction SilentlyContinue)) {
    Write-Host "  rsrc をインストールします..."
    go install github.com/akavel/rsrc@latest
}

# ── リソースファイル生成 ───────────────────────────────────────────────────
Write-Host "[2/4] Windows リソース (rsrc.syso) を生成中..."
$ManifestPath = Join-Path $Root "dynhosts.manifest"
$IcoPath      = Join-Path $Root "dynhosts.ico"
$SysoPath     = Join-Path $Root "rsrc.syso"

if (Test-Path $IcoPath) {
    & rsrc -manifest $ManifestPath -ico $IcoPath -o $SysoPath
    Write-Host "  rsrc.syso を生成しました（アイコン + マニフェスト）。"
} else {
    Write-Host "  dynhosts.ico が見つかりません。マニフェストのみ埋め込みます。"
    & rsrc -manifest $ManifestPath -o $SysoPath
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
foreach ($f in @("config.yaml.example", "README.md", "dynhosts.ico")) {
    $src = Join-Path $Root $f
    if (Test-Path $src) { Copy-Item $src $OutDir -Force }
}

Write-Host ""
Write-Host "ビルド完了: $OutExe" -ForegroundColor Green
Write-Host "配布物:     $OutDir"  -ForegroundColor Green
