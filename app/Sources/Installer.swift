// Installer.swift — 從 DMG 直接雙擊也能裝：自己搬進「應用程式」、加進 Dock、從那裡重新打開
//
// DMG 是唯讀映像，拖曳過程不會執行任何程式，所以「拖完自動做事」做不到；能做的是兩條路：
//   ① 使用者直接雙擊 DMG 裡的 Fully → 這裡接手：問一次 → 複製到 /Applications → 加進 Dock → 從新位置打開 → 退出舊的、退出磁碟映像
//   ② 使用者照舊拖進「應用程式」再打開 → 第一次從 /Applications 啟動時把自己加進 Dock（只釘一次，見 main.swift）；
//      之後每次啟動只檢查 Dock 那格有沒有指對（換版後會指著垃圾桶裡的舊版），指錯才修
import Cocoa

enum Installer {
    static let appName = "Fully"
    static var installedURL: URL { URL(fileURLWithPath: "/Applications/\(appName).app") }

    /// 從磁碟映像跑（含 macOS 對「下載回來的 app」套的 App Translocation 隨機路徑）
    static var isRunningFromDiskImage: Bool {
        let p = Bundle.main.bundlePath
        return p.hasPrefix("/Volumes/") || p.contains("/AppTranslocation/")
    }
    static var isRunningFromApplications: Bool { Bundle.main.bundlePath.hasPrefix("/Applications/") }

    /// DMG 裡雙擊的入口。問一次；同意就自己裝好並從 /Applications 重開（本行程隨後 exit），拒絕就教他拖然後 exit。
    static func offerInstallFromDiskImage(autoYes: Bool = false) {
        NSApp.activate(ignoringOtherApps: true)
        var yes = autoYes
        if !yes {
            let a = NSAlert()
            a.messageText = L("把 Fully 放進「應用程式」？", "Move Fully to Applications?")
            a.informativeText = L("Fully 會自己複製到「應用程式」、加進 Dock，然後從那裡打開。之後按 ⌃⌥⌘V 或點 Dock 圖示就好。", "Fully copies itself to Applications, adds itself to the Dock and opens from there. After that, press ⌃⌥⌘V or click the Dock icon.")
            a.addButton(withTitle: L("放進應用程式並打開", "Move and Open"))
            a.addButton(withTitle: L("我自己拖", "I’ll Drag It Myself"))
            yes = a.runModal() == .alertFirstButtonReturn
        }
        guard yes else {
            let a = NSAlert()
            a.messageText = L("先安裝再打開", "Install first, then open")
            a.informativeText = L("請把 Fully 拖進「應用程式」資料夾，再從那裡打開。", "Drag Fully into the Applications folder, then open it from there.")
            a.runModal()
            exit(0)
        }
        do {
            try install()
        } catch {
            NSLog("Fully install failed: \(error)")
            let a = NSAlert()
            a.messageText = L("沒辦法自動放進「應用程式」", "Couldn’t move Fully to Applications")
            a.informativeText = "\(error.localizedDescription)\n\n" + L("請把 Fully 拖進「應用程式」資料夾，再從那裡打開。", "Drag Fully into the Applications folder, then open it from there.")
            a.runModal()
            exit(1)
        }
        let cfg = NSWorkspace.OpenConfiguration()
        cfg.activates = true
        // 同 bundle id 已在跑時，openApplication 只會「切到」正在跑的這顆（DMG 裡的自己）；要明講開新實例
        cfg.createsNewApplicationInstance = true
        if let v = diskImageVolume() { cfg.arguments = ["--eject", v] }
        NSWorkspace.shared.openApplication(at: installedURL, configuration: cfg) { _, err in
            if let err { NSLog("Fully relaunch failed: \(err)") }
            DispatchQueue.main.async { exit(0) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) { exit(0) }
    }

    /// 複製到 /Applications（舊版先請它退出、丟垃圾桶可還原，不 rm），再釘進 Dock。
    static func install() throws {
        let fm = FileManager.default
        let src = Bundle.main.bundleURL
        let dst = installedURL
        let me = ProcessInfo.processInfo.processIdentifier
        let bid = Bundle.main.bundleIdentifier ?? "ltd.intention.fullsize"
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: bid).filter { $0.processIdentifier != me }
        for r in others { r.terminate() }
        let deadline = Date().addingTimeInterval(6)
        while others.contains(where: { !$0.isTerminated }) && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        for r in others where !r.isTerminated { r.forceTerminate() }
        let olds = [dst]
        for old in olds where fm.fileExists(atPath: old.path) {
            var trashed: NSURL?
            try fm.trashItem(at: old, resultingItemURL: &trashed)
        }
        try fm.copyItem(at: src, to: dst)
        NSLog("Fully installed to \(dst.path) from \(src.path)")
        Dock.ensure(appURL: dst)
    }

