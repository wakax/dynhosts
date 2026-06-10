"""
dynhosts / main.py
システムトレイアプリケーション + CLI エントリーポイント

使い方:
    python main.py           # システムトレイで起動
    python main.py --update  # 一度だけ更新して終了（タスクスケジューラ向け）
    python main.py --install # Windowsタスクスケジューラに登録
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 管理者権限チェック・昇格
# ---------------------------------------------------------------------------

def set_dpi_awareness() -> None:
    """Hi-DPI ディスプレイでの文字ぼやけを防ぐ。
    Per-Monitor DPI Aware (v2) を試み、失敗時は System DPI Aware にフォールバックする。
    UI を生成する前に呼び出すこと。
    """
    try:
        # Windows 10 Creators Update (1703) 以降: Per-Monitor v2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            # Windows Vista 以降のフォールバック
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_instance_mutex = None  # プロセス終了まで保持（GC 防止）


def acquire_instance_lock() -> bool:
    """
    名前付きミューテックスで二重起動を防ぐ（トレイモード専用）。
    ロック取得成功 → True、既に起動中 → False。
    """
    global _instance_mutex
    _instance_mutex = ctypes.windll.kernel32.CreateMutexW(
        None, False, "Global\\dynhosts-tray"
    )
    # ERROR_ALREADY_EXISTS (183) が返れば別インスタンスが存在する
    return ctypes.windll.kernel32.GetLastError() != 183


def is_admin() -> bool:
    """現在のプロセスが管理者権限で動作しているか確認"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_and_restart() -> None:
    """UAC ダイアログを表示して管理者権限で再起動する"""
    params = " ".join([f'"{a}"' for a in sys.argv[1:]])
    if IS_FROZEN:
        # EXE 化時は sys.executable が自分自身なのでスクリプトパスを渡さない
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
    else:
        script = str(Path(__file__).resolve())
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', None, 1
        )
    sys.exit(0)


# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------

# PyInstaller 等で EXE 化されているか
IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    # onefile 形式では __file__ が一時展開フォルダ(_MEIPASS)を指すため、
    # config.yaml / ログは EXE 本体の隣に置く
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_PATH    = BASE_DIR / "dynhosts.log"


def get_launch_command(extra_args: str = "") -> tuple[str, str]:
    """
    タスクスケジューラ・ショートカット登録用の (実行ファイル, 引数) を返す。
    EXE 化時は EXE 自身、スクリプト実行時は pythonw.exe + main.py。
    """
    if IS_FROZEN:
        return sys.executable, extra_args
    # pythonw.exe はコンソールウィンドウを表示しない Windows 専用実行ファイル
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    python_exe = str(pythonw) if pythonw.exists() else sys.executable
    script_path = str(Path(__file__).resolve())
    args = f'"{script_path}"' + (f" {extra_args}" if extra_args else "")
    return python_exe, args


# ---------------------------------------------------------------------------
# ロギング初期化
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    # Windows コンソールのエンコードを UTF-8 に統一（cp932 による文字化け・クラッシュ防止）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # windowed EXE（--noconsole）では sys.stdout が None になるためファイルのみに出力
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# コアモジュールのインポート（インストール前でも起動できるよう遅延）
# ---------------------------------------------------------------------------

def import_core():
    try:
        import core  # type: ignore
        return core
    except ImportError as exc:
        logging.error("core.py が見つかりません: %s", exc)
        raise


def import_yaml():
    try:
        import yaml  # type: ignore
        return yaml
    except ImportError:
        logging.error(
            "PyYAML がインストールされていません。"
            "  pip install pyyaml  を実行してください。"
        )
        raise


# ---------------------------------------------------------------------------
# 更新処理
# ---------------------------------------------------------------------------

_update_lock = threading.Lock()
_last_result: dict = {"time": None, "success": 0, "failure": 0, "error": None}


def run_update() -> None:
    """hostsファイルを更新する（スレッドセーフ）"""
    if not _update_lock.acquire(blocking=False):
        logging.info("更新処理が既に実行中です。スキップします。")
        return

    try:
        core = import_core()
        yaml = import_yaml()

        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {CONFIG_PATH}")

        config = core.load_config(str(CONFIG_PATH))
        success, failure = core.update_hosts_file(config)

        _last_result.update({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "success": success,
            "failure": failure,
            "error": None,
        })
        logging.info("更新完了 — 成功: %d, 失敗: %d", success, failure)

    except Exception as exc:
        _last_result["error"] = str(exc)
        logging.error("更新エラー: %s", exc)
    finally:
        _update_lock.release()


