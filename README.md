# dynhosts

FQDN を DNS 解決して Windows の `hosts` ファイルを自動更新するツールです。  
システムトレイに常駐し、定期的に名前解決を行って結果を反映します。

## 特徴

- **自動更新** — 設定した間隔で FQDN を DNS 解決し `hosts` ファイルを更新
- **システムトレイ常駐** — バックグラウンドで動作し、右クリックメニューから操作
- **GUI 設定画面** — エントリーの追加・編集・削除、有効/無効の切り替えをウィンドウで操作
- **エントリーごとの有効/無効** — 設定画面のチェックで個別に停止可能
- **自動バックアップ** — 更新前に `hosts` ファイルをバックアップ（世代管理あり）
- **タスクスケジューラー連携** — ログオン時の自動起動・定期更新をスケジューラーに登録
- **二重起動防止** — 名前付きミューテックスで同一プロセスの重複起動を防止

## 動作環境

- Windows 10 / 11
- Python 3.9 以上（[python.org](https://www.python.org/downloads/) 公式インストーラー推奨）
  - **EXE 版を使う場合は Python のインストールは不要です**（[EXE 版の配布](#exe-版の配布)を参照）

## セットアップ

### 1. 依存パッケージのインストール

```powershell
pip install -r requirements.txt
```

| パッケージ | 用途 |
|---|---|
| `pyyaml` | 設定ファイルの読み込み（必須） |
| `pystray` | システムトレイアイコン（必須） |
| `Pillow` | トレイアイコン画像の生成（必須） |
| `dnspython` | カスタム DNS サーバー指定時のみ必要 |

### 2. タスクスケジューラーへの登録（推奨）

管理者として PowerShell を開き、以下を実行します。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

登録される内容：

| タスク名 | トリガー | 内容 |
|---|---|---|
| `dynhosts-tray` | ログオン時 | システムトレイを自動起動 |
| `dynhosts-auto-update` | 定期（設定間隔） + 起動時 | hosts ファイルを更新 |

スタートメニューへのショートカット登録は設定画面の「スタートアップ」タブから行えます。

## 使い方

### トレイモードで起動

```powershell
python main.py
```

初回起動時は UAC ダイアログが表示されます（`hosts` ファイルの書き込みに管理者権限が必要）。

タスクスケジューラー経由での自動起動時は UAC なしで起動します。

### トレイアイコンのメニュー

| メニュー項目 | 動作 |
|---|---|
| 最終更新（グレー表示） | 前回の更新結果を表示 |
| 今すぐ更新 | 即座に DNS 解決・hosts 更新を実行 |
| 設定を編集 | 設定ウィンドウを開く |
| 設定ファイルを開く | `config.yaml` をテキストエディターで開く |
| hosts ファイルを開く | `hosts` ファイルをテキストエディターで開く |
| ログを開く | `dynhosts.log` を開く |
| 終了 | アプリケーションを終了 |

> **ヒント**: トレイアイコンをシングルクリックしても設定ウィンドウが開きます。

## 設定ファイル（config.yaml）

```yaml
settings:
  update_interval: 3600        # 更新間隔（秒）。3600 = 1時間
  dns_server: ""               # カスタム DNS サーバー IP（空 = OS 既定）
  hosts_file: "C:\\Windows\\System32\\drivers\\etc\\hosts"
  backup: true                 # 更新前にバックアップを取る
  backup_count: 5              # バックアップの保持世代数

entries:
  - name: "dev.example.local"        # hosts に登録する短い名前
    alias: "dev-alb-xxxx.elb.amazonaws.com"  # DNS 解決する FQDN
    comment: "開発サーバー"           # 任意のコメント
    # enabled: false               # false にすると hosts への反映をスキップ
```

### フィールド説明

| フィールド | 必須 | 説明 |
|---|---|---|
| `name` | — | `hosts` ファイルに登録する短い名前 |
| `alias` | ✓ | DNS 解決する完全修飾ドメイン名（FQDN） |
| `comment` | — | `hosts` ファイルに記録するコメント |
| `enabled` | — | `false` にするとそのエントリーをスキップ（省略時は `true`） |

DNS に複数の IP が返ってきた場合は先頭の 1 件のみ登録します。

### hosts ファイルへの書き込み例

```
192.0.2.1    dev.example.local
```

## 設定 GUI

トレイアイコンをクリックすると設定ウィンドウが開きます。

### エントリー管理タブ

- **✓ 列をクリック** — そのエントリーの有効/無効を切り替え
- **ダブルクリック** — 編集ダイアログを開く
- **追加 / 編集 / 削除** — エントリーの管理
- **↑ / ↓** — 表示順の並び替え
- **保存して今すぐ更新** — 保存後に即座に hosts を更新

### 基本設定タブ

更新間隔、DNS サーバー、hosts ファイルのパス、バックアップ設定を変更できます。  
更新間隔の変更は保存直後から反映されます（稼働中のタイマーを即座にリセット）。

### スタートアップタブ

タスクスケジューラーへの登録状態を確認し、登録・削除を行えます。

## コマンドラインオプション

```
python main.py [オプション]

オプション:
  （なし）          システムトレイモードで起動
  --update          一度だけ hosts を更新して終了（タスクスケジューラー向け）
  --install         タスクスケジューラーとスタートメニューに登録
  --uninstall       タスクスケジューラーとスタートメニューから削除
  --no-elevate      管理者昇格をスキップ（テスト用）
```

## EXE 版の配布

Python がインストールされていない PC 向けに、単一 EXE にまとめて配布できます。

### ビルド（開発側）

Python と依存パッケージが入った環境で以下を実行します。

```powershell
.\build.ps1
```

| 出力 | 内容 |
|---|---|
| `dist\dynhosts\` | アプリ一式のフォルダ（`dynhosts.exe` + ランタイム） |
| `dist\dynhosts.zip` | 配布用 ZIP（上記フォルダ + `config.yaml.example` + README） |

手動でビルドする場合は `pip install -r requirements.txt pyinstaller` のうえ `python make_icon.py` と `pyinstaller dynhosts.spec --noconfirm` を実行してください。

> ビルドは onedir 形式（フォルダ配布）です。単一 EXE（onefile）形式は自己展開構造が
> アンチウイルスのヒューリスティック検知（例: `Trojan:Win32/Bearfoos.A!ml`）に
> 誤検知されやすいため採用していません。

### 利用（配布先の PC）

1. ZIP を任意の**書き込み可能な場所**に展開します（`config.yaml`・ログ・バックアップが EXE と同じフォルダに作られるため、`Program Files` 直下は避けてください）
2. `dynhosts` フォルダ内の `dynhosts.exe` をダブルクリックして起動します（UAC ダイアログが表示されます）
   - 初回起動時に既定の `config.yaml` が自動生成され、設定画面が開きます
3. 自動起動・定期更新を使う場合は、設定画面の「スタートアップ」タブから登録します（EXE のパスでタスクスケジューラーに登録されます）

コマンドラインオプション（`--update` / `--install` / `--uninstall`）は Python 版と同じです。EXE はコンソール非表示のため、実行結果は `dynhosts.log` で確認してください。

> **注意**: 署名のない EXE のため、ダウンロード直後は SmartScreen の警告が表示されることがあります（「詳細情報」→「実行」で起動できます）。それでもアンチウイルスに誤検知される場合は、[Microsoft への誤検知報告](https://www.microsoft.com/en-us/wdsi/filesubmission)を行うか、コード署名の導入を検討してください。

## ファイル構成

```
dynhosts/
├── main.py           # エントリーポイント・トレイ UI・タスクスケジューラー登録
├── core.py           # DNS 解決・hosts ファイル読み書き・バックアップ
├── settings_gui.py   # 設定 GUI ウィンドウ（tkinter）
├── config.yaml       # 設定ファイル（エントリー一覧・動作設定）
├── requirements.txt  # 依存パッケージ
├── install.ps1       # セットアップスクリプト
├── dynhosts.spec     # PyInstaller ビルド定義
├── build.ps1         # EXE ビルドスクリプト
└── dynhosts.log # 実行ログ（自動生成）
```

## ライセンス

MIT License
