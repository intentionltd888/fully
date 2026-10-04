// Fully — 貼網址，抓完整版
//
// 貼一個網址，抓下它的「完整版」而不是頁面上的縮圖。
//
// 這個檔是主控：面板、佇列、剪貼簿監看、跑引擎、選單列與 Dock、右鍵服務與 fully:// 連結、通知。其他檔：
//   ・ClipCard.swift＋card.html：複製網址就跳的預覽卡（右上角，不搶焦點）
//   ・SideIcons.swift：Dock 圖示與選單列圖示的進度　・Thumbs.swift：縮圖（完成畫面、預覽卡、通知）
//   ・Follow.swift：追蹤來源、只抓新的　・Installer.swift：DMG 雙擊即裝＋釘 Dock
//   ・Prefs.swift：語言、設定值、叫引擎的共用管道
//
// 形態：NSStatusItem ＋ 浮動面板（WKWebView）＋ 預覽卡（另一個 WKWebView）
//   - 介面層 = ui.html，資料層 = 引擎（Resources/bin/fully-engine，grab.py 凍成的獨立執行檔）
//   - 兩層用 WKScriptMessageHandler ↔ 一行一個 JSON 事件溝通（EngineRunner，Prefs.swift）
//
// 之所以把抓取邏輯留在 Python 而不改寫成 Swift：引擎有一整套回歸測試，
// 重寫等於把已經修掉的坑（CSRF 403／308 轉址／404 回 200）重新引入一次。

import AppKit
import Carbon.HIToolbox
import UserNotifications
import WebKit

// ─── 常數 ────────────────────────────────────────────────────────────

enum Const {
    static let appName     = "Fully"
    static let panelSize   = NSSize(width: 400, height: 600)
    static let destKey     = "FullyDestination"
    static let hideTipKey  = "FullyHideTipShown"
    static let wizardKey   = "FullyWizardDone"
    static let themeKey    = "FullyTheme"        // system／light／dark
    static let queueKey    = "FullyPendingJobs"  // 關掉重開接著抓
    /// Neu.material 的亮／暗兩色（跟 ui.html 的 token 同值），視窗底色與標題列跟著走
    static let materialColor = NSColor(name: nil) { a in
        a.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
            ? NSColor(red: 0x2A/255, green: 0x2C/255, blue: 0x31/255, alpha: 1)
            : NSColor(red: 0xEE/255, green: 0xEF/255, blue: 0xF2/255, alpha: 1)
    }
    /// 預設輸出：~/Downloads/Fully。使用者改過以 UserDefaults 為準。
    static let defaultDest: String = {
        return NSHomeDirectory() + "/Downloads/Fully"
    }()
    static let bookmarklet = "javascript:location.href='fully://grab?url='+encodeURIComponent(location.href)"
}

// ─── 選單列圖示：Fully 標記（弧線箭頭 ↘，template image，跟隨深淺色）──
// 幾何跟 app/make-icon.swift 同一組：
// 右直條＋下橫條＋四分之一環；筆粗 0.3S、弧外半徑 0.7S、內半徑 0.4S。三塊同向放同一條路徑，接縫不漏白。

func fullyArrow(x0: CGFloat, y0: CGFloat, S: CGFloat) -> NSBezierPath {
    let t = 0.3 * S, R = 0.7 * S, r = 0.4 * S
    let p = NSBezierPath()
    p.appendRect(NSRect(x: x0 + S - t, y: y0, width: t, height: S))
    p.appendRect(NSRect(x: x0, y: y0, width: S, height: t))
    let c = NSPoint(x: x0, y: y0 + t)
    p.move(to: NSPoint(x: x0 + r, y: y0 + t))
    p.line(to: NSPoint(x: x0 + R, y: y0 + t))
    p.appendArc(withCenter: c, radius: R, startAngle: 0, endAngle: 90, clockwise: false)
    p.line(to: NSPoint(x: x0, y: y0 + t + r))
    p.appendArc(withCenter: c, radius: r, startAngle: 90, endAngle: 0, clockwise: true)
    p.close()
    p.windingRule = .nonZero
    return p
}

func makeStatusIcon() -> NSImage { StatusIcon.make() }

/// 無邊框面板。
///
/// `.borderless` 的 NSWindow 預設 `canBecomeKey == false` —— 鍵盤事件完全進不來，
/// 連打字都不行，更別說 ⌘V。要自己覆寫回 true。
final class KeyPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

/// 主面板的 WebView：可以把「完成的縮圖」「最近抓的」直接拖出去（Figma、Keynote、Finder、桌面）。
/// 做法：介面層在 mousedown 時先送 dragArm（要拖哪幾個檔），這裡在滑鼠真的拖動時開一個原生的拖曳（檔案 URL）。
final class DragWebView: WKWebView, NSDraggingSource {
    var armedFiles: [String] = []
    private var downEvent: NSEvent?

    override func mouseDown(with e: NSEvent) { downEvent = e; super.mouseDown(with: e) }
    override func mouseUp(with e: NSEvent) { armedFiles = []; downEvent = nil; super.mouseUp(with: e) }
    override func mouseDragged(with e: NSEvent) {
        if !armedFiles.isEmpty, let d = downEvent,
           hypot(e.locationInWindow.x - d.locationInWindow.x, e.locationInWindow.y - d.locationInWindow.y) > 4 {
            let files = armedFiles.filter { FileManager.default.fileExists(atPath: $0) }
            armedFiles = []
            if !files.isEmpty {
                let p = convert(d.locationInWindow, from: nil)
                let items = files.enumerated().map { i, f -> NSDraggingItem in
                    let it = NSDraggingItem(pasteboardWriter: URL(fileURLWithPath: f) as NSURL)
                    let icon = NSImage(contentsOfFile: f) ?? NSWorkspace.shared.icon(forFile: f)
                    let side: CGFloat = 72
                    let sz = icon.size.width > 0 ? NSSize(width: side, height: side * icon.size.height / max(1, icon.size.width)) : NSSize(width: side, height: side)
                    it.setDraggingFrame(NSRect(x: p.x - sz.width / 2 + CGFloat(i * 6), y: p.y - sz.height / 2 - CGFloat(i * 6),
                                               width: sz.width, height: sz.height), contents: icon)
                    return it
                }
                beginDraggingSession(with: items, event: d, source: self)
                return
            }
        }
        super.mouseDragged(with: e)
    }
    func draggingSession(_ s: NSDraggingSession, sourceOperationMaskFor c: NSDraggingContext) -> NSDragOperation {
        c == .outsideApplication ? .copy : []
    }
}

/// 一個下載工作（可以存起來，關掉重開接著抓）
struct Job: Codable, Equatable {
    var url: String
    var mode: String = "av"          // 開抓方式（預設 av）
    var pick: String? = nil          // 只抓挑過的（引擎 --pick）
    var list: String? = nil          // 預先列好的圖片清單檔（引擎 --list）
    var card = false                 // 從預覽卡或 fully:// 開抓的：卡片原地顯示進度
}

// ─── 主控 ────────────────────────────────────────────────────────────

