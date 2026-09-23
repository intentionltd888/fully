// Prefs.swift — 語言、設定值、叫引擎的共用管道
//
// 為什麼集中在這：同一支引擎有三種用法——主下載、預覽（複製網址就跳的卡片）、追蹤來源的定期檢查——
// 環境變數與「一行一個 JSON 事件」的讀法要一模一樣，不然三邊行為會慢慢分岔。
import Foundation

// ─── 語言 ─────────────────────────────────────────────────────────────

enum Lang {
    static let key = "FullyLang"                 // system／zh／en
    static var setting: String {
        get {
            let a = CommandLine.arguments                    // 截圖用：--lang zh／en
            if let i = a.firstIndex(of: "--lang"), a.count > i + 1 { return a[i + 1] }
            return UserDefaults.standard.string(forKey: key) ?? "system"
        }
        set { UserDefaults.standard.set(newValue, forKey: key) }
    }
    /// 實際用的語言：跟系統時看偏好語言第一個是不是中文（繁簡都算中文介面）
    static var code: String {
        switch setting {
        case "zh": return "zh"
        case "en": return "en"
        default:
            let first = Locale.preferredLanguages.first?.lowercased() ?? "zh"
            return first.hasPrefix("zh") ? "zh" : "en"
        }
    }
    static var isEn: Bool { code == "en" }
}

/// 給人看的字一律寫成 L("中文", "English")
func L(_ zh: String, _ en: String) -> String { Lang.isEn ? en : zh }

// ─── 設定值 ───────────────────────────────────────────────────────────

enum Prefs {
    private static let d = UserDefaults.standard

    /// 複製網址時：card＝跳預覽卡問一聲（預設）／auto＝直接抓（舊的「複製網址就自動下載」）／off＝不動
    static var clipMode: String {
        get {
            if let m = d.string(forKey: "FullyClipMode") { return m }
            return "card"
        }
        set { d.set(newValue, forKey: "FullyClipMode") }
    }
    /// 單張圖抓完，把原圖放進剪貼簿（⌘V 直接貼進 Figma／Keynote）
    static var copyAfter: Bool {
        get { d.object(forKey: "FullyCopyAfter") as? Bool ?? true }
        set { d.set(newValue, forKey: "FullyCopyAfter") }
    }
    /// 同一張不存兩次（比對存放資料夾裡的圖）
    static var dedup: Bool {
        get { d.object(forKey: "FullyDedup") as? Bool ?? true }
        set { d.set(newValue, forKey: "FullyDedup") }
    }
    /// 精靈第一頁的「我了解」（使用規範）
    static var agreed: Bool {
        get { d.bool(forKey: "FullyAgreedTerms") }
        set { d.set(newValue, forKey: "FullyAgreedTerms") }
    }
}

// ─── 叫引擎 ───────────────────────────────────────────────────────────

enum EngineRunner {
    struct Candidate { let exe: String; let args: [String]; let kind: String }

    /// 照優先序：① 包內獨立版 Resources/bin/fully-engine（不吃系統 Python）② /usr/bin/python3＋Resources/grab.py（開發期、Intel 退路）。
    /// 只有「叫不起來」才換下一個；引擎起來後自己失敗＝真錯誤，照實回報，不重跑。
    static var candidates: [Candidate] {
        var list: [Candidate] = []
        if let bin = Bundle.main.path(forResource: "fully-engine", ofType: nil, inDirectory: "bin"),
           FileManager.default.isExecutableFile(atPath: bin) {
            list.append(Candidate(exe: bin, args: [], kind: "bundled"))
        }
        if let py = Bundle.main.path(forResource: "grab", ofType: "py") {
            list.append(Candidate(exe: "/usr/bin/python3", args: [py], kind: "system-python"))
        }
        return list
    }

    /// ~/Library/Application Support/Fully：重複比對索引、追蹤清單等本機資料都住這裡（只在這台 Mac）
    static let dataDir: String = {
        let dir = NSHomeDirectory() + "/Library/Application Support/Fully"
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        return dir
    }()

    static var environment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["FULLY_LANG"] = Lang.code
        env["FULLY_DATA_DIR"] = dataDir
        env["FULLY_DEDUP"] = Prefs.dedup ? "1" : "0"
        return env
    }

    /// 起一支引擎。事件照順序在主執行緒回呼；結束時先把最後一截輸出讀完、送完，才回呼 onExit
    /// （在 terminationHandler 直接拔掉讀取器的話，最後一行 done 偶爾會被吃掉，看起來像下載中斷）
    @discardableResult
    static func start(_ tail: [String], onEvent: @escaping ([String: Any]) -> Void,
                      onExit: @escaping (Int32) -> Void) -> (process: Process, kind: String)? {
        for c in candidates {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: c.exe)
            p.arguments = c.args + tail
            p.environment = environment
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            let lock = NSLock()
            var buffer = Data()

            func drain(final: Bool) -> [[String: Any]] {
                lock.lock(); defer { lock.unlock() }
                var out: [[String: Any]] = []
                while let nl = buffer.firstIndex(of: 0x0A) {
                    let line = Data(buffer[buffer.startIndex..<nl])
                    buffer.removeSubrange(buffer.startIndex...nl)
                    if let o = try? JSONSerialization.jsonObject(with: line) as? [String: Any] { out.append(o) }
                }
                if final, !buffer.isEmpty {
                    if let o = try? JSONSerialization.jsonObject(with: buffer) as? [String: Any] { out.append(o) }
                    buffer.removeAll()
                }
                return out
            }

            pipe.fileHandleForReading.readabilityHandler = { fh in
                let chunk = fh.availableData
                guard !chunk.isEmpty else { return }
                lock.lock(); buffer.append(chunk); lock.unlock()
                let evs = drain(final: false)
                if !evs.isEmpty { DispatchQueue.main.async { evs.forEach(onEvent) } }
            }
            p.terminationHandler = { proc in
                pipe.fileHandleForReading.readabilityHandler = nil
                let rest = pipe.fileHandleForReading.readDataToEndOfFile()
                lock.lock(); buffer.append(rest); lock.unlock()
                let evs = drain(final: true)
                DispatchQueue.main.async {
                    evs.forEach(onEvent)
                    onExit(proc.terminationStatus)
                }
            }
            do {
                try p.run()
                return (p, c.kind)
            } catch {
                pipe.fileHandleForReading.readabilityHandler = nil   // 這個候選沒起來（例如 Intel 機器跑 arm64 獨立版），換下一個
                continue
            }
        }
        return nil
    }
}
