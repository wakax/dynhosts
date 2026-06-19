package main

import (
	"fmt"
	"log"
	"strings"
	"github.com/lxn/walk"
	. "github.com/lxn/walk/declarative"
	"github.com/lxn/win"
)

// ---------------------------------------------------------------------------
// エントリーリスト TableModel
// ---------------------------------------------------------------------------

type EntryModel struct {
	walk.TableModelBase
	items []Entry
}

func newEntryModel(entries []Entry) *EntryModel {
	m := &EntryModel{}
	m.items = make([]Entry, len(entries))
	for i, e := range entries {
		m.items[i] = e.Clone()
	}
	return m
}

func (m *EntryModel) RowCount() int { return len(m.items) }

func (m *EntryModel) Value(row, col int) interface{} {
	if row < 0 || row >= len(m.items) {
		return nil
	}
	e := m.items[row]
	switch col {
	case 0:
		return ""
	case 1:
		return e.Name
	case 2:
		return e.Alias
	case 3:
		return e.Comment
	}
	return nil
}

func (m *EntryModel) Checked(index int) bool {
	if index < 0 || index >= len(m.items) {
		return false
	}
	return m.items[index].IsEnabled()
}

func (m *EntryModel) SetChecked(index int, checked bool) error {
	if index < 0 || index >= len(m.items) {
		return nil
	}
	m.items[index].Enabled = &checked
	return nil
}

// ---------------------------------------------------------------------------
// エントリー追加・編集ダイアログ
// ---------------------------------------------------------------------------

func showEntryDialog(owner walk.Form, e *Entry) (*Entry, bool) {
	entry := Entry{}
	if e != nil {
		entry = e.Clone()
	}

	var dlg *walk.Dialog
	var nameEdit, aliasEdit, commentEdit *walk.LineEdit
	var enabledCB *walk.CheckBox
	var acceptPB, cancelPB *walk.PushButton
	accepted := false

	title := "エントリーの追加"
	if e != nil {
		title = "エントリーの編集"
	}

	enabledVal := true
	if e != nil {
		enabledVal = e.IsEnabled()
	}

	if err := (Dialog{
		AssignTo:      &dlg,
		Title:         title,
		DefaultButton: &acceptPB,
		CancelButton:  &cancelPB,
		MinSize:       Size{Width: 480, Height: 260},
		Font:          Font{Family: "Meiryo UI", PointSize: 9},
		Layout:        VBox{},
		Children: []Widget{
			Composite{
				Layout: VBox{},
				Children: []Widget{
					Label{Text: "名前（hosts の短縮名）:"},
					LineEdit{AssignTo: &nameEdit, Text: entry.Name},
					Label{Text: "別名 / FQDN（必須）:"},
					LineEdit{AssignTo: &aliasEdit, Text: entry.Alias},
					Label{Text: "コメント:"},
					LineEdit{AssignTo: &commentEdit, Text: entry.Comment},
					Composite{
						Layout: HBox{MarginsZero: true},
						Children: []Widget{
							CheckBox{AssignTo: &enabledCB, Text: "有効", Checked: enabledVal},
							HSpacer{},
						},
					},
				},
			},
			Composite{
				Layout: HBox{},
				Children: []Widget{
					HSpacer{},
					PushButton{
						AssignTo: &acceptPB,
						Text:     "OK",
						OnClicked: func() {
							alias := strings.TrimSpace(aliasEdit.Text())
							if alias == "" {
								walk.MsgBox(dlg, "入力エラー", "alias (FQDN) は必須です。", walk.MsgBoxOK|walk.MsgBoxIconWarning)
								return
							}
							entry.Name = strings.TrimSpace(nameEdit.Text())
							entry.Alias = alias
							entry.Comment = strings.TrimSpace(commentEdit.Text())
							checked := enabledCB.Checked()
							if !checked {
								entry.Enabled = &checked
							} else {
								entry.Enabled = nil
							}
							accepted = true
							dlg.Accept()
						},
					},
					PushButton{
						AssignTo:  &cancelPB,
						Text:      "キャンセル",
						OnClicked: func() { dlg.Cancel() },
					},
				},
			},
		},
	}).Create(owner); err != nil {
		log.Printf("エントリーダイアログ作成エラー: %v", err)
		return nil, false
	}

	nameEdit.SetFocus()
	dlg.Run()

	if accepted {
		return &entry, true
	}
	return nil, false
}

// ---------------------------------------------------------------------------
// 設定ウィンドウ（シングルトン）
// ---------------------------------------------------------------------------

var settingsMW *walk.MainWindow