final class Controller: NSObject, NSApplicationDelegate, WKScriptMessageHandler,
                        WKNavigationDelegate, NSWindowDelegate, NSMenuDelegate,
                        UNUserNotificationCenterDelegate {

    private var statusItem: NSStatusItem!
    private var web: DragWebView!
    private var task: Process?
    private var lastFolder: String?
    private var uiReady = false
    private var cancelled = false
    private var floating: KeyPanel?         // 面板本體（無邊框、可拖、可收鍵盤）
    private var hotKey: EventHotKeyRef?
    private var movedByUser = false     // 使用者拖過之後就不再自動歸位
    private var frameBeforeZoom: NSRect?  // zoom 切換前的大小

    // ── 佇列：多個連結排隊，一個一個抓；可存可接 ──
    private var queue: [Job] = []
    private var cur: Job?
    private var curSource: [String: Any] = [:]                // 這支工作的 source 事件（名稱／種類／資料夾）
    private var lastErr = ""
    private var lastErrEvent: [String: Any] = [:]
    private var sawDone = false          // 引擎在 --json 模式下錯誤也 exit 0（事件已送出），所以「有沒有 done」才是成敗
    private var batch: [(name: String, ok: Bool, msg: String, job: Job)] = []
    private var failedJobs: [Job] = []   // 上一批抓不到的——「全部重試」用
    private var queueDone = 0
    private var queueTotal = 0
    private var frac: Double? = nil      // 現在這支的進度（nil＝閒著；<0＝讀取中）
    private var lastDone: [String: Any] = [:]   // 最近一次 done（追蹤、拖出、剪貼簿用）
    private var activity: NSObjectProtocol?     // 下載中不讓 Mac 睡著

    private static let historyKey = "FullyHistory"
    private var history: [[String: Any]] {
        get { (UserDefaults.standard.array(forKey: Self.historyKey) as? [[String: Any]]) ?? [] }
        set { UserDefaults.standard.set(Array(newValue.prefix(30)), forKey: Self.historyKey) }
    }

    /// 一看就知道是圖的網址（直接指到圖檔）：預覽不必先過安全檢查
    private static let mediaHosts: [String] = {
        var l: [String] = []
        return l
    }()
    private static let fileExts = ["jpg", "jpeg", "png", "webp", "gif", "avif", "heic", "svg", "mp4", "mov", "m4v", "webm", "m3u8"]
    static func looksLikeMedia(_ u: String) -> Bool {
        guard let url = URL(string: u), let host = url.host?.lowercased() else { return false }
        if mediaHosts.contains(where: { host == $0 || host.hasSuffix("." + $0) || ($0.hasSuffix(".") && host.contains($0)) }) { return true }
        return fileExts.contains(url.pathExtension.lowercased())
    }
    /// 預覽會先去「看一眼」那個網址（只讀頁面，不下載檔案）。看起來像一次性連結、內網、帶權杖的網址不自動去看——
    /// 看一眼就可能把一次性的驗證或邀請連結用掉。
    static func safeToProbe(_ u: String) -> Bool {
        guard let url = URL(string: u), let host = url.host?.lowercased(), url.scheme == "https" || url.scheme == "http" else { return false }
        if !host.contains(".") || host.hasSuffix(".local") || host.hasSuffix(".internal") || host.hasSuffix(".ts.net") { return false }
        if host.range(of: #"^\d+\.\d+\.\d+\.\d+$"#, options: .regularExpression) != nil { return false }
        let low = u.lowercased()
        let risky = ["token", "code=", "auth", "login", "signin", "sign-in", "magic", "verify", "reset", "session", "otp", "password",
                     "invite", "unsubscribe", "confirm", "key=", "sig=", "signature="]
        return !risky.contains { low.contains($0) }
    }

    // ── 剪貼簿監看（預設「問一聲」＝預覽卡）──
    private var watchTimer: Timer?
    private var lastPasteCount = NSPasteboard.general.changeCount
    private var recentURLs: [String] = []
    private static let selfMarker = NSPasteboard.PasteboardType("ltd.intention.fully.self")   // 我們自己寫進剪貼簿的，不要又被監看接走

    // ── 預覽 ──
    private var probeProc: Process?
    private var probeFor = ""
    private var probeCache: [String: [String: Any]] = [:]

    /// selftest 用的暫時目的地。獨立一個欄位，才不會把測試路徑寫進使用者的儲存設定。
    private var destOverride: String?

    private var dest: String {
        get {
            if let o = destOverride { return o }
            let a = CommandLine.arguments                     // 測試用：--dest <資料夾>（不改使用者的設定）
            if let i = a.firstIndex(of: "--dest"), a.count > i + 1 { return a[i + 1] }
            return UserDefaults.standard.string(forKey: Const.destKey) ?? Const.defaultDest
        }
        set { UserDefaults.standard.set(newValue, forKey: Const.destKey) }
    }
    private var wizardDone: Bool { UserDefaults.standard.bool(forKey: Const.wizardKey) }

    /// 主題：system／light／dark。直接設 NSApp.appearance，
    /// 標題列、三鍵、WKWebView 的 prefers-color-scheme 全部一起變。
    private var theme: String {
        get {
            let a = CommandLine.arguments
            if let i = a.firstIndex(of: "--theme"), a.count > i + 1 { return a[i + 1] }   // 截圖用
            return UserDefaults.standard.string(forKey: Const.themeKey) ?? "system"
        }
        set { UserDefaults.standard.set(newValue, forKey: Const.themeKey) }
    }
    private func applyTheme() {
        switch theme {
        case "light": NSApp.appearance = NSAppearance(named: .aqua)
        case "dark":  NSApp.appearance = NSAppearance(named: .darkAqua)
        default:      NSApp.appearance = nil
        }
        emit(["type": "theme", "mode": theme])
    }

    // MARK: 啟動

    /// --selftest <連結> <資料夾>：不開面板，直接跑完整條鏈，
    /// 再把 DOM 讀回來確認事件真的到得了介面層。給整合測試與 CI 用。
    private var selftest: (url: String, dest: String)? {
        let a = CommandLine.arguments
        guard let i = a.firstIndex(of: "--selftest"), a.count > i + 2 else { return nil }
        return (a[i + 1], a[i + 2])
    }
    private var isSnapshotRun: Bool { CommandLine.arguments.contains("--snapshot") }

    /// --wizard：強制開精靈（設計審查與截圖用）；--wizard-page N：直接跳到第 N 頁
    private var forceWizard: Bool { CommandLine.arguments.contains("--wizard") }
    private var wizardPage: Int {
        let a = CommandLine.arguments
        guard let i = a.firstIndex(of: "--wizard-page"), a.count > i + 1 else { return 0 }
        return Int(a[i + 1]) ?? 0
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        // ── 安裝器：DMG 裡雙擊 → 問一句 → 搬進 /Applications → 釘 Dock → 從那裡重開
        let args = CommandLine.arguments
        if Installer.isRunningFromDiskImage {
            Installer.offerInstallFromDiskImage(autoYes: args.contains("--install"))
            return
        }
        if let i = args.firstIndex(of: "--eject"), i + 1 < args.count { Installer.ejectLater(args[i + 1]) }
        // 每次從「應用程式」打開都檢查 Dock 那格指對沒有（換版後舊版進垃圾桶，Dock 會跟著指向垃圾桶裡的舊版）。
        // 第一次打開還沒釘就釘（dockPinned 只記「釘過一次」，之後使用者自己拿掉就不再加回去）。
        if Installer.isRunningFromApplications, selftest == nil {
            let first = !UserDefaults.standard.bool(forKey: "dockPinned")
            UserDefaults.standard.set(true, forKey: "dockPinned")
            Dock.ensure(appURL: Bundle.main.bundleURL, pinIfMissing: first)
        }

        // 正規 app —— 跑起來就有 Dock 圖示、⌘Tab 找得到；選單列圖示與 ⌃⌥⌘V 並存。
        NSApp.setActivationPolicy(.regular)
        applyTheme()

        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "app")
        if #available(macOS 13.3, *) { cfg.preferences.isElementFullscreenEnabled = false }

        web = DragWebView(frame: NSRect(origin: .zero, size: Const.panelSize), configuration: cfg)
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")   // 讓 CSS 的紙色自己畫
        if web.responds(to: Selector(("setInspectable:"))) { web.setValue(true, forKey: "inspectable") }

        guard let ui = Bundle.main.url(forResource: "ui", withExtension: "html") else {
            fatalError("ui.html 不在 bundle 裡")
        }
        web.loadFileURL(ui, allowingReadAccessTo: ui.deletingLastPathComponent())

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = makeStatusIcon()
        statusItem.button?.target = self
        statusItem.button?.action = #selector(toggle(_:))
        statusItem.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        SideIcons.shared.attach(status: statusItem.button)

        installMenu()
        registerHotkey()
        setupCard()
        setupFollows()
        NSApp.servicesProvider = self          // 右鍵「服務 → 用 Fully 抓」
        NSUpdateDynamicServices()
        if selftest == nil, !isSnapshotRun {
            startWatch()                       // 自測時不接剪貼簿（不然會多抓剪貼簿裡的網址）
            Follows.shared.startSchedule()
        }

        // --diag：把「面板為什麼開在那裡」的判斷過程印出來。純診斷，不影響正常啟動。
        if CommandLine.arguments.contains("--diag") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                let b = self.statusItem.button
                let scr = NSScreen.main
                print("statusButton      = \(b.map { "\($0.bounds)" } ?? "nil")")
                print("statusButton.window = \(b?.window.map { "\($0.frame)" } ?? "nil")")
                print("在螢幕上的位置    = \(b?.window.map { "\($0.convertToScreen(b!.bounds))" } ?? "nil")")
                print("screen.frame      = \(scr?.frame.debugDescription ?? "nil")")
                print("screen.visible    = \(scr?.visibleFrame.debugDescription ?? "nil")")
                print("statusReachable   = \(self.statusReachable)")
                self.showPanel()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                    print("floating.frame    = \(self.floating.map { "\($0.frame)" } ?? "nil")")
                    print("floating.isKey    = \(self.floating?.isKeyWindow ?? false)")
                    print("canBecomeKey      = \(self.floating?.canBecomeKey ?? false)")
                    let edit = NSApp.mainMenu?.items.first(where: { $0.submenu?.title == L("編輯", "Edit") })?.submenu
                    let keys = edit?.items.map { "\($0.title)=\($0.keyEquivalent)" }.joined(separator: " ") ?? "沒有編輯選單"
                    print("編輯選單          = \(keys)")
                    print("firstResponder    = \(self.floating?.firstResponder.map { "\(type(of: $0))" } ?? "nil")")
                    exit(0)
                }
            }
        }
        // 驗收鉤：預覽卡／Dock 圖示的畫面（官網截圖與設計審查用，不碰網路）
        if let i = args.firstIndex(of: "--card-demo"), args.count > i + 1 { cardDemo(args[i + 1]) }
        // 驗收鉤：--open-url <fully://…>＝假裝系統把這個連結交進來（測 fully:// 的處理，不經 LaunchServices）
        if let i = args.firstIndex(of: "--open-url"), args.count > i + 1, let u = URL(string: args[i + 1]) {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.application(NSApp, open: [u]) }
        }
    }

    /// 裝一份最小主選單。
    ///
    /// **這是 ⌘V 貼不上去的原因**：LSUIElement／.accessory 的 app 預設沒有主選單，
    /// 而 ⌘C／⌘V／⌘A 是靠主選單的 key equivalent 分派的 —— 沒有「編輯」選單，
    /// 按鍵根本走不到輸入框。用標準 selector 掛上去就會自動作用在第一回應者身上。
    private func installMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: L("結束 Fully", "Quit Fully"),
                        action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: L("編輯", "Edit"))
        edit.addItem(withTitle: L("復原", "Undo"), action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: L("重做", "Redo"), action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: L("剪下", "Cut"),  action: #selector(NSText.cut(_:)),       keyEquivalent: "x")
        edit.addItem(withTitle: L("拷貝", "Copy"), action: #selector(NSText.copy(_:)),      keyEquivalent: "c")
        edit.addItem(withTitle: L("貼上", "Paste"), action: #selector(NSText.paste(_:)),    keyEquivalent: "v")
        edit.addItem(.separator())
        edit.addItem(withTitle: L("全選", "Select All"), action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        NSApp.mainMenu = main
    }

    // MARK: 開合

    /// 選單列圖示現在真的點得到嗎。
    ///
    /// 兩種點不到的情況：
    ///   1. 使用者開了「自動隱藏選單列」—— 收起來時整條狀態列被推到螢幕頂端**之外**
    ///      （實測 y = screen.maxY，剛好在可視範圍上面一格）。
    ///   2. 選單列塞滿（常駐項目太多＋瀏海），放不下的被挪到畫面外。
    ///
    /// **Y 軸一定要檢查。** 只驗 X 會誤判成「看得到」，錨定一個在畫面外的按鈕，
    /// macOS 會把它丟到左上角 —— 看起來就像面板亂跑。
    private var statusReachable: Bool {
        guard let b = statusItem.button, let w = b.window, let scr = NSScreen.main else { return false }
        let f = w.convertToScreen(b.bounds)
        guard f.width > 1 else { return false }
        let inX = f.maxX > scr.frame.minX + 1 && f.minX < scr.frame.maxX - 1
        let inY = f.minY < scr.frame.maxY - 2 && f.maxY > scr.frame.minY + 1
        return inX && inY
    }

    @objc private func toggle(_ sender: NSStatusBarButton) {
        // 右鍵（或 control＋點）＝選單：正在抓什麼、最近抓的、追蹤中、複製網址時怎麼做
        if let e = NSApp.currentEvent, e.type == .rightMouseUp || e.modifierFlags.contains(.control) {
            showStatusMenu()
            return
        }
        if let f = floating, f.isVisible { f.orderOut(nil); return }
        showPanel()
    }

    /// 統一的「把面板叫出來」入口。
    ///
    /// **一律用浮動視窗，不用 popover** —— popover 釘在錨點上，使用者拖不動它，
    /// 而面板要能自由拖移。只用一種呈現方式也讓行為可預期：
    /// 不管從快捷鍵、選單列還是 Finder 進來，看到的都是同一個可拖的面板。
    private func showPanel() {
        // 順序有意義：accessory app 要先 activate，視窗才拿得到 key status；
        // 反過來做的話 makeKeyAndOrderFront 會被隨後的 activate 洗掉，鍵盤就進不來。
        NSApp.activate(ignoringOtherApps: true)
        showFloating(near: statusReachable ? statusItem.button : nil)
        pushDest()
        pushClipboard()
        emit(["type": "focus"])
    }

    /// 全域快捷鍵 ⌃⌥⌘V。
    /// 開了「自動隱藏選單列」的話，圖示平常根本不在畫面上 ——
    /// 只靠選單列的話等於沒有入口。用 Carbon 的 RegisterEventHotKey，
    /// 不需要輔助使用權限（NSEvent 的全域監聽需要）。
    private func registerHotkey() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                 eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, userData in
            guard let userData else { return noErr }
            let me = Unmanaged<Controller>.fromOpaque(userData).takeUnretainedValue()
            DispatchQueue.main.async { me.hotkeyFired() }
            return noErr
        }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), nil)

        let id = EventHotKeyID(signature: OSType(0x46554C4C), id: 1)   // FULL
        RegisterEventHotKey(UInt32(kVK_ANSI_V),
                            UInt32(controlKey | optionKey | cmdKey),
                            id, GetApplicationEventTarget(), 0, &hotKey)
    }

    fileprivate func hotkeyFired() {
        if let f = floating, f.isVisible { f.orderOut(nil); return }
        showPanel()
    }

    private func showFloating(near anchor: NSStatusBarButton? = nil) {
        if floating == nil {
            // 原生紅黃綠三鍵：.titled 標題列**留在上面**，標題列透明、底色跟材料同色；紅＝收起（不結束）、黃＝縮到 Dock、綠＝放大填滿（不進全螢幕）。
            let p = KeyPanel(contentRect: NSRect(origin: .zero, size: Const.panelSize),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable],
                             backing: .buffered, defer: false)
            p.title = Const.appName
            p.titlebarAppearsTransparent = true
            p.titleVisibility = .hidden
            p.minSize = Const.panelSize                          // 版面照 400×600 設計，不准再縮
            p.maxSize = NSSize(width: 640, height: 1000)
            p.setFrameAutosaveName("FullyPanel22")
            p.isOpaque = true
            p.backgroundColor = Const.materialColor              // 亮／暗動態色，標題列一起變
            p.hasShadow = true
            p.level = .floating
            p.isReleasedWhenClosed = false
            p.isMovableByWindowBackground = true
            // 切去瀏覽器複製網址時面板不能跟著不見 —— NSPanel 預設 hidesOnDeactivate = true，關掉。
            p.hidesOnDeactivate = false
            p.collectionBehavior = [.canJoinAllSpaces, .fullScreenNone]
            p.delegate = self
            floating = p
            p.setContentSize(Const.panelSize)
        }
        guard let f = floating else { return }

        web.frame = NSRect(origin: .zero, size: floating?.contentView?.bounds.size ?? Const.panelSize)
        web.autoresizingMask = [.width, .height]
        f.contentView = web

        // 只有第一次（或被移出畫面）才重新定位；使用者拖過就尊重他放的位置
        if !f.isVisible && !movedByUser {
            if let b = anchor, let w = b.window {
                let r = w.convertToScreen(b.bounds)
                f.setFrameOrigin(NSPoint(x: min(r.midX - Const.panelSize.width / 2,
                                                (NSScreen.main?.visibleFrame.maxX ?? r.maxX) - Const.panelSize.width - 12),
                                         y: r.minY - Const.panelSize.height - 8))
            } else if let scr = NSScreen.main {
                let v = scr.visibleFrame
                f.setFrameOrigin(NSPoint(x: v.maxX - Const.panelSize.width - 14,
                                         y: v.maxY - Const.panelSize.height - 8))
            }
        }
        f.makeKeyAndOrderFront(nil)
        f.makeFirstResponder(web)
    }

    /// 在 Finder 再按一次 app／點 Dock 圖示＝叫出面板。沒有這個的話，重複雙擊完全沒反應——看起來就像「打不開」。
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        showPanel()
        return true
    }

    /// 使用者從別的 app 切回來時，剪貼簿若是網址就自動帶入 ——
    /// 配合上面的「面板常駐」：去複製 → 切回來 → 網址已經在輸入框裡。
    func applicationDidBecomeActive(_ n: Notification) {
        if floating?.isVisible == true { pushClipboard() }
    }

    /// 原生紅鍵＝收起，不結束（結束走 ⌘Q）。首次收起教一次去哪找回來。
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if sender === floating { hideWithTip(); return false }
        return true
    }

    private func hideWithTip() {
        if !UserDefaults.standard.bool(forKey: Const.hideTipKey) {
            UserDefaults.standard.set(true, forKey: Const.hideTipKey)
            let a = NSAlert()
            a.messageText = L("面板收起了去哪找？", "Where did the panel go?")
            a.informativeText = L("同時按 control ⌃ ＋ option ⌥ ＋ command ⌘ ＋ V，或點 Dock 的 Fully 圖標、選單列的小圖示，隨時叫回來。下載會在背景繼續，Dock 圖示上看得到進度。command ⌘ ＋ Q 才是結束程式。",
                                  "Press control ⌃ + option ⌥ + command ⌘ + V, or click Fully in the Dock or the menu bar, to bring it back. Downloads keep going in the background — the Dock icon shows the progress. command ⌘ + Q quits.")
            a.addButton(withTitle: L("知道了", "Got it"))
            a.runModal()
        }
        floating?.orderOut(nil)
    }

    // MARK: 選單列右鍵選單

    private func showStatusMenu() {
        let m = NSMenu()
        m.delegate = self
        m.addItem(withTitle: L("打開 Fully", "Open Fully"), action: #selector(menuOpen), keyEquivalent: "").target = self
        if task != nil {
            let name = (curSource["name"] as? String) ?? cur?.url ?? ""
            let pct = (frac ?? -1) >= 0 ? "  \(Int((frac ?? 0) * 100))%" : ""
            let it = m.addItem(withTitle: L("正在抓：", "Grabbing: ") + String(name.prefix(36)) + pct, action: nil, keyEquivalent: "")
            it.isEnabled = false
            if !queue.isEmpty {
                m.addItem(withTitle: L("還有 \(queue.count) 個在排", "\(queue.count) more in line"), action: nil, keyEquivalent: "").isEnabled = false
            }
            m.addItem(withTitle: L("停止", "Stop"), action: #selector(menuStop), keyEquivalent: "").target = self
        }
        m.addItem(.separator())

        let recent = NSMenuItem(title: L("最近抓的", "Recent"), action: nil, keyEquivalent: "")
        let sub = NSMenu()
        for (i, it) in history.prefix(8).enumerated() {
            let mi = sub.addItem(withTitle: String(((it["name"] as? String) ?? (it["url"] as? String) ?? "").prefix(48)),
                                 action: #selector(menuRecent(_:)), keyEquivalent: "")
            mi.target = self
            mi.tag = i
        }
        if history.isEmpty { sub.addItem(withTitle: L("還沒有抓過東西", "Nothing yet"), action: nil, keyEquivalent: "").isEnabled = false }
        recent.submenu = sub
        m.addItem(recent)

        let fol = NSMenuItem(title: Follows.shared.items.isEmpty ? L("追蹤中", "Following")
                                 : L("追蹤中（\(Follows.shared.items.count)）", "Following (\(Follows.shared.items.count))"),
                             action: nil, keyEquivalent: "")
        let fs = NSMenu()
        for f in Follows.shared.items.prefix(10) {
            fs.addItem(withTitle: String(f.name.prefix(40)) + (f.lastNew > 0 ? L("・新 \(f.lastNew)", " · \(f.lastNew) new") : ""), action: nil, keyEquivalent: "").isEnabled = false
        }
        if !Follows.shared.items.isEmpty { fs.addItem(.separator()) }
        let now = fs.addItem(withTitle: Follows.shared.checking ? L("正在檢查…", "Checking…") : L("現在檢查", "Check now"),
                             action: #selector(menuFollowCheck), keyEquivalent: "")
        now.target = self
        now.isEnabled = !Follows.shared.checking && !Follows.shared.items.isEmpty
        fol.submenu = fs
        m.addItem(fol)

        m.addItem(.separator())

        let clip = NSMenuItem(title: L("複製網址時", "When I copy a link"), action: nil, keyEquivalent: "")
        let cs = NSMenu()
        for (k, t) in [("card", L("跳出預覽卡問我", "Ask with a preview card")), ("auto", L("直接抓", "Grab right away")), ("off", L("不動", "Do nothing"))] {
            let mi = cs.addItem(withTitle: t, action: #selector(menuClip(_:)), keyEquivalent: "")
            mi.target = self
            mi.representedObject = k
            mi.state = Prefs.clipMode == k ? .on : .off
        }
        clip.submenu = cs
        m.addItem(clip)
        m.addItem(.separator())
        m.addItem(withTitle: L("結束 Fully", "Quit Fully"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        statusItem.menu = m
        statusItem.button?.performClick(nil)
    }
    func menuDidClose(_ menu: NSMenu) {
        if statusItem.menu === menu { DispatchQueue.main.async { self.statusItem.menu = nil } }
    }
    @objc private func menuOpen() { showPanel() }
    @objc private func menuStop() { cancelAll() }
    @objc private func menuRecent(_ s: NSMenuItem) {
        guard s.tag < history.count else { return }
        reveal(item: history[s.tag])
    }
    @objc private func menuFollowCheck() { Follows.shared.checkAll() }
    @objc private func menuClip(_ s: NSMenuItem) {
        Prefs.clipMode = s.representedObject as? String ?? "card"
        startWatch()
        pushPrefs()
    }

    // MARK: Swift → JS

    private func emit(_ payload: [String: Any]) {
        guard uiReady || payload["type"] as? String == "ready",
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else { return }
        DispatchQueue.main.async { self.web.evaluateJavaScript("window.appEvent(\(json))") }
    }

    private func pushDest() {
        let home = NSHomeDirectory()
        var shown = dest.hasPrefix(home) ? String(dest.dropFirst(home.count + 1)) : dest
        if shown.hasPrefix("Desktop/") { shown = String(shown.dropFirst("Desktop/".count)) }
        emit(["type": "dest", "path": shown])
    }

    private func pushClipboard() {
        guard let s = NSPasteboard.general.string(forType: .string) else { return }
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.hasPrefix("http"), t.count < 2048,
              !t.contains(" "), !t.contains("\n") else { return }
        emit(["type": "clip", "url": t])
    }

    private func pushPrefs() {
        let base: [String: Any] = ["type": "prefs", "clip": Prefs.clipMode, "copyAfter": Prefs.copyAfter, "dedup": Prefs.dedup,
                                   "lang": Lang.setting, "bookmarklet": Const.bookmarklet]
        let d = base
        emit(d)
    }

    private func pushFollows() {
        emit(["type": "follows", "items": Follows.shared.dict, "checking": Follows.shared.checking])
    }

    // MARK: JS → Swift

    func userContentController(_ c: WKUserContentController, didReceive msg: WKScriptMessage) {
        guard let body = msg.body as? [String: Any],
              let action = body["action"] as? String else { return }

        switch action {
        case "ready":
            uiReady = true
            // 截圖時 WebView 不在視窗裡，過場與動畫停在起點；凍住才拍得到真實的終態
            if isSnapshotRun {
                web.evaluateJavaScript("document.body.classList.add('freeze')") { _, _ in }
            }
            emit(["type": "hello", "lang": Lang.code])
            pushDest()
            pushPrefs()
            emit(["type": "theme", "mode": theme])
            let info = Bundle.main.infoDictionary
            emit(["type": "about", "version": info?["CFBundleShortVersionString"] as? String ?? "",
                  "build": info?["CFBundleVersion"] as? String ?? ""])
            if selftest == nil { emit(["type": "history", "items": Array(history.prefix(8))]); pushFollows() }
            engineReady()
            // 首啟精靈：沒跑過（或 --wizard）就蓋在主面板上，而且**面板要自己打開**
            if selftest == nil, (!wizardDone || forceWizard) {
                emit(["type": "wizard", "show": true, "page": wizardPage, "clip": Prefs.clipMode, "agreed": Prefs.agreed,
                      "auto": isSnapshotRun ? true : EngineManager.shared.autoOn])
                if !isSnapshotRun {
                    showPanel()
                    if let f = floating, f.frame.height < Const.panelSize.height {
                        var fr = f.frame
                        fr.origin.y -= Const.panelSize.height - fr.height
                        fr.size.height = Const.panelSize.height
                        f.setFrame(fr, display: true)
                    }
                }
            }
            // --snapshot 單獨用（沒有 --selftest）＝拍待命態（或精靈頁、--demo 狀態），給設計迭代看版面
            if selftest == nil, isSnapshotRun, !CommandLine.arguments.contains("--card-demo") {
                emit(["type": "dest", "path": "Downloads/Fully"])
                let a = CommandLine.arguments
                if let i = a.firstIndex(of: "--demo"), a.count > i + 1,
                   a[i + 1].allSatisfy({ $0.isLetter || $0 == "-" }) {
                    let st = a[i + 1]      // 排在前面幾個 emit 之後跑，假資料才不會被真的蓋掉
                    DispatchQueue.main.async { self.web.evaluateJavaScript("window.__demo('\(st)')") { _, _ in } }
                }
                finishSelftest()
            }
            if let t = selftest {
                destOverride = t.dest
                pushDest()
                let urls = t.url.components(separatedBy: "||").filter { !$0.isEmpty }
                let a = CommandLine.arguments
                let m = a.firstIndex(of: "--mode").flatMap { a.count > $0 + 1 ? a[$0 + 1] : nil } ?? "av"
                let pick = a.firstIndex(of: "--pick").flatMap { a.count > $0 + 1 ? a[$0 + 1] : nil }
                enqueue(urls.map { Job(url: $0, mode: m, pick: pick) }, fresh: true)
            } else if !isSnapshotRun {
                resumeSavedQueue()
            }

        case "pick":
            pickFolder()

        case "paste":
            // 「貼上」鍵：給不會按 ⌘V 的人。剪貼簿有什麼就交給介面層判斷是不是網址
            let t = (NSPasteboard.general.string(forType: .string) ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            emit(["type": "paste", "text": String(t.prefix(8192))])

        case "probe":
            // 網址卡的預覽（貼上／帶入網址就會送來）；items＝挑幾張要每一項。截圖（--snapshot）時不碰網路
            guard let u = body["url"] as? String, u.hasPrefix("http"), !isSnapshotRun else { return }
            probe(u, items: body["items"] as? Bool ?? false, manual: body["manual"] as? Bool ?? false)

        case "openFile":
            // 「打開看看」：總覽圖或單一檔案直接用預設程式打開；檔案不在了就退回顯示資料夾
            if let f = body["file"] as? String, FileManager.default.fileExists(atPath: f) {
                NSWorkspace.shared.open(URL(fileURLWithPath: f))
            } else if let d = lastFolder {
                NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: d)
            }

        case "dragArm":
            // 介面層按下了可以拖出去的東西（完成的縮圖／最近抓的一列）：真的拖動時由 DragWebView 開原生拖曳
            web.armedFiles = (body["files"] as? [String]) ?? []

        case "wizardDone":
            UserDefaults.standard.set(true, forKey: Const.wizardKey)
            emit(["type": "wizard", "show": false])
            EngineManager.shared.checkForUpdate(force: false) { s in self.emit(s.dict) }

        case "agree":
            Prefs.agreed = body["on"] as? Bool ?? true

        case "histReveal":
            if let i = body["i"] as? Int, i < history.count { reveal(item: history[i]) }
            else if let f = body["file"] as? String, FileManager.default.fileExists(atPath: f) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: f)])
            } else if let d = body["folder"] as? String, FileManager.default.fileExists(atPath: d) {
                NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: d)
            } else {
                emit(["type": "notice", "message": L("那個檔案已經不在原來的位置了", "That file isn't where it was anymore")])
            }

        case "histThumbs":
            // 最近抓的：幫看得到的那幾列補縮圖
            for (i, it) in history.prefix(8).enumerated() {
                guard let f = (it["file"] as? String) ?? (it["sheet"] as? String) else { continue }
                Thumbs.dataURL(for: f, side: 96) { d in if let d { self.emit(["type": "histThumb", "i": i, "data": d]) } }
            }

        case "histClear":
            history = []
            emit(["type": "history", "items": []])

        case "theme":
            let m = body["mode"] as? String ?? "system"
            theme = ["system", "light", "dark"].contains(m) ? m : "system"
            applyTheme()

        case "lang":
            let l = body["lang"] as? String ?? "system"
            Lang.setting = ["system", "zh", "en"].contains(l) ? l : "system"
            installMenu()
            emit(["type": "hello", "lang": Lang.code])
            pushPrefs()

        case "clipMode":
            Prefs.clipMode = ["card", "auto", "off"].contains(body["mode"] as? String ?? "") ? body["mode"] as! String : "card"
            startWatch()
            pushPrefs()

        case "copyAfter":
            Prefs.copyAfter = body["on"] as? Bool ?? true
            pushPrefs()

        case "dedup":
            Prefs.dedup = body["on"] as? Bool ?? true
            pushPrefs()

        case "copyBookmarklet":
            let pb = NSPasteboard.general
            pb.clearContents()
            pb.setString(Const.bookmarklet, forType: .string)
            lastPasteCount = pb.changeCount
            emit(["type": "notice", "message": L("書籤小工具拷貝好了：新增一個書籤，網址貼上這段", "Bookmarklet copied — add a bookmark and paste this as its address")])

        case "openDoc":
            openDoc(body["doc"] as? String ?? "terms")

        case "start":
            let urls = (body["urls"] as? [String])
                ?? (body["url"] as? String).map { [$0] } ?? []
            guard !urls.isEmpty, task == nil else { return }
            let pick = body["pick"] as? String
            enqueue(urls.map { Job(url: $0, mode: body["mode"] as? String ?? "av", pick: pick) }, fresh: true)

        case "queueAdd":                       // 拖放連結／剪貼簿監看進來的
            let adds = (body["urls"] as? [String]) ?? []
            guard !adds.isEmpty else { return }
            enqueue(adds.map { Job(url: $0, mode: body["mode"] as? String ?? "av") }, fresh: false)

        case "retryAll":
            let jobs = failedJobs
            failedJobs = []
            guard !jobs.isEmpty, task == nil else { return }
            enqueue(jobs, fresh: true)

        case "followAdd":
            guard let u = (lastDone["url"] as? String) ?? cur?.url, !Follows.shared.isFollowing(u) else { return }
            Follows.shared.add(url: u, name: (lastDone["headline"] as? String) ?? (curSource["name"] as? String) ?? u,
                               kind: (curSource["kind"] as? String) ?? "web", mode: (lastDone["mode"] as? String) ?? "av", root: dest)
            emit(["type": "notice", "message": L("追蹤了：之後每 6 小時看一次，只抓新的", "Following — Fully checks every 6 hours and grabs only what's new")])

        case "followRemove":
            if let id = body["id"] as? String { Follows.shared.remove(id: id) }

        case "followCheck":
            Follows.shared.checkAll()

        case "cancel":
            cancelAll()

        case "drag":
            // 介面層送來的位移。screen 座標 Y 軸向下，Cocoa 向上，所以 dy 要反號。
            guard let f = floating,
                  let dx = body["dx"] as? Double, let dy = body["dy"] as? Double else { return }
            movedByUser = true
            f.setFrameOrigin(NSPoint(x: f.frame.origin.x + dx, y: f.frame.origin.y - dy))

        case "openDest":
            // 隨時可按：開現在設定的目的地資料夾（還沒下載過也能開）
            let target = lastFolder ?? dest
            if !FileManager.default.fileExists(atPath: target) {
                try? FileManager.default.createDirectory(atPath: target, withIntermediateDirectories: true)
            }
            NSWorkspace.shared.open(URL(fileURLWithPath: target))

        case "hide":
            hideWithTip()

        case "zoom":
            // 放大到整個螢幕／還原：zoom 式切換，不進 fullscreen space
            if let f = floating, let scr = f.screen ?? NSScreen.main {
                if let saved = frameBeforeZoom {
                    frameBeforeZoom = nil
                    f.setFrame(saved, display: true, animate: true)
                } else {
                    frameBeforeZoom = f.frame
                    f.setFrame(scr.visibleFrame, display: true, animate: true)
                }
            }

        case "resize":
            // 邊緣拖曳縮放（手寫版：無邊框＋.resizable 系統不會給把手）。
            guard let f = floating, frameBeforeZoom == nil,
                  let dx = body["dx"] as? Double, let dy = body["dy"] as? Double,
                  let edge = body["edge"] as? String else { return }
            movedByUser = true
            var fr = f.frame
            let minW: CGFloat = 380, maxW: CGFloat = 760
            let minH: CGFloat = 440, maxH: CGFloat = 1000
            if edge.contains("r") { fr.size.width = min(max(minW, fr.width + dx), maxW) }
            if edge.contains("l") {
                let w = min(max(minW, fr.width - dx), maxW)
                fr.origin.x += fr.width - w; fr.size.width = w
            }
            if edge.contains("b") {
                let h = min(max(minH, fr.height + dy), maxH)
                fr.origin.y -= h - fr.height; fr.size.height = h
            }
            if edge.contains("t") { fr.size.height = min(max(minH, fr.height - dy), maxH) }
            f.setFrame(fr, display: true)

        case "reveal":
            if let file = body["file"] as? String, FileManager.default.fileExists(atPath: file) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: file)])
            } else if let f = lastFolder {
                NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: f)
            }

        case "quit":
            NSApp.terminate(nil)

        // 影片引擎自動更新：設定裡的開關、精靈與設定裡的「現在檢查」
        case "autoUpdate":
            let on = body["on"] as? Bool ?? true
            EngineManager.shared.autoOn = on
            emit(EngineManager.shared.status(fast: true).dict)      // fast：不在主執行緒跑 --version
            if on { EngineManager.shared.checkForUpdate(force: true) { s in self.emit(s.dict) } }
        case "checkUpdate":
            EngineManager.shared.checkForUpdate(force: true) { s in self.emit(s.dict) }

        default:
            break
        }
    }

    private func engineReady() {
        // 影片引擎：先把狀態推給介面，再看要不要背景檢查更新（每天一次）
        let eng = EngineManager.shared
        var first = eng.status(fast: true)         // 第一眼先給出廠版本，免得精靈那頁空著
        if isSnapshotRun {                          // 截圖照新使用者的預設（自動更新開），不帶這台 Mac 自己的設定
            first.auto = true; first.status = "還沒檢查"; first.checkedAt = ""
        }
        emit(first.dict)
        guard selftest == nil, !isSnapshotRun else { return }
        DispatchQueue.global(qos: .utility).async {
            eng.ensureStable()
            let st = eng.status()
            DispatchQueue.main.async {
                self.emit(st.dict)
                if !self.forceWizard || self.wizardDone {
                    eng.checkForUpdate(force: false) { s in self.emit(s.dict) }
                }
            }
        }
    }

    private func pickFolder() {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.allowsMultipleSelection = false
        p.canCreateDirectories = true
        p.prompt = L("選擇", "Choose")
        p.message = L("抓下來的東西要存到哪裡？會自動用來源名稱開一個子資料夾。", "Where should Fully save things? It makes a subfolder named after each source.")
        p.directoryURL = URL(fileURLWithPath: dest)
        NSApp.activate(ignoringOtherApps: true)
        if p.runModal() == .OK, let u = p.url {
            dest = u.path
            pushDest()
        }
    }

    private func reveal(item it: [String: Any]) {
        if let f = it["file"] as? String, FileManager.default.fileExists(atPath: f) {
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: f)])
        } else if let d = it["folder"] as? String, !d.isEmpty, FileManager.default.fileExists(atPath: d) {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: d)
        } else {
            emit(["type": "notice", "message": L("那個檔案已經不在原來的位置了", "That file isn't where it was anymore")])
        }
    }

    // MARK: 佇列

    private func enqueue(_ jobs: [Job], fresh: Bool) {
        let clean = jobs.map { j -> Job in var j = j; j.url = j.url.trimmingCharacters(in: .whitespacesAndNewlines); return j }
                        .filter { $0.url.hasPrefix("http") || $0.list != nil }
        guard !clean.isEmpty else { return }
        if fresh && task == nil { queueDone = 0; queueTotal = 0; batch.removeAll() }
        queue.append(contentsOf: clean)
        queueTotal += clean.count
        persistQueue()
        emitQueue()
        runNext()
    }

    private func runNext() {
        guard task == nil, !queue.isEmpty else { return }
        let job = queue.removeFirst()
        emitQueue()
        run(job)
    }

    private func emitQueue() {
        emit(["type": "queue",
              "pending": queue.map { $0.url },
              "done": queueDone, "total": queueTotal,
              "active": task != nil])
        updateSide()
    }

    /// Dock 與選單列：進度＋還有幾個
    private func updateSide() {
        let remaining = queue.count + (task != nil ? 1 : 0)
        SideIcons.shared.set(progress: task != nil ? (frac ?? -1) : nil, queued: remaining)
    }

    /// 停止：中止現在這支並清空佇列。已寫好的檔案都保留。
    private func cancelAll() {
        cancelled = true
        queue.removeAll()
        task?.terminate()
        task = nil
        persistQueue()
        emitQueue()
        setBusy(false)
        emit(["type": "error", "message": L("已停止。已經抓下來的檔案都留著。", "Stopped. Everything saved so far is kept.")])
    }

    // ── 關掉重開接著抓 ──

    private func persistQueue() {
        var all = queue
        if let c = cur, task != nil { all.insert(c, at: 0) }
        if all.isEmpty { UserDefaults.standard.removeObject(forKey: Const.queueKey); return }
        if let d = try? JSONEncoder().encode(all) { UserDefaults.standard.set(d, forKey: Const.queueKey) }
    }

    private func resumeSavedQueue() {
        guard let d = UserDefaults.standard.data(forKey: Const.queueKey),
              let jobs = try? JSONDecoder().decode([Job].self, from: d), !jobs.isEmpty else { return }
        emit(["type": "notice", "message": L("接著抓上次沒抓完的 \(jobs.count) 個", "Picking up \(jobs.count) unfinished from last time")])
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { self.enqueue(jobs, fresh: true) }
    }

    // ── 下載中不讓 Mac 睡著（螢幕照樣可以關）──

    private func setBusy(_ busy: Bool) {
        if busy {
            if activity == nil {
                activity = ProcessInfo.processInfo.beginActivity(
                    options: [.idleSystemSleepDisabled, .suddenTerminationDisabled, .automaticTerminationDisabled],
                    reason: "Fully is downloading")
            }
        } else if task == nil, !Follows.shared.checking, let a = activity {
            ProcessInfo.processInfo.endActivity(a)
            activity = nil
        }
    }

    /// 存放資料夾所在的磁碟還剩多少（資料夾還沒建就往上找）
    private func freeBytes(_ path: String) -> Int64? {
        var u = URL(fileURLWithPath: path)
        while !FileManager.default.fileExists(atPath: u.path), u.path != "/" { u.deleteLastPathComponent() }
        return (try? u.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?.volumeAvailableCapacityForImportantUsage
    }

    // MARK: 跑引擎

    private func run(_ job: Job) {
        cur = job
        curSource = [:]; lastErr = ""; lastErrEvent = [:]; sawDone = false; cancelled = false; frac = -1
        emit(["type": "started", "url": job.url])   // 介面要知道現在抓的是哪個網址：拖放／自動下載進來的，失敗後才能「再試一次」

        // 空間不夠先講（1 GB 以下），不要抓到一半才炸
        if let free = freeBytes(dest), free < 1_000_000_000 {
            let msg = L("存放的磁碟剩不到 1 GB。先清出一點空間再抓，或在「設定」換一個存放位置。",
                        "Less than 1 GB left on the disk you save to. Free up some space, or pick another folder in Settings.")
            lastErr = msg
            emit(["type": "error", "message": msg, "nospace": true])
            finish(job: job, exitOK: false)
            return
        }
        setBusy(true)
        if job.card { ClipCard.shared.progress(url: job.url, frac: -1, text: L("正在看這是什麼…", "Taking a look…")) }
        updateSide()

        prepareArgs(job) { extra in
            // 影片的「要什麼」：audio 只要聲音／data 標題與留言／frames 每個鏡頭截圖；av（預設）＝影片本身
            let flag: [String] = ["audio": ["--audio"], "data": ["--data"], "frames": ["--frames"]][job.mode] ?? []
            let tail = ["--json"] + flag + extra + (job.list != nil ? [self.dest] : [job.url, self.dest])
            let started = EngineRunner.start(tail, onEvent: { ev in self.handle(ev, job: job) },
                                             onExit: { code in self.engineExited(code, job: job) })
            guard let started else {
                self.task = nil
                let msg = L("叫不動下載引擎，app 可能沒打包完整。", "Couldn't start the download engine — the app may be incomplete.")
                self.lastErr = msg
                self.emit(["type": "error", "message": msg])
                self.finish(job: job, exitOK: false)
                return
            }
            self.task = started.process
            if self.selftest != nil { print("ENGINE \(started.kind)") }
            self.persistQueue()
        }
    }

    /// 引擎的額外參數：挑幾張、預先列好的清單
    private func prepareArgs(_ job: Job, done: @escaping ([String]) -> Void) {
        var a: [String] = []
        if let p = job.pick, !p.isEmpty { a += ["--pick", p] }
        if let l = job.list { a += ["--list", l] }
        done(a)
    }

    private func handle(_ ev: [String: Any], job: Job) {
        var ev = ev
        switch ev["type"] as? String {
        case "source":
            curSource = ev
            frac = (ev["count"] as? Int ?? 0) > 0 ? 0 : -1
            if job.card { ClipCard.shared.progress(url: job.url, frac: frac ?? -1, text: L("下載中…", "Downloading…")) }
        case "progress":
            frac = Double(ev["percent"] as? Int ?? 0) / 100
            if job.card { ClipCard.shared.progress(url: job.url, frac: frac ?? 0, text: L("下載中 \(Int((frac ?? 0) * 100))%", "Downloading \(Int((frac ?? 0) * 100))%")) }
        case "item":
            let total = curSource["count"] as? Int ?? 0
            let i = ev["index"] as? Int ?? 0
            frac = total > 0 ? Double(i) / Double(total) : -1
            if job.card {
                ClipCard.shared.progress(url: job.url, frac: frac ?? -1,
                                         text: total > 0 ? L("\(i)／\(total) 張", "\(i) of \(total)") : L("\(i) 張", "\(i) saved"))
            }
        case "error":
            lastErr = ev["message"] as? String ?? ""
            lastErrEvent = ev
        case "done":
            sawDone = true
            if let f = ev["folder"] as? String, !f.isEmpty { lastFolder = f }
            ev["url"] = job.url
            ev["mode"] = job.mode
            lastDone = ev
            ev["following"] = Follows.shared.isFollowing(job.url)
            doneArrived(ev, job: job)
        default: break
        }
        emit(ev)
        updateSide()
    }

    private func doneArrived(_ ev: [String: Any], job: Job) {
        let file = ev["file"] as? String
        let name = (ev["headline"] as? String) ?? (curSource["name"] as? String) ?? ""
        let added = ev["added"] as? Int ?? 0
        let detail = Self.proofLine(ev)
        var cardDetail = Self.proofLine(ev, compact: true)
        if added > 1 {       // 一整批：卡片那行比較窄，只講張數與最大尺寸（幾倍留給完成畫面）
            let w = ev["w"] as? Int ?? 0, h = ev["h"] as? Int ?? 0
            cardDetail = L("\(added) 張", "\(added) saved") + (w > 0 ? L("・最大 \(w) × \(h)", " · up to \(w) × \(h)") : "")
        } else if added == 0 {
            cardDetail = Self.nothingLine(ev)
        }
        let head = Self.doneHead(ev)
        recordHistory(ev, job: job)
        batch.append((name: name, ok: true, msg: "", job: job))

        // 單張圖：原圖直接進剪貼簿（⌘V 貼進 Figma／Keynote）
        var copied = false
        if added == 1, let f = file, Prefs.copyAfter, Self.isImage(f), selftest == nil {
            copied = copyToPasteboard(f)
            if copied { emit(["type": "copied"]) }
        }
        let thumbSrc = file ?? (ev["first"] as? String) ?? (ev["sheet"] as? String) ?? (ev["dup_of"] as? String)
        if let f = thumbSrc {
            Thumbs.dataURL(for: f, side: 160) { d in
                if let d { self.emit(["type": "thumb", "data": d]) }
                if job.card { ClipCard.shared.done(url: job.url, title: head, meta: cardDetail.isEmpty ? name : cardDetail, thumbData: d) }
            }
        } else if job.card {
            // 什麼都沒存（太小／沒抓到）：卡片按鈕改成「看細節」，不讓人打開一個空資料夾
            ClipCard.shared.done(url: job.url, title: head, meta: cardDetail.isEmpty ? name : cardDetail, thumbData: nil,
                                 canOpen: added > 0)
        }
        let body = [name, detail, copied ? L("原圖已在剪貼簿", "Original is on your clipboard") : ""].filter { !$0.isEmpty }.joined(separator: "・")
        notify(head,
               body: body + L("（點一下顯示檔案）", " (click to show)"), file: file ?? (ev["dup_of"] as? String), folder: ev["folder"] as? String,
               thumb: thumbSrc)
    }

    /// 完成的大字：面板（ui.html done()）、預覽卡、通知三處同一套判斷
    static func doneHead(_ ev: [String: Any]) -> String {
        let n = ev["added"] as? Int ?? 0, sk = ev["skipped"] as? Int ?? 0, du = ev["dups"] as? Int ?? 0
        let sm = ev["small"] as? Int ?? 0, fl = ev["failed"] as? Int ?? 0
        if n > 0 { return (ev["preview_only"] as? Bool == true) ? L("只有預覽圖", "Preview image only") : L("存好了", "Saved") }   // 頁面本身讀不到圖，只存到分享預覽圖
        if du > 0 { return L("早就有了", "Already saved") }
        if sk > 0 && sm >= sk { return L("沒有夠大的圖", "No big images") }
        if sk == 0 && fl > 0 { return L("這次沒抓到", "Nothing came through") }
        return L("之前就抓過了", "Already saved")
    }

    /// 一張都沒存的時候，卡片那行講為什麼
    static func nothingLine(_ ev: [String: Any]) -> String {
        let sk = ev["skipped"] as? Int ?? 0, du = ev["dups"] as? Int ?? 0
        let sm = ev["small"] as? Int ?? 0, fl = ev["failed"] as? Int ?? 0
        if du > 0 { return L("跟之前抓的一模一樣", "Identical to one you already have") }
        if sk > 0 && sm >= sk { return L("都太小（像圖示），沒有存", "All too small (icons) — nothing saved") }
        if sk == 0 && fl > 0 { return L("\(fl) 張抓不到", "\(fl) couldn't be fetched") }
        return L("全部都已經在資料夾裡", "All already in the folder")
    }

    /// 「拿到多大」一句話（通知、預覽卡用；介面層自己組中英）。compact＝預覽卡那行比較窄
    static func proofLine(_ ev: [String: Any], compact: Bool = false) -> String {
        guard let w = ev["w"] as? Int, let h = ev["h"] as? Int, w > 0 else { return "" }
        if let res = ev["res"] as? String {        // 影片：畫質
            let fps = ev["fps"] as? Int ?? 0
            return "\(w) × \(h)・" + res + (fps > 30 ? "\(fps)" : "") + ((ev["hdr"] as? Bool == true) ? " HDR" : "")
        }
        var s = "\(w) × \(h)"
        if let pw = ev["page_w"] as? Int, pw > 0, Double(w) / Double(pw) >= 1.3 {
            let r = Double(w) / Double(pw)
            let rs = r >= 10 ? "\(Int(r.rounded()))" : String(format: "%.1f", r)
            s += compact ? L("・頁面上的 \(rs) 倍", " · \(rs)× the page") : L("・頁面上那張的 \(rs) 倍", " · \(rs)× the one on the page")
        }
        return s
    }

    static func isImage(_ path: String) -> Bool {
        ["jpg", "jpeg", "png", "gif", "webp", "avif", "heic", "tiff", "bmp", "svg"].contains((path as NSString).pathExtension.lowercased())
    }

    /// 原圖放進剪貼簿：檔案 URL（貼進 Finder／Keynote 是檔案）＋圖片資料（貼進 Figma 是圖）。不放網址文字——在聊天軟體會貼成網址。
    private func copyToPasteboard(_ path: String) -> Bool {
        guard let data = FileManager.default.contents(atPath: path) else { return false }
        let pb = NSPasteboard.general
        pb.clearContents()
        let it = NSPasteboardItem()
        it.setString(URL(fileURLWithPath: path).absoluteString, forType: .fileURL)
        let ext = (path as NSString).pathExtension.lowercased()
        if ext == "png" { it.setData(data, forType: .png) }
        else if ext == "jpg" || ext == "jpeg" { it.setData(data, forType: NSPasteboard.PasteboardType("public.jpeg")) }
        if ext != "png", ext != "svg", let img = NSImage(data: data), img.size.width * img.size.height < 40_000_000,
           let tiff = img.tiffRepresentation {
            it.setData(tiff, forType: .tiff)
        }
        it.setData(Data(), forType: Self.selfMarker)
        let ok = pb.writeObjects([it])
        lastPasteCount = pb.changeCount
        return ok
    }

    private func engineExited(_ code: Int32, job: Job) {
        task = nil
        if !sawDone, !cancelled {
            if lastErr.isEmpty {
                lastErr = L("下載中斷了（代碼 \(code)）。", "The download stopped (code \(code)).")
                emit(["type": "error", "message": lastErr])
            }
            if job.card { ClipCard.shared.failed(url: job.url, message: lastErr) }
        }
        finish(job: job, exitOK: sawDone)
    }

    private func finish(job: Job, exitOK: Bool) {
        task = nil
        if !exitOK, !cancelled {
            var nm = (curSource["name"] as? String) ?? job.url
            if nm == "影片" || nm == "Video" { nm = job.url }      // 影片線還沒拿到片名時的暫稱，失敗清單上改寫網址
            batch.append((name: nm, ok: false, msg: lastErr, job: job))
        }
        if !cancelled { queueDone += 1 }
        cur = nil
        frac = nil
        persistQueue()
        emitQueue()
        if !queue.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { self.runNext() }
            return
        }
        // 整批跑完
        setBusy(false)
        let okN = batch.filter { $0.ok }.count
        if okN > 0 { SideIcons.shared.flashDone() } else { updateSide() }
        failedJobs = batch.filter { !$0.ok }.map { $0.job }
        // 多網址結算：幾個完成、哪幾個抓不到（單支不另外講）
        if queueTotal > 1 {
            let failed = batch.filter { !$0.ok }.map { ["name": $0.name, "msg": $0.msg] }
            emit(["type": "batch", "ok": okN, "total": queueTotal, "failed": failed])
            if !cancelled {
                notify(L("全部跑完", "All done"),
                       body: L("\(okN) 個完成", "\(okN) done") + (failed.isEmpty ? "" : L("，\(failed.count) 個抓不到", ", \(failed.count) couldn't be grabbed")),
                       folder: lastFolder)
            }
        }
        batch.removeAll()
        if selftest != nil { finishSelftest() }
    }

    /// 最近抓的：存 30 筆，待命畫面列出，點了在 Finder 顯示
    private func recordHistory(_ done: [String: Any], job: Job) {
        guard selftest == nil else { return }
        let f = DateFormatter(); f.dateFormat = "M/d HH:mm"
        var item: [String: Any] = [
            "name": (done["headline"] as? String) ?? (curSource["name"] as? String) ?? job.url,
            "kind": (curSource["label"] as? String) ?? (curSource["kind"] as? String) ?? "",
            "folder": (done["folder"] as? String) ?? "",
            "when": f.string(from: Date()),
            "added": done["added"] as? Int ?? 0,
            "mode": job.mode,
            "url": job.url,
        ]
        if let file = done["file"] as? String { item["file"] = file }
        if let sheet = done["sheet"] as? String { item["sheet"] = sheet }
        if let dims = done["dims"] as? String { item["dims"] = dims }
        var h = history
        h.removeAll { ($0["url"] as? String) == job.url && ($0["folder"] as? String) == (done["folder"] as? String) }
        h.insert(item, at: 0)
        history = h
        emit(["type": "history", "items": Array(h.prefix(8))])
    }

    /// 這個網址抓過嗎（預覽卡的「抓過了 月/日」）
    private func seenDate(_ url: String) -> String? {
        guard let it = history.first(where: { ($0["url"] as? String) == url }), let w = it["when"] as? String else { return nil }
        return w.components(separatedBy: " ").first
    }

    // MARK: 預覽

    private func probe(_ url: String, items: Bool = false, manual: Bool = false) {
        if !items, let c = probeCache[url] { deliver(c, items: false); return }
        // 不是一看就知道是圖的網址：先確認看一眼是安全的（一次性連結、內網不自動去看）；使用者自己按「看一下」則照看
        if !manual, !Self.looksLikeMedia(url), !Self.safeToProbe(url) { return }
        probeProc?.terminate()
        probeFor = url + (items ? "#items" : "")
        let key = probeFor
        prepareArgs(Job(url: url)) { extra in
            let tail = ["--json", "--probe"] + (items ? ["--items"] : []) + extra + [url, self.dest]
            let started = EngineRunner.start(tail, onEvent: { ev in
                guard key == self.probeFor else { return }
                switch ev["type"] as? String {
                case "preview":
                    var p = ev
                    if let s = self.seenDate(url) { p["seen"] = s }
                    if !items { self.probeCache[url] = p }
                    self.deliver(p, items: items)
                case "error":
                    var p: [String: Any] = ["type": "preview", "url": url, "failed": true, "message": ev["message"] ?? ""]
                    if ev["not_public"] as? Bool == true { p["not_public"] = true }      // 不是公開的：預覽卡那行照實講
                    self.deliver(p, items: items)
                default: break
                }
            }, onExit: { _ in })
            self.probeProc = started?.process
        }
    }

    private func deliver(_ p: [String: Any], items: Bool) {
        if items {
            var d = p; d["type"] = "items"
            emit(d)
        } else {
            emit(p)
            ClipCard.shared.preview(p)
        }
    }

    // MARK: 剪貼簿監看（預設「問一聲」＝預覽卡）

    private func startWatch() {
        stopWatch()
        dlog("startWatch mode=\(Prefs.clipMode)")
        guard Prefs.clipMode != "off" else { return }
        lastPasteCount = NSPasteboard.general.changeCount
        watchTimer = Timer.scheduledTimer(withTimeInterval: 0.8, repeats: true) { [weak self] _ in self?.pollClipboard() }
    }

    private func stopWatch() {
        watchTimer?.invalidate()
        watchTimer = nil
    }

    /// FULLY_DEBUG=1 時把判斷過程印出來（剪貼簿監看、預覽）
    private static let debug = ProcessInfo.processInfo.environment["FULLY_DEBUG"] == "1"
    private func dlog(_ s: @autoclosure () -> String) { if Self.debug { print("[fully] " + s()); fflush(stdout) } }

    private func pollClipboard() {
        let pb = NSPasteboard.general
        guard pb.changeCount != lastPasteCount else { return }
        dlog("clipboard changed \(lastPasteCount) → \(pb.changeCount) types=\(pb.types?.map(\.rawValue) ?? [])")
        lastPasteCount = pb.changeCount
        if pb.types?.contains(Self.selfMarker) == true { return }              // 我們自己剛放進去的原圖
        guard let t = pb.string(forType: .string)?.trimmingCharacters(in: .whitespacesAndNewlines),
              t.hasPrefix("http"), t.count < 2048, !t.contains(" "), !t.contains("\n"),
              !recentURLs.contains(t) else { return }
        // 任何網址都問（看一眼之前會先過安全檢查）
        dlog("url=\(t) media=\(Self.looksLikeMedia(t)) mode=\(Prefs.clipMode)")
        recentURLs.append(t)
        if recentURLs.count > 8 { recentURLs.removeFirst() }

        // 面板開著而且在前面：直接放進面板的網址卡，不另外跳卡片
        if let f = floating, f.isVisible, NSApp.isActive {
            emit(["type": "clip", "url": t])
            return
        }
        switch Prefs.clipMode {
        case "auto":
            enqueue([Job(url: t, mode: "av", card: true)], fresh: task == nil && queue.isEmpty)
            ClipCard.shared.show(url: t, label: Self.hostLabel(t), seen: seenDate(t))
            ClipCard.shared.progress(url: t, frac: -1, text: L("排進去了", "Queued"))
        case "card":
            ClipCard.shared.show(url: t, label: Self.hostLabel(t), seen: seenDate(t))
            probe(t)
        default: break
        }
    }

    static func hostLabel(_ u: String) -> String {
        var h = URL(string: u)?.host ?? u
        if h.hasPrefix("www.") { h.removeFirst(4) }
        return h
    }

    private func setupCard() {
        ClipCard.shared.onAction = { [weak self] url, action in
            guard let self else { return }
            switch action {
            case .grab:
                self.enqueue([Job(url: url, mode: "av", card: true)], fresh: self.task == nil && self.queue.isEmpty)
                ClipCard.shared.progress(url: url, frac: -1, text: self.task == nil ? L("正在看這是什麼…", "Taking a look…") : L("排進去了", "Queued"))
            case .open:
                if let f = self.lastDone["file"] as? String ?? self.lastDone["sheet"] as? String, FileManager.default.fileExists(atPath: f) {
                    NSWorkspace.shared.open(URL(fileURLWithPath: f))
                } else if let d = self.lastFolder {
                    NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: d)
                }
            case .panel:
                self.showPanel()
                self.emit(["type": "clip", "url": url])
            }
        }
    }

    // MARK: 追蹤

    private func setupFollows() {
        let f = Follows.shared
        f.onChange = { [weak self] in self?.pushFollows() }
        f.onBusy = { [weak self] busy in self?.setBusy(busy) }
        f.onNews = { [weak self] news in
            let total = news.reduce(0) { $0 + $1.1 }
            self?.notify(L("追蹤的來源有新東西", "New from what you follow"),
                         body: L("\(news.count) 個來源、共 \(total) 個：", "\(news.count) sources, \(total) new: ") + news.map { $0.0.name }.prefix(3).joined(separator: "、"),
                         folder: news.first.map { URL(fileURLWithPath: $0.0.root).path })
        }
    }

    // MARK: 右鍵服務與 fully:// 連結

    /// 「服務 → 用 Fully 抓」：任何 app 裡選取的網址（或含網址的文字）
    @objc func grabService(_ pboard: NSPasteboard, userData: String?, error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        var text = pboard.string(forType: .string) ?? ""
        if let urls = pboard.readObjects(forClasses: [NSURL.self]) as? [URL] { text += "\n" + urls.map(\.absoluteString).joined(separator: "\n") }
        let found = Self.extractURLs(text)
        guard !found.isEmpty else {
            error.pointee = L("選取的文字裡沒有網址", "There's no link in the selection") as NSString
            return
        }
        enqueue(found.map { Job(url: $0, card: found.count == 1) }, fresh: task == nil && queue.isEmpty)
        if found.count == 1 {
            ClipCard.shared.show(url: found[0], label: Self.hostLabel(found[0]), seen: seenDate(found[0]))
            ClipCard.shared.progress(url: found[0], frac: -1, text: L("交給 Fully 了", "Handed to Fully"))
        } else {
            notify(L("交給 Fully 了", "Handed to Fully"), body: L("\(found.count) 個網址排進去了", "\(found.count) links queued"))
        }
    }

    static func extractURLs(_ s: String) -> [String] {
        guard let det = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return [] }
        var out: [String] = []
        det.enumerateMatches(in: s, range: NSRange(s.startIndex..., in: s)) { m, _, _ in
            if let u = m?.url?.absoluteString, u.hasPrefix("http"), !out.contains(u) { out.append(u) }
        }
        return out
    }

    /// fully://grab?url=…（書籤小工具、捷徑、Raycast）／fully://open?url=…（只帶進面板）
    func application(_ application: NSApplication, open urls: [URL]) {
        for u in urls where u.scheme == "fully" {
            let q = URLComponents(url: u, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let target = q.first { $0.name == "url" }?.value ?? ""
            let asked = q.first { $0.name == "mode" }?.value ?? "av"      // 影片：&mode=audio|frames|data
            let mode = ["av", "audio", "frames", "data"].contains(asked) ? asked : "av"
            switch u.host {
            case "grab" where target.hasPrefix("http"):
                enqueue([Job(url: target, mode: mode, card: true)], fresh: task == nil && queue.isEmpty)
                ClipCard.shared.show(url: target, label: Self.hostLabel(target), seen: seenDate(target))
                ClipCard.shared.progress(url: target, frac: -1, text: L("交給 Fully 了", "Handed to Fully"))
            case "open" where target.hasPrefix("http"):
                showPanel()
                emit(["type": "clip", "url": target])
            default:
                showPanel()
            }
        }
    }

    // MARK: 使用規範、隱私（app 內閱讀）

    private func openDoc(_ name: String) {
        let file = name == "privacy" ? "privacy" : "terms"
        guard let p = Bundle.main.path(forResource: file, ofType: "md", inDirectory: "docs"),
              var s = try? String(contentsOfFile: p, encoding: .utf8) else { return }
        let title = s.split(separator: "\n").first { $0.hasPrefix("# ") }.map { String($0.dropFirst(2)) } ?? "Fully"
        // 文件是中英各一段（## 中文／## English）：只給介面語言那段；草稿註記（> 開頭）不給
        let pickLang: (String) -> String = { t in
            guard let r = t.range(of: "\n## English") else { return t }
            return Lang.isEn ? String(t[r.upperBound...]) : String(t[..<r.lowerBound])
        }
        s = pickLang(s)
        let lines = s.split(separator: "\n", omittingEmptySubsequences: false)
            .filter { !$0.hasPrefix(">") && !$0.hasPrefix("# ") && $0.trimmingCharacters(in: .whitespaces) != "## 中文" }
        emit(["type": "doc", "doc": file, "title": title, "md": lines.joined(separator: "\n")])
    }

    // MARK: 通知

    private func notify(_ title: String, body: String, file: String? = nil, folder: String? = nil, thumb: String? = nil) {
        guard selftest == nil, !isSnapshotRun else { return }
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { ok, _ in
            guard ok else { return }
            let send: (URL?) -> Void = { att in
                let c = UNMutableNotificationContent()
                c.title = title
                c.body = String(body.prefix(120))
                var info: [String: String] = [:]
                if let file { info["file"] = file }
                if let folder { info["folder"] = folder }
                c.userInfo = info
                if let att, let a = try? UNNotificationAttachment(identifier: "thumb", url: att, options: nil) { c.attachments = [a] }
                center.add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
            }
            // 通知附縮圖（看一眼就知道抓對了）。通知中心會把附件搬走，所以給的是暫存的一份
            if let t = thumb { DispatchQueue.main.async { Thumbs.tempFile(for: t) { send($0) } } } else { send(nil) }
        }
    }

    /// 點通知＝直接在 Finder 顯示那個檔
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        DispatchQueue.main.async {
            if let f = info["file"] as? String, FileManager.default.fileExists(atPath: f) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: f)])
            } else if let d = info["folder"] as? String, FileManager.default.fileExists(atPath: d) {
                NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: d)
            }
            done()
        }
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])   // app 在前景也照樣跳
    }


    // MARK: 驗收鉤

    /// --card-demo <ask|run|done|err> --snapshot <png>：擺好預覽卡拍下來（官網與設計審查；不碰網路）
    private func cardDemo(_ state: String) {
        let (url, label, title) = ("https://www.intention.ltd/made", "intention.ltd", "INTENTION Made")   // 截圖用的假資料：自己的網頁
        var thumb: String? = nil
        if let p = Bundle.main.path(forResource: "AppIcon", ofType: "icns") {
            Thumbs.dataURL(for: p, side: 160) { thumb = $0 }
        }
        ClipCard.shared.show(url: url, label: label, seen: state == "ask" ? nil : nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            let base: [String: Any] = ["type": "preview", "url": url, "label": label, "name": title, "count": 42,
                                       "w": 4032, "h": 3024, "multi": true]
            ClipCard.shared.preview(base)
            switch state {
            case "run": ClipCard.shared.progress(url: url, frac: 0.62, text: L("26／42 張", "26 of 42"))
            case "done": ClipCard.shared.done(url: url, title: L("存好了", "Saved"), meta: "4032 × 3024" + L("・頁面上的 17 倍", " · 17× the page"), thumbData: thumb)
            case "err": ClipCard.shared.failed(url: url, message: L("這個網頁不是公開的。Fully 只存公開看得到的圖。", "This page isn't public. Fully only saves images that are publicly visible."))
            default: break
            }
        }
        let a = CommandLine.arguments
        guard let i = a.firstIndex(of: "--snapshot"), a.count > i + 1 else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
            ClipCard.shared.snapshot(to: a[i + 1]) { exit(0) }
        }
    }

    private func finishSelftest() {
        // 等最後一批事件走完 JS 的事件迴圈再讀 DOM
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            let probe = """
            (() => { const t = id => (document.getElementById(id) || {}).textContent || null;
              return JSON.stringify({
                state:  t('state'),
                sub:    (t('sub') || '').replace(/\\s+/g, ' ').trim(),
                proof:  t('proof'),
                mode:   document.body.dataset.state,
                view:   document.body.dataset.v,
                orb:    document.body.dataset.o,
                label:  t('orbLabel'),
                card:   t('cardTitle'), cardUrl: t('cardUrl'),
                name:   t('nameLine'), note: t('note'),
                p:      (document.getElementById('arc') || {style: {getPropertyValue: () => ''}}).style.getPropertyValue('--p'),
                resolving: document.body.classList.contains('resolving'),
                page:   document.body.dataset.page || ''
              }); })()
            """
            self.web.evaluateJavaScript(probe) { result, err in
                if let s = result as? String { print("SELFTEST \(s)") }
                else { print("SELFTEST FAILED \(err?.localizedDescription ?? "no result")") }

                // --snapshot <png>：把 WKWebView 實際渲染的畫面存成圖，用來目視驗收
                let a = CommandLine.arguments
                guard let i = a.firstIndex(of: "--snapshot"), a.count > i + 1 else { exit(0) }
                let cfg = WKSnapshotConfiguration()
                cfg.rect = CGRect(origin: .zero, size: Const.panelSize)
                self.web.takeSnapshot(with: cfg) { img, _ in
                    if let img,
                       let tiff = img.tiffRepresentation,
                       let rep = NSBitmapImageRep(data: tiff),
                       let png = rep.representation(using: .png, properties: [:]) {
                        try? png.write(to: URL(fileURLWithPath: a[i + 1]))
                        print("SNAPSHOT \(a[i + 1])")
                    }
                    exit(0)
                }
            }
        }
    }
}

