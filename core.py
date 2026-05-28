"""
dynhosts / core.py
DNS名前解決 + hostsファイルのマーカーブロック管理ロジック
"""

from __future__ import annotations

import logging
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# hostsファイル内の管理ブロックを示すマーカー
MARKER_BEGIN = "# BEGIN dynhosts"
MARKER_END   = "# END dynhosts"

# ---------------------------------------------------------------------------
# 設定ファイル
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """YAML設定ファイルを読み込んで辞書を返す"""
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get_setting(config: dict, key: str, default=None):
    """config['settings'][key] を取得。なければ default を返す"""
    return config.get("settings", {}).get(key, default)


# ---------------------------------------------------------------------------
# DNS解決
# ---------------------------------------------------------------------------

def resolve_fqdn(fqdn: str, dns_server: Optional[str] = None) -> list[str]:
    """
    FQDNをDNS解決してIPアドレスの重複なしリストを返す。
    dns_server が指定された場合は dnspython を使用（未インストール時は警告して socket にフォールバック）。
    """
    ips: list[str] = []

    if dns_server:
        try:
            import dns.resolver  # type: ignore

            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = [dns_server]
            resolver.timeout = 5
            resolver.lifetime = 10

            for rdtype in ("A", "AAAA"):
                try:
                    answers = resolver.resolve(fqdn, rdtype)
                    for rdata in answers:
                        ip = str(rdata)
                        if ip not in ips:
                            ips.append(ip)
                except Exception:
                    pass  # NXDOMAIN / NoAnswer / Timeout は無視して次へ

            if ips:
                return ips
            # dns_server 指定でも解決できなかったとき socket にフォールバック
        except ImportError:
            logging.warning(
                "dnspython がインストールされていません。"
                "カスタム DNS サーバーは無視してシステム既定の DNS を使用します。"
                "  pip install dnspython"
            )

    # socket（システム既定 DNS）で解決
    try:
        results = socket.getaddrinfo(fqdn, None)
        seen: set[str] = set()
        for result in results:
            ip = result[4][0]
            if ip not in seen:
                seen.add(ip)
                ips.append(ip)
    except socket.gaierror as exc:
        logging.error("DNS解決失敗 %s: %s", fqdn, exc)

    return ips


# ---------------------------------------------------------------------------
# バックアップ
# ---------------------------------------------------------------------------

def create_backup(hosts_path: str, backup_count: int = 5) -> Path:
    """
    hostsファイルをタイムスタンプ付きでバックアップする。
    古いバックアップは backup_count 件を超えると自動削除。
    """
    src = Path(hosts_path)
    backup_dir = src.parent / "dynhosts_backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir / f"hosts_{timestamp}.bak"
    shutil.copy2(src, dst)
    logging.info("バックアップ作成: %s", dst)

    # 古いバックアップを世代管理
    backups = sorted(backup_dir.glob("hosts_*.bak"))
    while len(backups) > backup_count:
        backups.pop(0).unlink()

    return dst


# ---------------------------------------------------------------------------
# 管理ブロック構築
# ---------------------------------------------------------------------------

def build_managed_section(config: dict) -> tuple[str, int, int]:
    """
    設定に基づいて管理ブロックのテキストを構築する。

    Returns:
        (section_text, success_count, failure_count)
    """
    dns_server: Optional[str] = get_setting(config, "dns_server") or None

    lines: list[str] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(MARKER_BEGIN)
    lines.append("# 自動管理セクション - 手動編集は次回更新時に上書きされます")
    lines.append(f"# 最終更新: {timestamp}")
    lines.append("#")

    success = 0
    failure = 0

    for entry in config.get("entries", []):
        alias: str = entry["alias"]
        name: str  = entry.get("name", "") or ""
        comment: str = entry.get("comment", "")

        # enabled: false のエントリーはコメントとして残してスキップ
        if not entry.get("enabled", True):
            lines.append(f"# [無効] {alias}")
            logging.info("スキップ（無効）: %s", alias)
            continue

        ips = resolve_fqdn(alias, dns_server)

        if not ips:
            lines.append(f"# [警告] DNS解決失敗: {alias}")
            logging.warning("DNS解決失敗: %s", alias)
            failure += 1
            continue

        # 先頭の IP と name だけ登録
        ip = ips[0]
        parts = [ip, name] if name else [ip, alias]
        lines.append("\t".join(parts))
        logging.info("解決: %s -> %s", alias, ip)

        success += 1

    lines.append(MARKER_END)
    return "\n".join(lines), success, failure


# ---------------------------------------------------------------------------
# hostsファイル更新
# ---------------------------------------------------------------------------

def update_hosts_file(config: dict) -> tuple[int, int]:
    """
    hostsファイルの管理ブロックを最新 DNS 解決結果で置き換える。

    Returns:
        (success_count, failure_count)

    Raises:
        PermissionError: 管理者権限が不足している場合
        OSError:         その他のファイル操作エラー
    """
    hosts_path: str = get_setting(
        config, "hosts_file", r"C:\Windows\System32\drivers\etc\hosts"
    )
    do_backup: bool = get_setting(config, "backup", True)
    backup_count: int = get_setting(config, "backup_count", 5)

    # バックアップ
    if do_backup:
        try:
            create_backup(hosts_path, backup_count)
        except Exception as exc:
            logging.warning("バックアップ作成失敗（処理は続行）: %s", exc)

    # 既存 hosts ファイルを読み込む
    try:
        content = Path(hosts_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logging.error("hostsファイル読み込みエラー: %s", exc)
        raise

    # 管理ブロックを構築
    managed_section, success, failure = build_managed_section(config)

    # 既存の管理ブロックを除去し、それ以外の行を保持
    kept_lines: list[str] = []
    inside_managed = False
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if stripped == MARKER_BEGIN:
            inside_managed = True
            continue
        if stripped == MARKER_END:
            inside_managed = False
            continue
        if not inside_managed:
            kept_lines.append(raw_line)

    # 末尾の空行を整形して管理ブロックを追記
    base = "\n".join(kept_lines).rstrip()
    new_content = base + "\n\n" + managed_section + "\n"

    # ファイルに書き込む
    try:
        Path(hosts_path).write_text(new_content, encoding="utf-8")
    except PermissionError:
        logging.error(
            "hostsファイルへの書き込み権限がありません。"
            "管理者権限で実行してください。"
        )
        raise
    except OSError as exc:
        logging.error("hostsファイル書き込みエラー: %s", exc)
        raise

    logging.info(
        "hostsファイルを更新しました: %s  (成功: %d, 失敗: %d)",
        hosts_path, success, failure,
    )
    return success, failure
