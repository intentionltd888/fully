// Engines.swift — 影片引擎（yt-dlp）自更新（兩版共用）
//
// 為什麼：影片網站一改版，舊引擎就抓不到；不能每次都等人換 vendor/bin 重出 DMG。
// 做法：yt-dlp 官方單檔本來就會自己更新（--update-to，會驗 SHA2-256SUMS、原子換檔），
// 只是它得住在可寫的地方——簽過章的 app 包裡不行。所以：
//   ・首次啟動把包內出廠版複製到 ~/Library/Application Support/Fully/engines/yt-dlp
//   ・之後每天背景跑一次 `yt-dlp --update-to stable@latest`（只連 github.com；設定裡可以關）
//   ・換完先 --version 起得來才算數；起不來退回 .prev，再不行退回包內出廠版
//   ・引擎（grab.py）透過環境變數 FULLY_YTDLP／FULLY_ENGINES_DIR 知道用哪一支；搶先版槽由它自己管
// ffmpeg／qjs 用包內版（只在本機處理檔案，不跟著網站改版）。
import Foundation

final class EngineManager {
    static let shared = EngineManager()

    struct Status {
        var ytdlp = "—"
        var source = "出廠版"      // 出廠版／更新版
        var status = "還沒檢查"
        var checkedAt = ""
        var auto = true
        var checking = false
        var gallery = "—"
        var ffmpeg = "—"
        var dict: [String: Any] {
            ["type": "engine", "ytdlp": ytdlp, "source": source, "status": status,
             "checkedAt": checkedAt, "auto": auto, "checking": checking,
             "gallery": gallery, "ffmpeg": ffmpeg]
        }
    }

    let dir = NSHomeDirectory() + "/Library/Application Support/Fully/engines"
    var stable: String { dir + "/yt-dlp" }
    private let checkedKey = "FullyEngineCheckedAt"
    private let statusKey = "FullyEngineStatus"
    private let autoOffKey = "FullyAutoUpdateOff"
    private(set) var checking = false
    private let q = DispatchQueue(label: "ltd.intention.fully.engines", qos: .utility)
    private let lock = NSLock()   // ensureStable 會從「ready 的背景」與「第一支工作的 environment」兩邊進來，不鎖會撞成兩份半成品

    var autoOn: Bool {
        get { !UserDefaults.standard.bool(forKey: autoOffKey) }
        set { UserDefaults.standard.set(!newValue, forKey: autoOffKey) }
    }

    var bundled: String? { Bundle.main.path(forResource: "yt-dlp", ofType: nil, inDirectory: "bin") }

    /// build.sh 寫的 Resources/engine-versions.txt（key=value 一行一個）；讀檔比逐支跑 --version 快得多
    lazy var shipped: [String: String] = {
        guard let p = Bundle.main.path(forResource: "engine-versions", ofType: "txt"),
              let s = try? String(contentsOfFile: p, encoding: .utf8) else { return [:] }
        var d: [String: String] = [:]
        for line in s.split(separator: "\n") {
            let kv = line.split(separator: "=", maxSplits: 1).map { String($0).trimmingCharacters(in: .whitespaces) }
            if kv.count == 2 { d[kv[0]] = kv[1] }
        }
        return d
    }()

    /// 現在會被拿來用的那支：Application Support 有且能跑 → 它；否則 nil（引擎自己退回包內）
    var activePath: String? {
        FileManager.default.isExecutableFile(atPath: stable) ? stable : nil
    }

    /// 給 grab.py 的環境變數。第一次拿的時候順便把出廠版放好（selftest 與首啟都走這裡，才不會第一支還在用包內版）。
    private var ensuredOnce = false
    var environment: [String: String] {
        if !ensuredOnce {
            ensuredOnce = true
            // 實測：主執行緒上絕不等。第一次叫引擎常是預覽卡——在這裡同步跑 yt-dlp --version
            // 會把整個介面凍住好幾秒，卡片畫不上螢幕（sample 抓到卡在 ensureStable 的鎖與 --version）。
            // 改成丟背景；還沒放好的這一次引擎自己退回包內出廠版（ensureStable 是 .new 再原子換名，不會拿到半截檔）。
            if Thread.isMainThread { q.async { _ = self.ensureStable() } } else { _ = ensureStable() }
        }
        var env = ProcessInfo.processInfo.environment
        env["FULLY_ENGINES_DIR"] = dir
        if let a = activePath { env["FULLY_YTDLP"] = a }
        return env
    }

    // MARK: 版本