# ---------------------------------------------------------------------------
# 自動更新スレッド
# ---------------------------------------------------------------------------

_stop_event   = threading.Event()
_wakeup_event = threading.Event()  # 待機を即座に中断するための割り込みイベント


def auto_update_loop(interval_seconds: int) -> None:
    """指定間隔で hostsファイルを自動更新するバックグラウンドスレッド"""
    current_interval = interval_seconds
    logging.info("自動更新スレッド開始 (間隔: %d 秒)", current_interval)

    while True:
        _wakeup_event.clear()
        # タイムアウト: True=自然に時間切れ、False=外部から叩き起こされた
        timed_out = not _wakeup_event.wait(timeout=current_interval)

        if _stop_event.is_set():
            break

        if timed_out:
            logging.info("自動更新を実行します...")
            run_update()

        # 毎サイクル後に設定ファイルから最新の間隔を読み込む
        try:
            _core = import_core()
            if CONFIG_PATH.exists():
                _cfg = _core.load_config(str(CONFIG_PATH))
                new_interval = _core.get_setting(
                    _cfg, "update_interval", interval_seconds)
                if new_interval != current_interval:
                    logging.info(
                        "更新間隔を変更: %d秒 → %d秒", current_interval, new_interval)
                    current_interval = new_interval
        except Exception:
            pass

    logging.info("自動更新スレッド停止")


# ---------------------------------------------------------------------------
# システムトレイ
# ---------------------------------------------------------------------------