// ─── 進入點 ──────────────────────────────────────────────────────────

/// 把一張 NSImage 或一個 NSView 畫成 PNG（驗收用）
func writePNG(size: NSSize, scale: CGFloat, to path: String, draw: () -> Void) {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale), pixelsHigh: Int(size.height * scale),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = size
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
}

// --statusicon <png>：選單列圖示的四個狀態（平常／進度 62%／讀取中／存好了）排成一排，8 倍大（選單列自動隱藏的機器截不到）
if let i = CommandLine.arguments.firstIndex(of: "--statusicon"), CommandLine.arguments.count > i + 1 {
    let states: [NSImage] = [StatusIcon.make(), StatusIcon.make(progress: 0.62), StatusIcon.make(progress: -1, phase: 1.2), StatusIcon.make(done: true)]
    writePNG(size: NSSize(width: 18 * 4 + 12 * 3, height: 18), scale: 8, to: CommandLine.arguments[i + 1]) {
        for (k, img) in states.enumerated() {
            let tinted = NSImage(size: img.size, flipped: false) { r in
                img.draw(in: r); NSColor.black.set(); r.fill(using: .sourceAtop); return true
            }
            tinted.draw(in: NSRect(x: CGFloat(k) * 30, y: 0, width: 18, height: 18))
        }
    }
    print("STATUSICON \(CommandLine.arguments[i + 1])")
    exit(0)
}
// --dock-demo <png>：Dock 圖示的四個狀態（進度 62%＋還有 3 個／讀取中／存好了／平常）
if let i = CommandLine.arguments.firstIndex(of: "--dock-demo"), CommandLine.arguments.count > i + 1 {
    _ = NSApplication.shared
    let v = DockTileView(frame: NSRect(x: 0, y: 0, width: 256, height: 256))
    let states: [(Double?, Int, Bool)] = [(0.62, 3, false), (-1, 0, false), (nil, 0, true), (nil, 0, false)]
    writePNG(size: NSSize(width: 256 * 4 + 24 * 3, height: 256), scale: 1, to: CommandLine.arguments[i + 1]) {
        for (k, s) in states.enumerated() {
            v.progress = s.0; v.badge = s.1; v.done = s.2; v.phase = 1.1
            NSGraphicsContext.saveGraphicsState()
            let t = NSAffineTransform(); t.translateX(by: CGFloat(k) * 280, yBy: 0); t.concat()
            v.draw(v.bounds)
            NSGraphicsContext.restoreGraphicsState()
        }
    }
    print("DOCKDEMO \(CommandLine.arguments[i + 1])")
    exit(0)
}

let app = NSApplication.shared
let controller = Controller()
app.delegate = controller
app.run()
