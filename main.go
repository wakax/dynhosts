package main

import (
	_ "embed"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
	"time"

	"github.com/lxn/walk"
	. "github.com/lxn/walk/declarative"
	"github.com/lxn/win"
	"golang.org/x/sys/windows"
)

//go:embed dynhosts.ico
var embeddedIcon []byte

func init() {
	// walk および Win32 GUI は OS のメインスレッドでのみ動作する
	runtime.LockOSThread()
}

// ---------------------------------------------------------------------------
// グローバル状態
// ---------------------------------------------------------------------------

var (
	configPath string
	logPath    string

	lastMu     sync.Mutex
	lastResult struct {
		t       time.Time
		success int
		failure int
		err     error
	}

	updateLock sync.Mutex
	stopCh     = make(chan struct{})
	wakeupCh   = make(chan struct{}, 1)

	hostMW       *walk.MainWindow
	ni           *walk.NotifyIcon
	statusAction *walk.Action

	instanceMutex windows.Handle
)

// ---------------------------------------------------------------------------
// エントリーポイント
// ---------------------------------------------------------------------------

func main() {
	exe, _ := os.Executable()
	baseDir := filepath.Dir(exe)
	configPath = filepath.Join(baseDir, "config.yaml")
	logPath = filepath.Join(baseDir, "dynhosts.log")

	setupLogging(logPath)

	updateFlag := flag.Bool("update", false, "一度だけ更新して終了（タスクスケジューラ向け）")
	installFlag := flag.Bool("install", false, "Windowsタスクスケジューラに登録")
	uninstallFlag := flag.Bool("uninstall", false, "Windowsタスクスケジューラから削除")
	flag.Parse()

	// 初回起動時の設定ファイル生成
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		if err := SaveConfig(configPath, DefaultConfig()); err != nil {
			log.Printf("設定ファイル生成エラー: %v", err)
		} else {
			log.Printf("既定の設定ファイルを生成しました: %s", configPath)
		}
	}

	if *installFlag {
		cfg, _ := LoadConfig(configPath)
		if err := InstallUpdateTask(cfg.Settings.UpdateInterval); err != nil {
			log.Printf("更新タスク登録エラー: %v", err)
		}
		if err := InstallTrayTask(); err != nil {
			log.Printf("トレイタスク登録エラー: %v", err)
		}
		if err := InstallStartMenu(); err != nil {
			log.Printf("スタートメニュー登録エラー: %v", err)
		}
		return
	}

	if *uninstallFlag {
		UninstallUpdateTask()  //nolint:errcheck
		UninstallTrayTask()    //nolint:errcheck
		UninstallStartMenu()   //nolint:errcheck
		return
	}

	if *updateFlag {
		cfg, err := LoadConfig(configPath)
		if err != nil {
			log.Printf("設定読み込みエラー: %v", err)
			os.Exit(1)
		}
		_, _, ferr := UpdateHostsFile(cfg)
		if ferr != nil {
			log.Printf("更新エラー: %v", ferr)
			os.Exit(1)
		}
		return
	}

	// トレイモード: 二重起動チェック（旧インスタンスがあれば終了させてリトライ）
	if !ensureSingleInstance() {
		return
	}

	runTray()
}

func acquireMutex(name string) bool {
	n, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return true
	}
	h, err := windows.CreateMutex(nil, false, n)
	instanceMutex = h
	return err != windows.ERROR_ALREADY_EXISTS
}

// ensureSingleInstance は二重起動を防ぐ。既存インスタンスがある場合は
// taskkill で終了させ、mutex を取得できるまで最大 3 秒待機する。
// それでも取得できない場合はメッセージボックスを表示して false を返す。
func ensureSingleInstance() bool {
	const name = "Global\\dynhosts-tray"
	if acquireMutex(name) {
		return true
	}

	log.Println("既存のインスタンスを検出しました。終了させます...")

	// 自分以外の dynhosts* プロセスを強制終了
	// ビルド時に Go リンカーが実行中 EXE を dynhosts.exe~ 等にリネームする場合があるため
	// /IM はワイルドカードで一括対応する
	exe, _ := os.Executable()
	exeBase := filepath.Base(exe) // "dynhosts.exe"
	exeWild := exeBase[:len(exeBase)-len(filepath.Ext(exeBase))] + "*" // "dynhosts*"
	cmd := exec.Command("taskkill",
		"/FI", fmt.Sprintf("PID ne %d", os.Getpid()),
		"/FI", "IMAGENAME eq "+exeWild,
		"/F")
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	cmd.Run() //nolint:errcheck

	// 旧インスタンスが保持していたハンドルを解放してからリトライ
	if instanceMutex != 0 {
		windows.CloseHandle(instanceMutex) //nolint:errcheck
		instanceMutex = 0
	}

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		time.Sleep(200 * time.Millisecond)
		if acquireMutex(name) {
			log.Println("旧インスタンスを終了させました。起動を続行します。")
			return true
		}
	}

	// それでも起動できない場合はユーザーに通知
	log.Println("mutex を取得できませんでした。起動を中止します。")
	msgTitle, _ := windows.UTF16PtrFromString("dynhosts")
	msgText, _ := windows.UTF16PtrFromString(
		"dynhosts の起動に失敗しました。\nタスクマネージャーで dynhosts.exe を終了してから再起動してください。")
	win.MessageBox(0, msgText, msgTitle, win.MB_OK|win.MB_ICONERROR)
	return false
}