    @discardableResult
    private func run(_ args: [String], timeout: TimeInterval) -> (code: Int32, out: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: args[0])
        p.arguments = Array(args.dropFirst())
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        do { try p.run() } catch { return (-1, "\(error.localizedDescription)") }
        let killer = DispatchWorkItem { if p.isRunning { p.terminate() } }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        killer.cancel()
        return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }

    func version(of path: String) -> String? {
        guard FileManager.default.isExecutableFile(atPath: path) else { return nil }
        let r = run([path, "--version"], timeout: 40)
        let v = r.out.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "\n").last.map(String.init) ?? ""
        return (r.code == 0 && v.range(of: #"^\d{4}\.\d{2}\.\d{2}"#, options: .regularExpression) != nil) ? v : nil
    }

    /// 第一次（或 App Support 那份比包內舊／壞掉）把出廠版放進去。回傳現在用的路徑。
    @discardableResult
    func ensureStable() -> String? {
        lock.lock(); defer { lock.unlock() }
        guard let b = bundled else { return nil }
        let fm = FileManager.default
        try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let shippedVer = shipped["yt-dlp"] ?? ""
        let cur = version(of: stable)
        let stale = cur == nil || (!shippedVer.isEmpty && cur! < shippedVer)   // 版號 YYYY.MM.DD 字串比較即可
        if stale {
            let tmp = stable + ".new"
            try? fm.removeItem(atPath: tmp)   // 只清自己上一輪留下的暫存檔
            do {
                try fm.copyItem(atPath: b, toPath: tmp)
                try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: tmp)
                if fm.fileExists(atPath: stable) { _ = try? fm.replaceItemAt(URL(fileURLWithPath: stable + ".prev"), withItemAt: URL(fileURLWithPath: stable)) }
                try fm.moveItem(atPath: tmp, toPath: stable)
                NSLog("Fully engines: 出廠版 yt-dlp \(shippedVer) → \(stable)")
            } catch {
                NSLog("Fully engines: 放出廠版失敗 \(error)")
                return nil
            }
        }
        return activePath
    }

    // MARK: 狀態

    /// fast＝不跑 --version（只讀版本表），給介面第一眼用；之後背景再補真實狀態
    func status(fast: Bool = false) -> Status {
        var s = Status()
        s.auto = autoOn
        s.checking = checking
        s.ffmpeg = shipped["ffmpeg"] ?? "—"
        if !fast, let a = activePath, let v = version(of: a) {
            s.ytdlp = v
            s.source = (v == (shipped["yt-dlp"] ?? "")) ? "出廠版" : "更新版"
        } else {
            s.ytdlp = shipped["yt-dlp"] ?? "—"
            s.source = "出廠版"
        }
        if let d = UserDefaults.standard.object(forKey: checkedKey) as? Date {
            let f = DateFormatter(); f.dateFormat = "M/d HH:mm"
            s.checkedAt = f.string(from: d)
            s.status = UserDefaults.standard.string(forKey: statusKey) ?? "已檢查"
        }
        if !autoOn { s.status = "自動更新已關，用出廠版或上次更新的版本" }
        return s
    }

    var dueForCheck: Bool {
        guard autoOn else { return false }
        guard let d = UserDefaults.standard.object(forKey: checkedKey) as? Date else { return true }
        return Date().timeIntervalSince(d) > 24 * 3600
    }

    /// 背景檢查更新。force＝不管 24 小時與開關，現在就查。完成後在主執行緒回呼最新狀態。
    func checkForUpdate(force: Bool, onChange: @escaping (Status) -> Void) {
        guard !checking else { return }
        guard force || dueForCheck else { return }
        checking = true
        var s = status(fast: true); s.checking = true; s.status = "正在檢查更新…"   // 主執行緒上只用 fast（不跑 --version）
        onChange(s)
        q.async {
            guard let path = self.ensureStable() else {
                var s = self.status(); s.status = "找不到引擎（app 沒打包完整）"   // 在背景算好再交給主執行緒
                DispatchQueue.main.async {
                    self.checking = false
                    onChange(s)
                }
                return
            }
            let before = self.version(of: path) ?? "?"
            let r = self.run([path, "--update-to", "stable@latest"], timeout: 240)
            var note: String
            if r.out.contains("is up to date") {
                note = "已是最新（\(before)）"
            } else if let m = r.out.range(of: #"Updated yt-dlp to \S+"#, options: .regularExpression) {
                let v = String(r.out[m]).replacingOccurrences(of: "Updated yt-dlp to ", with: "")
                note = "已更新到 \(v.replacingOccurrences(of: "stable@", with: ""))"
            } else if r.code == 0 {
                note = "已檢查（\(before)）"
            } else {
                note = "檢查失敗，可能沒有網路；先用 \(before)"
            }
            // 換完要起得來才算數；起不來退回上一版，再不行退回出廠版
            if self.version(of: path) == nil {
                let fm = FileManager.default
                if fm.fileExists(atPath: path + ".prev"),
                   (try? fm.replaceItemAt(URL(fileURLWithPath: path), withItemAt: URL(fileURLWithPath: path + ".prev"))) != nil,
                   self.version(of: path) != nil {
                    note = "更新後起不來，已退回上一版"
                } else {
                    try? fm.removeItem(atPath: path)      // 壞掉的自己人檔案
                    self.ensureStable()
                    note = "更新後起不來，已退回出廠版"
                }
            }
            UserDefaults.standard.set(Date(), forKey: self.checkedKey)
            UserDefaults.standard.set(note, forKey: self.statusKey)
            let st = self.status()                  // 在背景算（會跑 --version），主執行緒只拿結果
            DispatchQueue.main.async {
                self.checking = false
                onChange(st)
            }
        }
    }
}