func openSettings(cfgPath string, onSave func(bool)) {
	if settingsMW != nil {
		settingsMW.Show()
		settingsMW.Activate()
		return
	}
	createSettingsWindow(cfgPath, onSave)
}

func createSettingsWindow(cfgPath string, onSave func(bool)) {
	cfg, err := LoadConfig(cfgPath)
	if err != nil {
		log.Printf("設定読み込みエラー: %v", err)
		cfg = DefaultConfig()
	}

	model := newEntryModel(cfg.Entries)

	var mw *walk.MainWindow
	var tv *walk.TableView
	var intervalEdit *walk.NumberEdit
	var dnsEdit *walk.LineEdit
	var hostsFileEdit *walk.LineEdit
	var backupCB *walk.CheckBox
	var backupCountEdit *walk.NumberEdit

	startupTab, startupSetup := buildStartupTab(&mw)

	icon, _ := loadIcon()

	if err := (MainWindow{
		AssignTo: &mw,
		Title:    "dynhosts 設定",
		Icon:     icon,
		Visible:  false,
		Font:     Font{Family: "Meiryo UI", PointSize: 9},
		MinSize:  Size{Width: 0, Height: 0},
		Layout:   VBox{MarginsZero: true},
		Children: []Widget{
			TabWidget{
				Pages: []TabPage{
					// ── Tab 1: エントリー管理 ──────────────────────────
					{
						Title:  "  エントリー管理  ",
						Layout: VBox{},
						Children: []Widget{
							TableView{
								AssignTo:         &tv,
								AlternatingRowBG: true,
								CheckBoxes:       true,
								ColumnsOrderable:  false,
								MinSize:           Size{Width: 850, Height: 360},
								Columns: []TableViewColumn{
									{Title: "有効", Width: 40},
									{Title: "名前", Width: 200},
									{Title: "Alias (FQDN)", Width: 380},
									{Title: "コメント", Width: 200},
								},
								Model: model,
							},
							Composite{
								Layout: HBox{MarginsZero: true},
								Children: []Widget{
									PushButton{
										Text:    "追加",
										MinSize: Size{Width: 90},
										MaxSize: Size{Width: 90},
										OnClicked: func() {
											entry, ok := showEntryDialog(mw, nil)
											if ok {
												model.items = append(model.items, *entry)
												model.PublishRowsReset() //nolint:errcheck
											}
										},
									},
									PushButton{
										Text:    "編集",
										MinSize: Size{Width: 90},
										MaxSize: Size{Width: 90},
										OnClicked: func() {
											row := tv.CurrentIndex()
											if row < 0 {
												return
											}
											entry, ok := showEntryDialog(mw, &model.items[row])
											if ok {
												model.items[row] = *entry
												model.PublishRowChanged(row) //nolint:errcheck
											}
										},
									},
									PushButton{
										Text:    "削除",
										MinSize: Size{Width: 90},
										MaxSize: Size{Width: 90},
										OnClicked: func() {
											row := tv.CurrentIndex()
											if row < 0 {
												return
											}
											label := model.items[row].Name
											if label == "" {
												label = model.items[row].Alias
											}
											if walk.MsgBox(mw, "削除確認",
												fmt.Sprintf("「%s」を削除しますか？", label),
												walk.MsgBoxYesNo|walk.MsgBoxIconQuestion) == walk.DlgCmdYes {
												model.items = append(model.items[:row], model.items[row+1:]...)
												model.PublishRowsReset() //nolint:errcheck
											}
										},
									},
									PushButton{
										Text:    "↑",
										MinSize: Size{Width: 40},
										MaxSize: Size{Width: 40},
										OnClicked: func() {
											row := tv.CurrentIndex()
											if row <= 0 {
												return
											}
											model.items[row-1], model.items[row] = model.items[row], model.items[row-1]
											model.PublishRowsReset() //nolint:errcheck
											tv.SetCurrentIndex(row - 1)
										},
									},
									PushButton{
										Text:    "↓",
										MinSize: Size{Width: 40},
										MaxSize: Size{Width: 40},
										OnClicked: func() {
											row := tv.CurrentIndex()
											if row < 0 || row >= len(model.items)-1 {
												return
											}
											model.items[row], model.items[row+1] = model.items[row+1], model.items[row]
											model.PublishRowsReset() //nolint:errcheck
											tv.SetCurrentIndex(row + 1)
										},
									},
									HSpacer{},
								},
							},
						},
					},

					// ── Tab 2: 基本設定 ──────────────────────────────
					{
						Title:  "  基本設定  ",
						Layout: Grid{Columns: 2},
						Children: []Widget{
							Label{Text: "更新間隔（秒）:"},
							Composite{
								Layout: HBox{MarginsZero: true},
								Children: []Widget{
									NumberEdit{
										AssignTo: &intervalEdit,
										Value:    float64(cfg.Settings.UpdateInterval),
										MinValue: 60,
										MaxValue: 86400,
										Decimals: 0,
										MinSize:  Size{Width: 80},
										MaxSize:  Size{Width: 80},
		},
									HSpacer{},
								},
							},
							Label{Text: "DNS サーバー（空 = OS 既定）:"},
							LineEdit{AssignTo: &dnsEdit, Text: cfg.Settings.DNSServer,},
							Label{Text: "hosts ファイルのパス:"},
							Composite{
								Layout: HBox{MarginsZero: true},
								Children: []Widget{
									LineEdit{
										AssignTo: &hostsFileEdit,
										Text:     cfg.Settings.HostsFile,
		},
									PushButton{
										Text:    "参照…",
										MinSize: Size{Width: 90},
										MaxSize: Size{Width: 90},
										OnClicked: func() {
											dlg := new(walk.FileDialog)
											dlg.Title = "hosts ファイルを選択"
											dlg.Filter = "すべてのファイル (*.*)|*.*"
											if ok, err := dlg.ShowOpen(mw); err == nil && ok {
												hostsFileEdit.SetText(dlg.FilePath)
											}
										},
									},
								},
							},
							CheckBox{
								AssignTo:   &backupCB,
								Text:       "更新前にバックアップを取る",
								Checked:    cfg.Settings.Backup,
								ColumnSpan: 2,
							},
							Label{Text: "バックアップ保持世代数:"},
							Composite{
								Layout: HBox{MarginsZero: true},
								Children: []Widget{
									NumberEdit{
										AssignTo: &backupCountEdit,
										Value:    float64(cfg.Settings.BackupCount),
										MinValue: 1,
										MaxValue: 100,
										Decimals: 0,
										MinSize:  Size{Width: 80},
										MaxSize:  Size{Width: 80},
		},
									HSpacer{},
								},
							},
						},
					},

					// ── Tab 3: スタートアップ ─────────────────────────
					startupTab,
				},
			},
			Composite{
				Layout: HBox{},
				Children: []Widget{
					PushButton{
						Text:    "保存",
						MinSize: Size{Width: 120},
						MaxSize: Size{Width: 120},
						OnClicked: func() {
							saveCfg := collectSettings(cfg, model, intervalEdit, dnsEdit, hostsFileEdit, backupCB, backupCountEdit)
							if err := SaveConfig(cfgPath, saveCfg); err != nil {
								walk.MsgBox(mw, "エラー", "設定の保存に失敗しました:\n"+err.Error(), walk.MsgBoxOK|walk.MsgBoxIconError)
								return
							}
							log.Printf("設定を保存しました: %s", cfgPath)
							if onSave != nil {
								onSave(true)
							}
							win.PostMessage(mw.Handle(), win.WM_CLOSE, 0, 0)
						},
					},
					HSpacer{},
					PushButton{
						Text:    "キャンセル",
						MinSize: Size{Width: 135},
						MaxSize: Size{Width: 135},
						OnClicked: func() {
							win.PostMessage(mw.Handle(), win.WM_CLOSE, 0, 0)
						},
					},
				},
			},
		},
	}).Create(); err != nil {
		log.Printf("設定ウィンドウ作成エラー: %v", err)
		return
	}

	settingsMW = mw
	startupSetup()

	// 行ダブルクリックで編集
	tv.ItemActivated().Attach(func() {
		row := tv.CurrentIndex()
		if row < 0 {
			return
		}
		entry, ok := showEntryDialog(mw, &model.items[row])
		if ok {
			model.items[row] = *entry
			model.PublishRowChanged(row) //nolint:errcheck
		}
	})

	// ウィンドウを閉じる → 破棄して次回開く時に再生成する
	mw.Closing().Attach(func(canceled *bool, reason walk.CloseReason) {
		settingsMW = nil
	})

	centerWindow(mw)
	mw.Show()
}

