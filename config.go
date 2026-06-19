package main

import (
	"fmt"
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

type Entry struct {
	Name    string `yaml:"name"`
	Alias   string `yaml:"alias"`
	Comment string `yaml:"comment,omitempty"`
	Enabled *bool  `yaml:"enabled,omitempty"`
}

func (e *Entry) IsEnabled() bool {
	return e.Enabled == nil || *e.Enabled
}

func (e Entry) Clone() Entry {
	cloned := e
	if e.Enabled != nil {
		b := *e.Enabled
		cloned.Enabled = &b
	}
	return cloned
}

type Settings struct {
	UpdateInterval int    `yaml:"update_interval"`
	DNSServer      string `yaml:"dns_server"`
	HostsFile      string `yaml:"hosts_file"`
	Backup         bool   `yaml:"backup"`
	BackupCount    int    `yaml:"backup_count"`
}

type Config struct {
	Settings Settings `yaml:"settings"`
	Entries  []Entry  `yaml:"entries"`
}

func DefaultConfig() Config {
	return Config{
		Settings: Settings{
			UpdateInterval: 3600,
			HostsFile:      `C:\Windows\System32\drivers\etc\hosts`,
			Backup:         true,
			BackupCount:    5,
		},
		Entries: []Entry{},
	}
}

func LoadConfig(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return DefaultConfig(), err
	}

	cfg := DefaultConfig()
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return DefaultConfig(), err
	}

	if cfg.Settings.UpdateInterval <= 0 {
		cfg.Settings.UpdateInterval = 3600
	}
	if cfg.Settings.HostsFile == "" {
		cfg.Settings.HostsFile = `C:\Windows\System32\drivers\etc\hosts`
	}
	if cfg.Settings.BackupCount <= 0 {
		cfg.Settings.BackupCount = 5
	}
	if cfg.Entries == nil {
		cfg.Entries = []Entry{}
	}

	return cfg, nil
}

func yamlEscape(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, `"`, `\"`)
	return s
}

func SaveConfig(path string, cfg Config) error {
	s := cfg.Settings

	lines := []string{
		"# =============================================================================",
		"# dynhosts 設定ファイル",
		"# =============================================================================",
		"# このファイルを編集して管理したい エントリーを登録してください。",
		"# 変更後はシステムトレイの「今すぐ更新」またはツールの再起動で反映されます。",
		"",
		"settings:",
		"  # hostsファイルの更新間隔（秒）",
		"  # 3600 = 1時間 / 86400 = 1日",
		fmt.Sprintf("  update_interval: %d", s.UpdateInterval),
		"",
		"  # カスタム DNS サーバーの IP アドレス（空文字 = OS 既定の DNS を使用）",
		`  # 例: "192.168.1.1"  /  "8.8.8.8"`,
		fmt.Sprintf(`  dns_server: "%s"`, yamlEscape(s.DNSServer)),
		"",
		"  # hostsファイルのパス（通常は変更不要）",
		fmt.Sprintf(`  hosts_file: "%s"`, yamlEscape(s.HostsFile)),
		"",
		"  # 更新前にバックアップを取るか",
		fmt.Sprintf("  backup: %v", s.Backup),
		"",
		"  # バックアップの保持世代数",
		fmt.Sprintf("  backup_count: %d", s.BackupCount),
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
	}

	if len(cfg.Entries) == 0 {
		lines = append(lines, "  []")
	} else {
		for _, e := range cfg.Entries {
			lines = append(lines, fmt.Sprintf(`  - name: "%s"`, yamlEscape(e.Name)))
			lines = append(lines, fmt.Sprintf(`    alias: "%s"`, yamlEscape(e.Alias)))
			if e.Comment != "" {
				lines = append(lines, fmt.Sprintf(`    comment: "%s"`, yamlEscape(e.Comment)))
			}
			if e.Enabled != nil && !*e.Enabled {
				lines = append(lines, "    enabled: false")
			}
			lines = append(lines, "")
		}
	}

	return os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0644)
}