    static func diskImageVolume() -> String? {
        let p = Bundle.main.bundlePath
        if p.hasPrefix("/Volumes/") {
            let parts = p.split(separator: "/", omittingEmptySubsequences: true)
            if parts.count >= 2 { return "/Volumes/\(parts[1])" }
        }
        let guess = "/Volumes/\(appName)"
        if FileManager.default.fileExists(atPath: "\(guess)/\(appName).app") { return guess }
        return nil
    }

    /// `--eject /Volumes/Fully`：從 /Applications 重開後把磁碟映像退出
    static func ejectLater(_ volume: String) {
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 2) {
            func detach(_ force: Bool) -> Bool {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/usr/bin/hdiutil")
                p.arguments = ["detach", volume] + (force ? ["-force"] : [])
                p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
                do { try p.run() } catch { return false }
                p.waitUntilExit()
                return p.terminationStatus == 0
            }
            if !detach(false) {
                Thread.sleep(forTimeInterval: 3)
                _ = detach(true)
            }
        }
    }
}

enum Dock {
    static let bundleID = "ltd.intention.fullsize"
    private static let domain = "com.apple.dock" as CFString
    private static let key = "persistent-apps" as CFString

    /// 這格是不是 Fully（同一個 bundle id，或檔名是 Fully.app）
    private static func isFully(_ tile: [String: Any]) -> Bool {
        guard let td = tile["tile-data"] as? [String: Any] else { return false }
        if (td["bundle-identifier"] as? String) == bundleID { return true }
        guard let fd = td["file-data"] as? [String: Any], let s = fd["_CFURLString"] as? String,
              let u = URL(string: s) else { return false }
        let names = ["Fully.app"]
        return names.contains(u.standardizedFileURL.lastPathComponent)
    }

    /// 這格實際指到哪。Dock 的書籤（book）追的是「那個檔案」不是路徑：舊版被丟進垃圾桶後，
    /// 路徑欄位還寫 /Applications/Fully.app，書籤卻指著垃圾桶裡的舊版（Dock 顯示舊圖示，重啟後整格掉出去）。
    private static func target(_ tile: [String: Any]) -> String? {
        guard let td = tile["tile-data"] as? [String: Any] else { return nil }
        if let book = td["book"] as? Data {
            var stale = false
            guard let u = try? URL(resolvingBookmarkData: book, options: [.withoutUI, .withoutMounting],
                                   relativeTo: nil, bookmarkDataIsStale: &stale) else { return nil }   // 解不開＝原檔已不在
            return u.standardizedFileURL.path
        }
        guard let fd = td["file-data"] as? [String: Any], let s = fd["_CFURLString"] as? String,
              let u = URL(string: s) else { return nil }
        return u.standardizedFileURL.path
    }

    /// 只有路徑、不帶書籤的乾淨一格（Dock 重啟後會自己替新檔補書籤）
    private static func cleanTile(_ path: String) -> [String: Any] {
        ["tile-type": "file-tile",
         "tile-data": ["file-data": ["_CFURLString": URL(fileURLWithPath: path, isDirectory: true).absoluteString,
                                     "_CFURLStringType": 15],
                       "file-label": "Fully", "bundle-identifier": bundleID, "file-type": 41] as [String: Any]]
    }

    /// 讓 Dock 上的 Fully 指到 appURL。改的是 com.apple.dock 的 persistent-apps，有改才重啟 Dock（閃一下）。
    ///   已經只有一格、而且指對 → 不動。
    ///   指錯（垃圾桶裡的舊版、書籤解不開）或重複 → 全部拿掉，在原本第一格的位置插回乾淨的一格。
    ///   沒釘：pinIfMissing＝true 釘在最後（安裝、第一次從「應用程式」打開）；false 不動（每次啟動的檢查，不替使用者多釘）。
    @discardableResult static func ensure(appURL: URL, pinIfMissing: Bool = true) -> Bool {
        var apps = (CFPreferencesCopyAppValue(key, domain) as? [[String: Any]]) ?? []
        let want = appURL.standardizedFileURL.path
        let mine = apps.indices.filter { isFully(apps[$0]) }
        if mine.isEmpty {
            guard pinIfMissing else { return false }
            apps.append(cleanTile(want))
        } else {
            if mine.count == 1, target(apps[mine[0]]) == want { return false }
            let at = mine[0]
            apps.removeAll { isFully($0) }
            apps.insert(cleanTile(want), at: min(at, apps.count))
        }
        CFPreferencesSetAppValue(key, apps as CFArray, domain)
        CFPreferencesAppSynchronize(domain)
        NSLog("Fully: Dock 那格指回 \(want)")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/killall")
        p.arguments = ["Dock"]
        try? p.run()
        return true
    }
}
