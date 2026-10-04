// Follow.swift — 追蹤來源，只抓新的
//
// 抓完一整批，完成畫面多一顆「追蹤，之後只抓新的」。之後 Fully 每 6 小時（app 開著時）
// 回去看一次，有新的就抓進同一個資料夾，一則通知講「3 個來源有新東西」。
// 「只抓新的」靠的是：比對資料夾裡的 .fully-seen（抓過的圖的 id）與已經有的檔。
// 清單存在 ~/Library/Application Support/Fully/follows.json（只在這台 Mac）。
import Foundation

struct Follow: Codable, Equatable {
    var id: String
    var url: String
    var name: String
    var kind: String            // 來源種類（引擎 detected 事件的 kind）
    var mode: String            // 開抓時的 mode
    var root: String            // 抓的時候的存放資料夾（引擎會照來源名稱開同一個子資料夾）
    var added: Date
    var lastCheck: Date?
    var lastNew: Int = 0
    var totalNew: Int = 0
    var archive: String?        // 影片清單的下載紀錄檔
    var lastError: String?
}

final class Follows {
    static let shared = Follows()
    static let every: TimeInterval = 6 * 3600

    private(set) var items: [Follow] = []
    private(set) var checking = false
    private let path = EngineRunner.dataDir + "/follows.json"
    private var timer: Timer?
    private var proc: Process?

    var onChange: (() -> Void)?
    /// 一輪檢查完：有新東西的來源與各抓了幾個
    var onNews: (([(Follow, Int)]) -> Void)?
    /// 忙不忙（讓 app 在檢查時不睡著）
    var onBusy: ((Bool) -> Void)?

    init() { load() }

    private func load() {
        guard let d = FileManager.default.contents(atPath: path) else { return }
        let dec = JSONDecoder(); dec.dateDecodingStrategy = .iso8601
        items = (try? dec.decode([Follow].self, from: d)) ?? []
    }

    private func save() {
        let enc = JSONEncoder(); enc.dateEncodingStrategy = .iso8601; enc.outputFormatting = [.prettyPrinted]
        if let d = try? enc.encode(items) {
            let tmp = path + ".tmp"
            if FileManager.default.createFile(atPath: tmp, contents: d) {
                _ = try? FileManager.default.replaceItemAt(URL(fileURLWithPath: path), withItemAt: URL(fileURLWithPath: tmp))
                if !FileManager.default.fileExists(atPath: path) { try? FileManager.default.moveItem(atPath: tmp, toPath: path) }
            }
        }
        onChange?()
    }

    func isFollowing(_ url: String) -> Bool { items.contains { $0.url == url } }

    var dict: [[String: Any]] {
        let f = DateFormatter(); f.dateFormat = "M/d HH:mm"
        return items.map { it in
            var d: [String: Any] = ["id": it.id, "url": it.url, "name": it.name, "kind": it.kind,
                                    "lastNew": it.lastNew, "totalNew": it.totalNew]
            if let c = it.lastCheck { d["lastCheck"] = f.string(from: c) }
            if let e = it.lastError { d["error"] = e }
            return d
        }
    }

    /// 開始追蹤：資料夾裡已經有的就是「看過了」的底，之後只抓新的
    func add(url: String, name: String, kind: String, mode: String, root: String) {
        guard !isFollowing(url) else { return }
        var f = Follow(id: UUID().uuidString, url: url, name: name, kind: kind, mode: mode, root: root,
                       added: Date(), lastCheck: Date())
        // 影片清單先做「看過了」的底（只列清單不下載，幾秒）
        if kind == "video" {
            let dir = EngineRunner.dataDir + "/archives"
            try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
            f.archive = dir + "/\(f.id).txt"
            EngineRunner.start(["--json", "--baseline", "--archive", f.archive!, url, root], onEvent: { _ in }, onExit: { _ in })
        }
        items.insert(f, at: 0)
        save()
    }

    func remove(id: String) {
        items.removeAll { $0.id == id }
        save()
    }

    // MARK: 排程

    func startSchedule() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 30 * 60, repeats: true) { [weak self] _ in self?.checkDue() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 90) { [weak self] in self?.checkDue() }   // 開機先讓出 90 秒
    }

    private func checkDue() {
        let due = items.contains { ($0.lastCheck ?? .distantPast).timeIntervalSinceNow < -Self.every }
        if due { checkAll(onlyDue: true) }
    }

    /// 一個一個檢查（同一時間只跑一支引擎，不跟使用者手上的下載搶網路太多）
    func checkAll(onlyDue: Bool = false) {
        guard !checking else { return }
        let todo = items.filter { !onlyDue || ($0.lastCheck ?? .distantPast).timeIntervalSinceNow < -Self.every }
        guard !todo.isEmpty else { return }
        checking = true
        onBusy?(true)
        onChange?()
        var news: [(Follow, Int)] = []
        func step(_ rest: ArraySlice<Follow>) {
            guard let f = rest.first else {
                checking = false
                onBusy?(false)
                save()
                if !news.isEmpty { onNews?(news) }
                return
            }
            check(f) { added, err in
                if let i = self.items.firstIndex(where: { $0.id == f.id }) {
                    self.items[i].lastCheck = Date()
                    self.items[i].lastNew = added
                    self.items[i].totalNew += added
                    self.items[i].lastError = err
                    if added > 0 { news.append((self.items[i], added)) }
                }
                self.onChange?()
                step(rest.dropFirst())
            }
        }
        step(todo[...])
    }

    private func check(_ f: Follow, done: @escaping (Int, String?) -> Void) {
        let run: ([String]) -> Void = { extra in
            var tail = ["--json", "--sub"] + extra
            if f.mode == "audio" { tail.append("--audio") }
            if let a = f.archive { tail += ["--archive", a] }
            tail += [f.url, f.root]
            var added = 0, err: String?
            let started = EngineRunner.start(tail, onEvent: { ev in
                switch ev["type"] as? String {
                case "done": added = ev["added"] as? Int ?? 0
                case "error": err = ev["message"] as? String
                default: break
                }
            }, onExit: { _ in done(added, err) })
            self.proc = started?.process
            if started == nil { done(0, L("叫不動下載引擎", "Couldn't start the engine")) }
        }
        run([])
    }

    func stop() { proc?.terminate() }
}