def build_icon_image():
    """PIL で小さなトレイアイコン画像を生成する"""
    from PIL import Image, ImageDraw  # type: ignore

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景円（濃い青）
    draw.ellipse([2, 2, size - 2, size - 2], fill=(30, 80, 160, 255))
    # "H" 文字（白）
    lw = 6
    draw.rectangle([14, 14, 14 + lw, size - 14], fill="white")
    draw.rectangle([size - 14 - lw, 14, size - 14, size - 14], fill="white")
    draw.rectangle([14, size // 2 - lw // 2, size - 14, size // 2 + lw // 2], fill="white")

    return img


def get_menu_title(_item=None) -> str:
    r = _last_result
    if r["time"]:
        status = f"成功:{r['success']} 失敗:{r['failure']}"
        return f"最終更新 {r['time']} ({status})"
    return "dynhosts"


def create_tray(interval_seconds: int):
    """pystray を使ってシステムトレイアイコンを作成・起動する"""
    try:
        import pystray  # type: ignore
        from pystray import MenuItem as item  # type: ignore
    except ImportError:
        logging.error(
            "pystray がインストールされていません。\n"
            "  pip install pystray pillow  を実行してください。"
        )
        sys.exit(1)

    # アイコンへの参照（コールバック内から再構築するため list で保持）
    _icon_ref: list = []

    # ----------------------------------------------------------------
    # コールバック定義
    # ----------------------------------------------------------------

    def on_update_now(icon, _item):
        icon.notify("hostsファイルを更新中...", "dynhosts")
        threading.Thread(target=run_update, daemon=True).start()

    def on_open_config(icon, _item):
        os.startfile(str(CONFIG_PATH))

    def on_open_log(icon, _item):
        os.startfile(str(LOG_PATH))

    def on_open_hosts(icon, _item):
        import core as c  # type: ignore
        cfg = c.load_config(str(CONFIG_PATH))
        hosts_path = c.get_setting(cfg, "hosts_file", r"C:\Windows\System32\drivers\etc\hosts")
        os.startfile(hosts_path)

    def on_exit(icon, _item):
        logging.info("アプリケーションを終了します。")
        _stop_event.set()
        _wakeup_event.set()  # 待機中のループを即座に終了させる
        icon.stop()

    def _on_save(update: bool = False):
        """設定保存後の共通処理（メニュー再構築・タイマーリセット・任意で即時更新）"""
        if _icon_ref:
            _icon_ref[0].menu = _build_menu()
            _icon_ref[0].update_menu()
        _wakeup_event.set()
        if update and _icon_ref:
            _icon_ref[0].notify("hostsファイルを更新中...", "dynhosts")
            threading.Thread(target=run_update, daemon=True).start()

    def _open_settings_window():
        try:
            from settings_gui import open_settings  # type: ignore
        except ImportError as exc:
            logging.error("settings_gui が見つかりません: %s", exc)
            return
        open_settings(CONFIG_PATH, on_save=_on_save)

    def on_open_settings(_icon, _item):
        threading.Thread(target=_open_settings_window, daemon=True).start()

    # ----------------------------------------------------------------
    # メニュー構築ヘルパー（保存後の再構築でも呼び出す）
    # ----------------------------------------------------------------

    def _build_menu():
        return pystray.Menu(
            item(get_menu_title,       None,             enabled=False),
            pystray.Menu.SEPARATOR,
            item("今すぐ更新",         on_update_now),
            item("設定を編集",         on_open_settings, default=True),
            pystray.Menu.SEPARATOR,
            item("設定ファイルを開く", on_open_config),
            item("hostsファイルを開く", on_open_hosts),
            item("ログを開く",         on_open_log),
            pystray.Menu.SEPARATOR,
            item("終了",               on_exit),
        )

    # ----------------------------------------------------------------
    # アイコン作成・スレッド起動
    # ----------------------------------------------------------------

    icon = pystray.Icon(
        "dynhosts",
        build_icon_image(),
        "dynhosts",
        _build_menu(),
    )
    _icon_ref.append(icon)

    # 初回更新（バックグラウンド）
    threading.Thread(target=run_update, daemon=True).start()

    # 自動更新スレッドを起動
    threading.Thread(
        target=auto_update_loop, args=(interval_seconds,), daemon=True
    ).start()

    # 起動時に設定画面を表示
    threading.Thread(target=_open_settings_window, daemon=True).start()

    logging.info("システムトレイアイコンを起動しました。")
    icon.run()


# ---------------------------------------------------------------------------
# タスクスケジューラ登録
# ---------------------------------------------------------------------------

TASK_NAME      = "dynhosts-auto-update"
TRAY_TASK_NAME = "dynhosts-tray"


def install_task_scheduler() -> None:
    """Windows タスクスケジューラにアップデートタスクを登録する"""
    command, arguments = get_launch_command("--update")
    interval_min = 60  # デフォルト60分

    # 設定ファイルから間隔を読み込む
    try:
        import yaml  # type: ignore
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
            sec = cfg.get("settings", {}).get("update_interval", 3600)
            interval_min = max(1, sec // 60)
    except Exception:
        pass

    xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{interval_min}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2000-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{command}"</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{BASE_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    xml_path = BASE_DIR / "task_definition.xml"
    xml_path.write_text(xml_content, encoding="utf-16")

    try:
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            logging.info("タスクスケジューラへの登録が完了しました: %s (更新間隔: %d 分)",
                         TASK_NAME, interval_min)
        else:
            logging.error("タスク登録失敗:\n%s", result.stderr)
    finally:
        xml_path.unlink(missing_ok=True)


def uninstall_task_scheduler() -> None:
    """タスクスケジューラからタスクを削除する"""
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        logging.info("タスクを削除しました: %s", TASK_NAME)
    else:
        logging.error("タスク削除失敗:\n%s", result.stderr)


def install_tray_task() -> None:
    """ログオン時にシステムトレイを管理者権限で自動起動するタスクを登録する"""
    command, arguments = get_launch_command()

    xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT10S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{command}"</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{BASE_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    xml_path = BASE_DIR / "tray_task_definition.xml"
    xml_path.write_text(xml_content, encoding="utf-16")

    try:
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TRAY_TASK_NAME, "/XML", str(xml_path), "/F"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            logging.info("ログオン時自動起動タスクを登録しました: %s", TRAY_TASK_NAME)
        else:
            logging.error("タスク登録失敗:\n%s", result.stderr)
    finally:
        xml_path.unlink(missing_ok=True)


def uninstall_tray_task() -> None:
    """タスクスケジューラからトレイ起動タスクを削除する"""
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TRAY_TASK_NAME, "/F"],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        logging.info("タスクを削除しました: %s", TRAY_TASK_NAME)
    else:
        logging.error("タスク削除失敗:\n%s", result.stderr)


# ---------------------------------------------------------------------------
# スタートメニュー ショートカット
# ---------------------------------------------------------------------------

SHORTCUT_NAME = "dynhosts.lnk"


def _start_menu_dir() -> Path:
    """現在のユーザーのスタートメニュー Programs フォルダを返す"""
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def install_start_menu() -> None:
    """スタートメニューに dynhosts のショートカットを作成する"""
    command, arguments = get_launch_command()
    lnk_path = _start_menu_dir() / SHORTCUT_NAME

    # WScript.Shell COM で .lnk を生成し、「管理者として実行」フラグを付ける
    ps_script = (
        f'$s = (New-Object -ComObject WScript.Shell).CreateShortcut("{lnk_path}");'
        f'$s.TargetPath = "{command}";'
        f'$s.Arguments = \'{arguments}\';'
        f'$s.WorkingDirectory = "{BASE_DIR}";'
        f'$s.Description = "dynhosts - hostsファイル自動更新ツール";'
        f'$s.Save();'
        # .lnk バイト 0x15 bit5 = RunAsAdministrator
        f'$b = [IO.File]::ReadAllBytes("{lnk_path}");'
        f'$b[0x15] = $b[0x15] -bor 0x20;'
        f'[IO.File]::WriteAllBytes("{lnk_path}", $b)'
    )

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        logging.info("スタートメニューにショートカットを作成しました: %s", lnk_path)
    else:
        logging.error("ショートカット作成失敗:\n%s", result.stderr)


def uninstall_start_menu() -> None:
    """スタートメニューのショートカットを削除する"""
    lnk_path = _start_menu_dir() / SHORTCUT_NAME
    if lnk_path.exists():
        lnk_path.unlink()
        logging.info("ショートカットを削除しました: %s", lnk_path)
    else:
        logging.info("ショートカットが見つかりません（スキップ）: %s", lnk_path)


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def main() -> None:
    set_dpi_awareness()   # UI 生成前に DPI 宣言（ぼやけ防止）
    setup_logging()

    # 初回起動時（EXE 配布直後など）は既定の設定ファイルを生成する
    if not CONFIG_PATH.exists():
        try:
            from settings_gui import save_config  # type: ignore
            save_config(CONFIG_PATH, {"settings": {}, "entries": []})
            logging.info("既定の設定ファイルを生成しました: %s", CONFIG_PATH)
        except Exception as exc:
            logging.warning("設定ファイルの生成に失敗: %s", exc)

    parser = argparse.ArgumentParser(
        description="dynhosts: FQDNをDNS解決してhostsファイルを自動更新するツール"
    )
    parser.add_argument("--update",   action="store_true", help="一度だけ更新して終了（タスクスケジューラ向け）")
    parser.add_argument("--install",  action="store_true", help="Windowsタスクスケジューラに登録")
    parser.add_argument("--uninstall",action="store_true", help="Windowsタスクスケジューラから削除")
    parser.add_argument("--no-elevate", action="store_true", help="管理者昇格をスキップ（テスト用）")
    args = parser.parse_args()

    # 管理者権限チェック
    if not args.no_elevate and not is_admin():
        logging.info("管理者権限がありません。UAC ダイアログを表示して再起動します...")
        elevate_and_restart()

    if args.install:
        install_task_scheduler()
        install_tray_task()
        install_start_menu()
        return

    if args.uninstall:
        uninstall_task_scheduler()
        uninstall_tray_task()
        uninstall_start_menu()
        return

    if args.update:
        # タスクスケジューラから起動されるモード（一度だけ更新して終了）
        run_update()
        r = _last_result
        sys.exit(1 if r.get("error") else 0)

    # --- システムトレイモード ---
    # 二重起動チェック（--update / --install などの非トレイモードは対象外）
    if not acquire_instance_lock():
        logging.info("既に起動中のインスタンスがあります。終了します。")
        sys.exit(0)

    # 設定から更新間隔を取得
    interval = 3600
    try:
        core = import_core()
        if CONFIG_PATH.exists():
            cfg = core.load_config(str(CONFIG_PATH))
            interval = core.get_setting(cfg, "update_interval", 3600)
    except Exception:
        pass

    create_tray(interval)


if __name__ == "__main__":
    main()
