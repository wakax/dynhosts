package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

const (
	updateTaskName = "dynhosts-auto-update"
	trayTaskName   = "dynhosts-tray"
)

func schtasks(args ...string) error {
	cmd := exec.Command("schtasks", args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000} // CREATE_NO_WINDOW
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("schtasks %v: %s", args, string(out))
	}
	return nil
}

func runPowerShell(script string) error {
	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("powershell: %s", string(out))
	}
	return nil
}

func psEscape(s string) string {
	return strings.ReplaceAll(s, "'", "''")
}

func InstallUpdateTask(intervalSeconds int) error {
	intervalMin := intervalSeconds / 60
	if intervalMin < 1 {
		intervalMin = 1
	}

	exe, _ := os.Executable()
	dir := filepath.Dir(exe)

	script := fmt.Sprintf(`
$a = New-ScheduledTaskAction -Execute '"%s"' -Argument '--update' -WorkingDirectory '%s'
$t1 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes %d)
$t2 = New-ScheduledTaskTrigger -AtStartup
$s = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest
Register-ScheduledTask -TaskName '%s' -Action $a -Trigger @($t1,$t2) -Settings $s -Principal $p -Force | Out-Null
`, psEscape(exe), psEscape(dir), intervalMin, updateTaskName)

	if err := runPowerShell(script); err != nil {
		return err
	}
	log.Printf("タスクスケジューラへの登録が完了しました: %s (更新間隔: %d 分)", updateTaskName, intervalMin)
	return nil
}

func UninstallUpdateTask() error {
	if err := schtasks("/Delete", "/TN", updateTaskName, "/F"); err != nil {
		log.Printf("タスク削除失敗 %s: %v", updateTaskName, err)
		return err
	}
	log.Printf("タスクを削除しました: %s", updateTaskName)
	return nil
}

func InstallTrayTask() error {
	exe, _ := os.Executable()
	dir := filepath.Dir(exe)

	script := fmt.Sprintf(`
$a = New-ScheduledTaskAction -Execute '"%s"' -WorkingDirectory '%s'
$t = New-ScheduledTaskTrigger -AtLogOn
$t.Delay = 'PT10S'
$s = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName '%s' -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null
`, psEscape(exe), psEscape(dir), trayTaskName)

	if err := runPowerShell(script); err != nil {
		return err
	}
	log.Printf("ログオン時自動起動タスクを登録しました: %s", trayTaskName)
	return nil
}

func UninstallTrayTask() error {
	if err := schtasks("/Delete", "/TN", trayTaskName, "/F"); err != nil {
		log.Printf("タスク削除失敗 %s: %v", trayTaskName, err)
		return err
	}
	log.Printf("タスクを削除しました: %s", trayTaskName)
	return nil
}

func InstallStartMenu() error {
	exe, _ := os.Executable()
	dir := filepath.Dir(exe)
	lnkPath := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "dynhosts.lnk")

	ps := fmt.Sprintf(
		`$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');`+
			`$s.TargetPath='%s';`+
			`$s.WorkingDirectory='%s';`+
			`$s.Description='dynhosts - hostsファイル自動更新ツール';`+
			`$s.Save();`+
			`$b=[IO.File]::ReadAllBytes('%s');`+
			`$b[0x15]=$b[0x15] -bor 0x20;`+
			`[IO.File]::WriteAllBytes('%s',$b)`,
		lnkPath, exe, dir, lnkPath, lnkPath,
	)

	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("ショートカット作成失敗: %s", string(out))
	}
	log.Printf("スタートメニューにショートカットを作成しました: %s", lnkPath)
	return nil
}

func UninstallStartMenu() error {
	lnkPath := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "dynhosts.lnk")
	if err := os.Remove(lnkPath); err != nil && !os.IsNotExist(err) {
		return err
	}
	log.Printf("ショートカットを削除しました: %s", lnkPath)
	return nil
}

func TaskExists(name string) bool {
	return schtasks("/Query", "/TN", name) == nil
}

func ShortcutExists() bool {
	lnkPath := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "dynhosts.lnk")
	_, err := os.Stat(lnkPath)
	return err == nil
}