// ---------------------------------------------------------------------------
// トレイ起動
// ---------------------------------------------------------------------------

func runTray() {
	// 非表示のホストウィンドウ（メッセージポンプ用）
	if err := (MainWindow{
		AssignTo: &hostMW,
		Title:    "dynhosts",
		Visible:  false,
		MinSize:  Size{Width: 1, Height: 1},
	}).Create(); err != nil {
		log.Fatalf("ホストウィンドウ作成エラー: %v", err)
	}

	// 終了ハンドラー: tray メニューからの終了だけでなく
	// 外部からの WM_CLOSE（新インスタンスによる置き換え等）にも対応する
	var cleanupOnce sync.Once
	hostMW.Closing().Attach(func(canceled *bool, reason walk.CloseReason) {
		cleanupOnce.Do(func() {
			log.Println("アプリケーションを終了します。")
			close(stopCh)
			if ni != nil {
				ni.SetVisible(false) //nolint:errcheck
			}
		})
	})

	var err error
	ni, err = walk.NewNotifyIcon(hostMW)
	if err != nil {
		log.Fatalf("トレイアイコン作成エラー: %v", err)
	}
	defer ni.Dispose()

	if icon, err := loadIcon(); err == nil {
		ni.SetIcon(icon)
	} else {
		log.Printf("アイコン読み込みエラー（スキップ）: %v", err)
	}
	ni.SetToolTip("dynhosts")
	buildTrayMenu()
	ni.SetVisible(true)

	// 初回更新 + 設定画面を起動後すぐに表示
	go func() {
		runUpdate()
		hostMW.Synchronize(func() {
			openSettings(configPath, onSettingsSaved)
		})
	}()

	// 設定から間隔取得
	cfg, _ := LoadConfig(configPath)
	interval := cfg.Settings.UpdateInterval
	if interval <= 0 {
		interval = 3600
	}
	go autoUpdateLoop(interval)

	log.Println("システムトレイアイコンを起動しました。")
	hostMW.Run()
}

// ---------------------------------------------------------------------------
// トレイメニュー構築
// ---------------------------------------------------------------------------

func buildTrayMenu() {
	menu := ni.ContextMenu()

	statusAction = walk.NewAction()
	statusAction.SetText("dynhosts")
	statusAction.SetEnabled(false)
	menu.Actions().Add(statusAction) //nolint:errcheck

	menu.Actions().Add(walk.NewSeparatorAction()) //nolint:errcheck

	updateNow := walk.NewAction()
	updateNow.SetText("今すぐ更新")
	updateNow.Triggered().Attach(func() {
		ni.ShowMessage("", "hostsファイルを更新中...") //nolint:errcheck
		go runUpdate()
	})
	menu.Actions().Add(updateNow) //nolint:errcheck

	openSettingsAction := walk.NewAction()
	openSettingsAction.SetText("設定を編集")
	openSettingsAction.SetDefault(true)
	openSettingsAction.Triggered().Attach(func() {
		openSettings(configPath, onSettingsSaved)
	})
	menu.Actions().Add(openSettingsAction) //nolint:errcheck

	menu.Actions().Add(walk.NewSeparatorAction()) //nolint:errcheck

	openConfigAction := walk.NewAction()
	openConfigAction.SetText("設定ファイルを開く")
	openConfigAction.Triggered().Attach(func() { shellOpen(configPath) })
	menu.Actions().Add(openConfigAction) //nolint:errcheck

	openHostsAction := walk.NewAction()
	openHostsAction.SetText("hostsファイルを開く")
	openHostsAction.Triggered().Attach(func() {
		cfg, _ := LoadConfig(configPath)
		hostsPath := cfg.Settings.HostsFile
		if hostsPath == "" {
			hostsPath = `C:\Windows\System32\drivers\etc\hosts`
		}
		shellOpen(hostsPath)
	})
	menu.Actions().Add(openHostsAction) //nolint:errcheck

	openLogAction := walk.NewAction()
	openLogAction.SetText("ログを開く")
	openLogAction.Triggered().Attach(func() { shellOpen(logPath) })
	menu.Actions().Add(openLogAction) //nolint:errcheck

	menu.Actions().Add(walk.NewSeparatorAction()) //nolint:errcheck

	exitAction := walk.NewAction()
	exitAction.SetText("終了")
	exitAction.Triggered().Attach(func() {
		log.Println("アプリケーションを終了します。")
		close(stopCh)
		ni.SetVisible(false) //nolint:errcheck
		if settingsMW != nil {
			settingsMW.Dispose()
			settingsMW = nil
		}
		os.Exit(0)
	})
	menu.Actions().Add(exitAction) //nolint:errcheck

	// 左クリックで設定画面を開く
	ni.MouseDown().Attach(func(x, y int, button walk.MouseButton) {
		if button == walk.LeftButton {
			openSettings(configPath, onSettingsSaved)
		}
	})
}