func collectSettings(base Config, model *EntryModel,
	intervalEdit *walk.NumberEdit, dnsEdit *walk.LineEdit,
	hostsFileEdit *walk.LineEdit, backupCB *walk.CheckBox,
	backupCountEdit *walk.NumberEdit) Config {

	cfg := base
	cfg.Settings.UpdateInterval = int(intervalEdit.Value())
	cfg.Settings.DNSServer = strings.TrimSpace(dnsEdit.Text())
	cfg.Settings.HostsFile = strings.TrimSpace(hostsFileEdit.Text())
	cfg.Settings.Backup = backupCB.Checked()
	cfg.Settings.BackupCount = int(backupCountEdit.Value())
	cfg.Entries = make([]Entry, len(model.items))
	copy(cfg.Entries, model.items)
	return cfg
}

// buildStartupTab はスタートアップ登録タブを構築して返す。
// 第2戻り値の setup は MainWindow.Create() 後に呼び出すこと。
func buildStartupTab(ownerPtr **walk.MainWindow) (TabPage, func()) {
	msgBox := func(title, msg string, style walk.MsgBoxStyle) {
		if *ownerPtr != nil {
			walk.MsgBox(*ownerPtr, title, msg, style)
		}
	}

	type item struct {
		label     string
		install   func() error
		uninstall func() error
		check     func() bool
	}

	items := []item{
		{
			label:     "ログオン時の自動起動",
			install:   InstallTrayTask,
			uninstall: UninstallTrayTask,
			check:     func() bool { return TaskExists(trayTaskName) },
		},
		{
			label: "定期自動更新タスク",
			install: func() error {
				cfg, err := LoadConfig(configPath)
				if err != nil {
					return err
				}
				return InstallUpdateTask(cfg.Settings.UpdateInterval)
			},
			uninstall: UninstallUpdateTask,
			check:     func() bool { return TaskExists(updateTaskName) },
		},
		{
			label:     "スタートメニューのショートカット",
			install:   InstallStartMenu,
			uninstall: UninstallStartMenu,
			check:     ShortcutExists,
		},
	}

	type ws struct {
		statusLbl *walk.Label
		deletePB  *walk.PushButton
	}
	wss := make([]ws, len(items))

	refresh := func(i int) {
		registered := items[i].check()
		if wss[i].statusLbl != nil {
			if registered {
				wss[i].statusLbl.SetText("登録済み ✓")
			} else {
				wss[i].statusLbl.SetText("未登録")
			}
		}
		if wss[i].deletePB != nil {
			wss[i].deletePB.SetEnabled(registered)
		}
	}

	children := []Widget{}
	for i, it := range items {
		i, it := i, it
		children = append(children,
			Composite{
				Layout: HBox{MarginsZero: true},
				Children: []Widget{
					Label{Text: it.label, MinSize: Size{Width: 200}},
					Label{AssignTo: &wss[i].statusLbl, Text: "", MinSize: Size{Width: 90}},
					PushButton{
						Text:    "登録",
						MinSize: Size{Width: 105},
						MaxSize: Size{Width: 105},
						OnClicked: func() {
							if err := it.install(); err != nil {
								msgBox("エラー", err.Error(), walk.MsgBoxOK|walk.MsgBoxIconError)
							} else {
								msgBox("完了", it.label+"を登録しました。", walk.MsgBoxOK|walk.MsgBoxIconInformation)
								refresh(i)
							}
						},
					},
					PushButton{
						AssignTo: &wss[i].deletePB,
						Text:     "削除",
						MinSize:  Size{Width: 105},
						MaxSize:  Size{Width: 105},
						OnClicked: func() {
							if err := it.uninstall(); err != nil {
								msgBox("エラー", err.Error(), walk.MsgBoxOK|walk.MsgBoxIconError)
							} else {
								msgBox("完了", it.label+"を削除しました。", walk.MsgBoxOK|walk.MsgBoxIconInformation)
								refresh(i)
							}
						},
					},
					HSpacer{},
				},
			},
		)
	}

	children = append(children, VSpacer{})

	setup := func() {
		for i := range items {
			refresh(i)
		}
	}

	return TabPage{
		Title:    "  スタートアップ  ",
		Layout:   VBox{},
		Children: children,
	}, setup
}

func centerWindow(mw *walk.MainWindow) {
	sw := int(win.GetSystemMetrics(win.SM_CXSCREEN))
	sh := int(win.GetSystemMetrics(win.SM_CYSCREEN))
	// コンテンツの最小サイズにリサイズしてから中央配置する
	// mw.Width()/Height() は Windows デフォルト（大）なので使わない
	w, h := mw.Width(), mw.Height()
	if item := walk.CreateLayoutItemsForContainer(mw); item != nil {
		if ms := item.MinSize(); ms.Width > 0 && ms.Height > 0 {
			w, h = ms.Width, ms.Height
		}
	}
	// SetBoundsPixels で物理ピクセル単位に統一（SetBounds は 96DPI 基準値を期待するため不一致になる）
	mw.SetBoundsPixels(walk.Rectangle{
		X:      (sw - w) / 2,
		Y:      (sh - h) / 2,
		Width:  w,
		Height: h,
	})
}
