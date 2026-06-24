package main

import (
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/miekg/dns"
)

const (
	markerBegin = "# BEGIN dynhosts"
	markerEnd   = "# END dynhosts"
)

// resolveFQDN は FQDN を DNS 解決して IP アドレスのリストを返す。
// dnsServer が空でない場合はそのサーバーに直接クエリを送り、失敗時はシステム DNS にフォールバックする。
func resolveFQDN(fqdn, dnsServer string) ([]string, error) {
	if dnsServer != "" {
		ips, err := resolveWithServer(fqdn, dnsServer)
		if err == nil && len(ips) > 0 {
			return ips, nil
		}
		log.Printf("カスタムDNS解決失敗 %s via %s: %v。システムDNSにフォールバック。", fqdn, dnsServer, err)
	}

	addrs, err := net.LookupHost(fqdn)
	if err != nil {
		return nil, fmt.Errorf("DNS解決失敗 %s: %w", fqdn, err)
	}
	return addrs, nil
}

func resolveWithServer(fqdn, server string) ([]string, error) {
	c := new(dns.Client)
	c.Timeout = 5 * time.Second

	if !strings.Contains(server, ":") {
		server = server + ":53"
	}

	var ips []string
	seen := map[string]bool{}

	for _, qtype := range []uint16{dns.TypeA, dns.TypeAAAA} {
		m := new(dns.Msg)
		m.SetQuestion(dns.Fqdn(fqdn), qtype)
		m.RecursionDesired = true

		r, _, err := c.Exchange(m, server)
		if err != nil {
			continue
		}
		for _, ans := range r.Answer {
			var ip string
			switch v := ans.(type) {
			case *dns.A:
				ip = v.A.String()
			case *dns.AAAA:
				ip = v.AAAA.String()
			}
			if ip != "" && !seen[ip] {
				seen[ip] = true
				ips = append(ips, ip)
			}
		}
	}

	if len(ips) == 0 {
		return nil, fmt.Errorf("no addresses returned from %s", server)
	}
	return ips, nil
}

func createBackup(hostsPath string, backupCount int) error {
	dir := filepath.Join(filepath.Dir(hostsPath), "dynhosts_backups")
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	timestamp := time.Now().Format("20060102_150405")
	dst := filepath.Join(dir, "hosts_"+timestamp+".bak")

	src, err := os.Open(hostsPath)
	if err != nil {
		return err
	}
	defer src.Close()

	d, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer d.Close()

	if _, err = io.Copy(d, src); err != nil {
		return err
	}
	log.Printf("バックアップ作成: %s", dst)

	entries, _ := filepath.Glob(filepath.Join(dir, "hosts_*.bak"))
	sort.Strings(entries)
	for len(entries) > backupCount {
		os.Remove(entries[0])
		entries = entries[1:]
	}

	return nil
}

func buildManagedSection(cfg Config) (string, int, int) {
	dnsServer := cfg.Settings.DNSServer
	timestamp := time.Now().Format("2006-01-02 15:04:05")

	var lines []string
	lines = append(lines, markerBegin)
	lines = append(lines, "# 自動管理セクション - 手動編集は次回更新時に上書きされます")
	lines = append(lines, "# 最終更新: "+timestamp)
	lines = append(lines, "#")

	success, failure := 0, 0

	for _, entry := range cfg.Entries {
		if !entry.IsEnabled() {
			lines = append(lines, "# [無効] "+entry.Alias)
			log.Printf("スキップ（無効）: %s", entry.Alias)
			continue
		}

		ips, err := resolveFQDN(entry.Alias, dnsServer)
		if err != nil || len(ips) == 0 {
			lines = append(lines, "# [警告] DNS解決失敗: "+entry.Alias)
			log.Printf("DNS解決失敗: %s: %v", entry.Alias, err)
			failure++
			continue
		}

		ip := ips[0]
		hostname := entry.Name
		if hostname == "" {
			hostname = entry.Alias
		}
		lines = append(lines, ip+"\t"+hostname)
		log.Printf("解決: %s -> %s", entry.Alias, ip)
		success++
	}

	lines = append(lines, markerEnd)
	return strings.Join(lines, "\n"), success, failure
}

// UpdateHostsFile は hosts ファイルの管理ブロックを最新の DNS 解決結果で置き換える。
func UpdateHostsFile(cfg Config) (success, failure int, err error) {
	hostsPath := cfg.Settings.HostsFile
	if hostsPath == "" {
		hostsPath = `C:\Windows\System32\drivers\etc\hosts`
	}

	if cfg.Settings.Backup {
		if berr := createBackup(hostsPath, cfg.Settings.BackupCount); berr != nil {
			log.Printf("バックアップ作成失敗（処理は続行）: %v", berr)
		}
	}

	content, err := os.ReadFile(hostsPath)
	if err != nil {
		return 0, 0, fmt.Errorf("hostsファイル読み込みエラー: %w", err)
	}

	managed, success, failure := buildManagedSection(cfg)

	var kept []string
	inside := false
	for _, line := range strings.Split(string(content), "\n") {
		stripped := strings.TrimSpace(line)
		if stripped == markerBegin {
			inside = true
			continue
		}
		if stripped == markerEnd {
			inside = false
			continue
		}
		if !inside {
			kept = append(kept, line)
		}
	}

	base := strings.TrimRight(strings.Join(kept, "\n"), "\r\n\t ")
	newContent := base + "\n\n" + managed + "\n"

	if err := os.WriteFile(hostsPath, []byte(newContent), 0644); err != nil {
		return 0, 0, fmt.Errorf("hostsファイル書き込みエラー: %w", err)
	}

	log.Printf("hostsファイルを更新しました: %s (成功: %d, 失敗: %d)", hostsPath, success, failure)
	return success, failure, nil
}

// RestoreHostsFile は hosts ファイルから dynhosts 管理セクションを削除して元の状態に戻す。
func RestoreHostsFile(cfg Config) error {
	hostsPath := cfg.Settings.HostsFile
	if hostsPath == "" {
		hostsPath = `C:\Windows\System32\drivers\etc\hosts`
	}

	content, err := os.ReadFile(hostsPath)
	if err != nil {
		return fmt.Errorf("hostsファイル読み込みエラー: %w", err)
	}

	var kept []string
	inside := false
	for _, line := range strings.Split(string(content), "\n") {
		stripped := strings.TrimSpace(line)
		if stripped == markerBegin {
			inside = true
			continue
		}
		if stripped == markerEnd {
			inside = false
			continue
		}
		if !inside {
			kept = append(kept, line)
		}
	}

	restored := strings.TrimRight(strings.Join(kept, "\n"), "\r\n\t ") + "\n"
	if err := os.WriteFile(hostsPath, []byte(restored), 0644); err != nil {
		return fmt.Errorf("hostsファイル書き込みエラー: %w", err)
	}

	log.Println("hostsファイルを元に戻しました")
	return nil
}
