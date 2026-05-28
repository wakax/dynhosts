"""
dynhosts / settings_gui.py
設定 GUI ウィンドウ（tkinter ベース・追加依存なし）
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Callable

import yaml


# ---------------------------------------------------------------------------
# config.yaml 書き出し（コメント付き）
# ---------------------------------------------------------------------------

def _q(s: str) -> str:
    """YAML ダブルクォート用エスケープ"""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def save_config(config_path: Path, cfg: dict) -> None:
    """設定をコメント付きで config.yaml に書き出す"""
    s = cfg.get("settings", {})
    entries = cfg.get("entries", [])

    lines = [
        "# =============================================================================",
        "# dynhosts 設定ファイル",
        "# =============================================================================",
        "# このファイルを編集して管理したい エントリーを登録してください。",
        "# 変更後はシステムトレイの「今すぐ更新」またはツールの再起動で反映されます。",
        "",
        "settings:",
        "  # hostsファイルの更新間隔（秒）",
        "  # 3600 = 1時間 / 86400 = 1日",
        f"  update_interval: {int(s.get('update_interval', 3600))}",
        "",
        "  # カスタム DNS サーバーの IP アドレス（空文字 = OS 既定の DNS を使用）",
        '  # 例: "192.168.1.1"  /  "8.8.8.8"',
        f'  dns_server: "{_q(str(s.get("dns_server", "") or ""))}"',
        "",
        "  # hostsファイルのパス（通常は変更不要）",
        f'  hosts_file: "{_q(str(s.get("hosts_file", r"C:\Windows\System32\drivers\etc\hosts")))}"',
        "",
        "  # 更新前にバックアップを取るか",
        f"  backup: {'true' if s.get('backup', True) else 'false'}",
        "",
        "  # バックアップの保持世代数",
        f"  backup_count: {int(s.get('backup_count', 5))}",
        "",
        "# =============================================================================",
        "# 管理エントリー一覧",
        "# =============================================================================",
        "# alias   : DNS 解決する完全修飾ドメイン名（必須）",
        "# name    : hosts に一緒に登録する短い名前（省略可）",
        "# comment : hosts ファイル内に記録するコメント（省略可）",
        "# enabled : false にすると hosts への反映をスキップ（省略時は true）",
        "#",
        "# ※ DNS に複数の IP が返ってきた場合は先頭の 1 件のみ登録します。",
        "# =============================================================================",
        "",
        "entries:",
    ]

    if not entries:
        lines.append("  []")
    else:
        for e in entries:
            lines.append(f'  - name: "{_q(e.get("name", ""))}"')
            lines.append(f'    alias: "{_q(e.get("alias", ""))}"')
            if e.get("comment"):
                lines.append(f'    comment: "{_q(e.get("comment", ""))}"')
            if not e.get("enabled", True):
                lines.append( "    enabled: false")
            lines.append("")

    config_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# エントリー追加・編集ダイアログ
# ---------------------------------------------------------------------------

class EntryDialog:
    """エントリーの追加・編集モーダルダイアログ"""

    def __init__(self, parent, entry: dict | None = None):
        import tkinter as tk
        from tkinter import ttk, messagebox

        self.result: dict | None = None
        is_edit = entry is not None
        entry = entry or {}

        top = tk.Toplevel(parent)
        top.title("エントリーの編集" if is_edit else "エントリーの追加")
        top.resizable(True, True)
        top.minsize(560, 280)
        top.grab_set()
        top.transient(parent)

        f = ttk.Frame(top, padding=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text="名前 (name) ─ hosts に登録する短い名前:").grid(
            row=0, column=0, sticky="w", pady=4)
        name_var = tk.StringVar(value=entry.get("name", ""))
        name_w = ttk.Entry(f, textvariable=name_var)
        name_w.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(f, text="別名 (alias) ─ DNS 解決する FQDN（必須）:").grid(
            row=2, column=0, sticky="w", pady=4)
        alias_var = tk.StringVar(value=entry.get("alias", ""))
        ttk.Entry(f, textvariable=alias_var).grid(
            row=3, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(f, text="コメント:").grid(row=4, column=0, sticky="w", pady=4)
        comment_var = tk.StringVar(value=entry.get("comment", ""))
        ttk.Entry(f, textvariable=comment_var).grid(
            row=5, column=0, sticky="ew", pady=(0, 14))

        btn_f = ttk.Frame(f)
        btn_f.grid(row=6, column=0, sticky="e")

        def ok():
            alias = alias_var.get().strip()
            if not alias:
                messagebox.showwarning("入力エラー", "alias (FQDN) は必須です。", parent=top)
                return
            self.result = {
                "name":    name_var.get().strip(),
                "alias":   alias,
                "comment": comment_var.get().strip(),
            }
            top.destroy()

        ttk.Button(btn_f, text="キャンセル", command=top.destroy, width=10).pack(
            side="right", padx=(6, 0))
        ttk.Button(btn_f, text="OK", command=ok, width=8).pack(side="right")

        # プライマリースクリーン中央に配置
        top.update_idletasks()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        w  = top.winfo_width()
        h  = top.winfo_height()
        top.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

        name_w.focus_set()
        top.bind("<Return>", lambda _: ok())
        top.bind("<Escape>", lambda _: top.destroy())
        parent.wait_window(top)


# ---------------------------------------------------------------------------
# メイン設定ウィンドウ
# ---------------------------------------------------------------------------

# チェックボックス列の表示文字
_CHECK_ON  = "✓"
_CHECK_OFF = ""


class SettingsWindow:
    """タブ付き設定ウィンドウ（エントリー管理が先頭タブ）"""

    def __init__(self, config_path: Path, on_save: Callable | None = None):
        import tkinter as tk
        from tkinter import ttk

        self._config_path = config_path
        self._on_save = on_save
        self._cfg = self._load()
        self._entries: list[dict] = copy.deepcopy(self._cfg.get("entries", []))

        self._root = tk.Tk()
        self._root.title("dynhosts 設定")
        self._root.minsize(720, 440)
        self._root.resizable(True, True)

        self._build(tk, ttk)
        self._center()

    # ------------------------------------------------------------------

    def _build_tab_startup(self, nb, ttk, tk):
        """タスクスケジューラー・スタートメニュー登録タブ"""
        import subprocess, os

        tab = ttk.Frame(nb, padding=20)
        nb.add(tab, text="  スタートアップ  ")
        tab.columnconfigure(1, weight=1)

        # 登録対象の定義
        def _task_exists(name: str) -> bool:
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", name],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return r.returncode == 0

        def _shortcut_exists() -> bool:
            lnk = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows"
                   / "Start Menu" / "Programs" / "dynhosts.lnk")
            return lnk.exists()

        items = [
            {
                "label":     "ログオン時の自動起動",
                "desc":      "サインイン時にシステムトレイを自動起動します",
                "check":     lambda: _task_exists("dynhosts-tray"),
                "install":   "install_tray_task",
                "uninstall": "uninstall_tray_task",
            },
            {
                "label":     "定期自動更新タスク",
                "desc":      "タスクスケジューラーで定期的に hosts を更新します",
                "check":     lambda: _task_exists("dynhosts-auto-update"),
                "install":   "install_task_scheduler",
                "uninstall": "uninstall_task_scheduler",
            },
            {
                "label":     "スタートメニューのショートカット",
                "desc":      "スタートメニューから手動で起動できるようにします",
                "check":     _shortcut_exists,
                "install":   "install_start_menu",
                "uninstall": "uninstall_start_menu",
            },
        ]

        status_vars: list[tk.StringVar] = []

        for i, it in enumerate(items):
            # ラベル列
            ttk.Label(tab, text=it["label"] + ":").grid(
                row=i * 2, column=0, sticky="w", padx=(0, 16), pady=(10, 0))
            ttk.Label(tab, text=it["desc"], foreground="gray").grid(
                row=i * 2 + 1, column=0, sticky="w", padx=(0, 16), pady=(0, 4))

            # 状態表示
            sv = tk.StringVar()
            status_vars.append(sv)
            ttk.Label(tab, textvariable=sv, width=10).grid(
                row=i * 2, column=1, sticky="w", pady=(10, 0))

            # 登録・削除ボタン
            bf = ttk.Frame(tab)
            bf.grid(row=i * 2, column=2, rowspan=2, sticky="e", padx=(8, 0))

            def _make_op(entry, idx, do_install: bool):
                def _op():
                    from tkinter import messagebox
                    try:
                        import main as _m
                        fn_name = entry["install"] if do_install else entry["uninstall"]
                        getattr(_m, fn_name)()
                    except Exception as e:
                        messagebox.showerror("エラー", str(e), parent=self._root)
                        return
                    # 実際の状態で表示を更新
                    registered = entry["check"]()
                    status_vars[idx].set("登録済み ✓" if registered else "未登録")
                return _op

            ttk.Button(bf, text="登録", width=6,
                       command=_make_op(it, i, True)).pack(side="left", padx=(0, 4))
            ttk.Button(bf, text="削除", width=6,
                       command=_make_op(it, i, False)).pack(side="left")

        # 初期状態を反映
        def _refresh():
            for idx, it in enumerate(items):
                registered = it["check"]()
                status_vars[idx].set("登録済み ✓" if registered else "未登録")

        _refresh()

    # ------------------------------------------------------------------

    def _center(self):
        """プライマリースクリーンの中央にウィンドウを配置する"""
        self._root.update_idletasks()
        w  = self._root.winfo_width()
        h  = self._root.winfo_height()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self._root.geometry(f"+{x}+{y}")

    def _load(self) -> dict:
        with open(self._config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _build(self, tk, ttk):
        from tkinter import filedialog, messagebox

        root = self._root
        s = self._cfg.get("settings", {})

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        # ── Tab 1: エントリー管理 ─────────────────────────────────────
        tab1 = ttk.Frame(nb, padding=8)
        nb.add(tab1, text="  エントリー管理  ")
        tab1.rowconfigure(0, weight=1)
        tab1.columnconfigure(0, weight=1)

        tree_frame = ttk.Frame(tab1)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        cols = ("enabled", "name", "alias", "comment")
        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            height=12, selectmode="browse")
        self._tree.heading("enabled", text="有効",              anchor="center")
        self._tree.heading("name",    text="名前 (name)",       anchor="w")
        self._tree.heading("alias",   text="別名 (alias) ─ FQDN", anchor="w")
        self._tree.heading("comment", text="コメント",          anchor="w")
        self._tree.column("enabled", width=44,  minwidth=44,  stretch=False, anchor="center")
        self._tree.column("name",    width=180, minwidth=80)
        self._tree.column("alias",   width=320, minwidth=160)
        self._tree.column("comment", width=140, minwidth=60)
        self._tree.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # クリック: 有効列ならトグル、それ以外はダブルクリックで編集
        self._tree.bind("<Button-1>",  self._on_click)
        self._tree.bind("<Double-1>",  self._on_double_click)

        btn_bar = ttk.Frame(tab1)
        btn_bar.grid(row=1, column=0, sticky="w", pady=(6, 0))
        for text, cmd, w in [
            ("追加",   self._add_entry,    6),
            ("編集",   self._edit_entry,   6),
            ("削除",   self._delete_entry, 6),
            ("↑",     self._move_up,      4),
            ("↓",     self._move_down,    4),
        ]:
            ttk.Button(btn_bar, text=text, command=cmd, width=w).pack(
                side="left", padx=2)

        self._refresh_tree()

        # ── Tab 2: 基本設定 ──────────────────────────────────────────
        tab2 = ttk.Frame(nb, padding=16)
        nb.add(tab2, text="  基本設定  ")
        tab2.columnconfigure(1, weight=1)

        def lbl(row, text):
            ttk.Label(tab2, text=text).grid(
                row=row, column=0, sticky="w", padx=(0, 14), pady=5)

        lbl(0, "更新間隔（秒）:")
        self._interval = ttk.Entry(tab2, width=10)
        self._interval.insert(0, str(s.get("update_interval", 3600)))
        self._interval.grid(row=0, column=1, sticky="w", pady=5)

        lbl(1, "DNS サーバー（空 = OS 既定）:")
        self._dns = ttk.Entry(tab2, width=22)
        self._dns.insert(0, s.get("dns_server", "") or "")
        self._dns.grid(row=1, column=1, sticky="w", pady=5)

        lbl(2, "hosts ファイルのパス:")
        hf_frame = ttk.Frame(tab2)
        hf_frame.grid(row=2, column=1, sticky="ew", pady=5)
        hf_frame.columnconfigure(0, weight=1)
        self._hosts_file = ttk.Entry(hf_frame)
        self._hosts_file.insert(
            0, s.get("hosts_file", r"C:\Windows\System32\drivers\etc\hosts"))
        self._hosts_file.grid(row=0, column=0, sticky="ew")
        ttk.Button(hf_frame, text="参照…", width=6,
                   command=lambda: self._browse_hosts(filedialog)).grid(
                       row=0, column=1, padx=(4, 0))

        self._backup_var = tk.BooleanVar(value=bool(s.get("backup", True)))
        ttk.Checkbutton(tab2, text="更新前にバックアップを取る",
                        variable=self._backup_var).grid(
                            row=3, column=0, columnspan=2, sticky="w", pady=5)

        lbl(4, "バックアップ保持世代数:")
        self._backup_count = ttk.Entry(tab2, width=8)
        self._backup_count.insert(0, str(s.get("backup_count", 5)))
        self._backup_count.grid(row=4, column=1, sticky="w", pady=5)

        # ── Tab 3: スタートアップ ─────────────────────────────────────
        self._build_tab_startup(nb, ttk, tk)

        # ── 下部ボタン ──────────────────────────────────────────────
        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=8)
        bottom = ttk.Frame(root, padding=(8, 6, 8, 8))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="キャンセル",
                   command=root.destroy, width=10).pack(side="left")
        ttk.Button(bottom, text="保存して今すぐ更新",
                   command=self._save_and_update, width=16).pack(
                       side="right", padx=(4, 0))
        ttk.Button(bottom, text="保存",
                   command=self._save, width=8).pack(side="right")

    # ------------------------------------------------------------------
    # ツリー操作

    def _refresh_tree(self):
        sel = self._selected_index()
        self._tree.delete(*self._tree.get_children())
        for e in self._entries:
            enabled = e.get("enabled", True)
            self._tree.insert("", "end", values=(
                _CHECK_ON if enabled else _CHECK_OFF,
                e.get("name", ""),
                e.get("alias", ""),
                e.get("comment", ""),
            ))
        # 選択を復元
        children = self._tree.get_children()
        if sel is not None and sel < len(children):
            self._tree.selection_set(children[sel])

    def _selected_index(self) -> int | None:
        sel = self._tree.selection()
        return self._tree.index(sel[0]) if sel else None

    def _on_click(self, event):
        """有効列（#1）クリックで enabled をトグル"""
        region = self._tree.identify("region", event.x, event.y)
        col    = self._tree.identify_column(event.x)
        row_id = self._tree.identify_row(event.y)
        if region == "cell" and col == "#1" and row_id:
            idx = self._tree.index(row_id)
            self._entries[idx]["enabled"] = not self._entries[idx].get("enabled", True)
            self._refresh_tree()

    def _on_double_click(self, event):
        """有効列以外のダブルクリックで編集ダイアログを開く"""
        col = self._tree.identify_column(event.x)
        if col != "#1":
            self._edit_entry()

    def _add_entry(self):
        dlg = EntryDialog(self._root)
        if dlg.result:
            dlg.result.setdefault("enabled", True)
            self._entries.append(dlg.result)
            self._refresh_tree()

    def _edit_entry(self):
        idx = self._selected_index()
        if idx is None:
            return
        dlg = EntryDialog(self._root, self._entries[idx])
        if dlg.result:
            # enabled フラグは編集ダイアログで変更しないので引き継ぐ
            dlg.result["enabled"] = self._entries[idx].get("enabled", True)
            self._entries[idx] = dlg.result
            self._refresh_tree()

    def _delete_entry(self):
        from tkinter import messagebox
        idx = self._selected_index()
        if idx is None:
            return
        label = self._entries[idx].get("name") or self._entries[idx].get("alias", "")
        if messagebox.askyesno("削除確認", f"「{label}」を削除しますか？",
                               parent=self._root):
            del self._entries[idx]
            self._refresh_tree()

    def _move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return
        self._entries[idx - 1], self._entries[idx] = (
            self._entries[idx], self._entries[idx - 1])
        self._refresh_tree()
        self._tree.selection_set(self._tree.get_children()[idx - 1])

    def _move_down(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self._entries) - 1:
            return
        self._entries[idx], self._entries[idx + 1] = (
            self._entries[idx + 1], self._entries[idx])
        self._refresh_tree()
        self._tree.selection_set(self._tree.get_children()[idx + 1])

    def _browse_hosts(self, filedialog):
        path = filedialog.askopenfilename(
            title="hosts ファイルを選択", parent=self._root)
        if path:
            self._hosts_file.delete(0, "end")
            self._hosts_file.insert(0, path)

    # ------------------------------------------------------------------
    # 保存

    def _collect(self) -> dict | None:
        from tkinter import messagebox
        try:
            interval = int(self._interval.get().strip())
        except ValueError:
            messagebox.showerror("入力エラー", "更新間隔は整数で入力してください。",
                                 parent=self._root)
            return None
        try:
            backup_count = int(self._backup_count.get().strip())
        except ValueError:
            messagebox.showerror("入力エラー", "バックアップ保持世代数は整数で入力してください。",
                                 parent=self._root)
            return None

        cfg = copy.deepcopy(self._cfg)
        cfg["settings"] = {
            "update_interval": interval,
            "dns_server":      self._dns.get().strip() or "",
            "hosts_file":      self._hosts_file.get().strip(),
            "backup":          bool(self._backup_var.get()),
            "backup_count":    backup_count,
        }
        cfg["entries"] = copy.deepcopy(self._entries)
        return cfg

    def _save(self, and_update: bool = False):
        from tkinter import messagebox
        cfg = self._collect()
        if cfg is None:
            return
        save_config(self._config_path, cfg)
        logging.info("設定を保存しました: %s", self._config_path)
        if self._on_save:
            self._on_save(update=and_update)
        if not and_update:
            messagebox.showinfo("保存完了", "設定を保存しました。", parent=self._root)
        self._root.destroy()

    def _save_and_update(self):
        self._save(and_update=True)

    def run(self):
        self._root.mainloop()


# ---------------------------------------------------------------------------
# 公開エントリーポイント
# ---------------------------------------------------------------------------

def open_settings(config_path: Path, on_save: Callable | None = None) -> None:
    """設定ウィンドウを開く（別スレッドからの呼び出し可）"""
    try:
        SettingsWindow(config_path, on_save=on_save).run()
    except Exception as exc:
        logging.error("設定ウィンドウでエラー: %s", exc)