// ---------------------------------------------------------------------------
// 更新処理
// ---------------------------------------------------------------------------

func onSettingsSaved(updateNow bool) {
	// 自動更新ループをリセット
	select {
	case wakeupCh <- struct{}{}:
	default:
	}
	if updateNow {
		ni.ShowMessage("", "hostsファイルを更新中...") //nolint:errcheck
		go runUpdate()
	}
}

func runUpdate() {
	if !updateLock.TryLock() {
		log.Println("更新処理が既に実行中です。スキップします。")
		return
	}
	defer updateLock.Unlock()

	cfg, err := LoadConfig(configPath)
	if err != nil {
		lastMu.Lock()
		lastResult.err = err
		lastMu.Unlock()
		log.Printf("設定読み込みエラー: %v", err)
		hostMW.Synchronize(updateTrayStatus)
		return
	}

	s, f, ferr := UpdateHostsFile(cfg)

	lastMu.Lock()
	lastResult.t = time.Now()
	lastResult.success = s
	lastResult.failure = f
	lastResult.err = ferr
	lastMu.Unlock()

	if ferr != nil {
		log.Printf("更新エラー: %v", ferr)
	} else {
		log.Printf("更新完了 — 成功: %d, 失敗: %d", s, f)
	}

	hostMW.Synchronize(updateTrayStatus)
}

func updateTrayStatus() {
	if statusAction == nil {
		return
	}
	lastMu.Lock()
	t := lastResult.t
	s := lastResult.success
	f := lastResult.failure
	e := lastResult.err
	lastMu.Unlock()

	if t.IsZero() {
		statusAction.SetText("dynhosts")
		return
	}
	if e != nil {
		statusAction.SetText("エラー: " + e.Error())
	} else {
		statusAction.SetText(fmt.Sprintf("最終更新 %s (成功:%d 失敗:%d)",
			t.Format("2006-01-02 15:04:05"), s, f))
	}
}

// ---------------------------------------------------------------------------
// 自動更新ループ
// ---------------------------------------------------------------------------

func autoUpdateLoop(interval int) {
	log.Printf("自動更新スレッド開始 (間隔: %d 秒)", interval)
	timer := time.NewTimer(time.Duration(interval) * time.Second)
	defer timer.Stop()

	for {
		select {
		case <-stopCh:
			log.Println("自動更新スレッド停止")
			return

		case <-wakeupCh:
			// 設定変更でタイマーをリセット
			if !timer.Stop() {
				select {
				case <-timer.C:
				default:
				}
			}
			cfg, err := LoadConfig(configPath)
			if err == nil && cfg.Settings.UpdateInterval > 0 {
				interval = cfg.Settings.UpdateInterval
			}
			timer.Reset(time.Duration(interval) * time.Second)

		case <-timer.C:
			log.Println("自動更新を実行します...")
			runUpdate()
			cfg, err := LoadConfig(configPath)
			if err == nil && cfg.Settings.UpdateInterval > 0 {
				interval = cfg.Settings.UpdateInterval
			}
			timer.Reset(time.Duration(interval) * time.Second)
		}
	}
}

// ---------------------------------------------------------------------------
// ユーティリティ
// ---------------------------------------------------------------------------

func setupLogging(logPath string) {
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	log.SetOutput(io.MultiWriter(f, os.Stderr))
	log.SetFlags(log.Ldate | log.Ltime)
}

func loadIcon() (*walk.Icon, error) {
	// EXE リソース (ID 1) を優先
	if icon, err := walk.NewIconFromResourceId(1); err == nil {
		return icon, nil
	}
	// go:embed で埋め込んだバイト列を一時ファイル経由でロード
	if tmp, err := os.CreateTemp("", "dynhosts*.ico"); err == nil {
		name := tmp.Name()
		_, werr := tmp.Write(embeddedIcon)
		tmp.Close()
		if werr == nil {
			if icon, err := walk.NewIconFromFile(name); err == nil {
				os.Remove(name)
				return icon, nil
			}
		}
		os.Remove(name)
	}
	// さらに EXE 隣の .ico にフォールバック
	exe, _ := os.Executable()
	icoPath := filepath.Join(filepath.Dir(exe), "dynhosts.ico")
	if _, err := os.Stat(icoPath); err == nil {
		return walk.NewIconFromFile(icoPath)
	}
	return nil, fmt.Errorf("アイコンが見つかりません")
}

func shellOpen(path string) {
	cmd := exec.Command("cmd", "/c", "start", "", path)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	cmd.Start() //nolint:errcheck
}
