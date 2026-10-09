// AppUpdate.swift — 有沒有新版的 Fully。
//
// app 開著時每天問一次 GitHub 的「最新發行版」（公開的 API，不帶任何資料、不送出任何東西）。
// 比這台的版本新，就交給 main.swift：設定頁「關於 Fully」那列出現「下載新版」，同一版只發一次通知。
// 下載是打開 releases/latest/download/Fully.dmg（瀏覽器下載），裝法跟第一次一樣：雙擊 DMG 裡的 Fully 就會換掉舊的，設定都留著。

import Foundation

enum AppUpdate {
    static let latestAPI = URL(string: "https://api.github.com/repos/intentionltd888/fully/releases/latest")!
    static let download = "https://github.com/intentionltd888/fully/releases/latest/download/Fully.dmg"
    private static let checkedKey = "FullyAppUpdateCheckedAt"
    private static let notifiedKey = "FullyAppUpdateNotified"

    static var current: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0" }

    /// "2.10.1" > "2.9.3"：一段一段比數字，缺的段當 0。
    static func isNewer(_ a: String, than b: String) -> Bool {
        let pa = a.split(separator: ".").map { Int($0) ?? 0 }, pb = b.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(pa.count, pb.count) {
            let x = i < pa.count ? pa[i] : 0, y = i < pb.count ? pb[i] : 0
            if x != y { return x > y }
        }
        return false
    }

    /// 查一次。force＝不管今天查過沒有。有新版回 completion(版本)，沒有或查不到回 nil（主執行緒）。
    static func check(force: Bool = false, completion: @escaping (String?) -> Void) {
        let d = UserDefaults.standard
        if !force, let last = d.object(forKey: checkedKey) as? Date, Date().timeIntervalSince(last) < 20 * 3600 {
            let known = d.string(forKey: "FullyAppUpdateLatest") ?? ""
            completion(isNewer(known, than: current) ? known : nil)
            return
        }
        var req = URLRequest(url: latestAPI, timeoutInterval: 15)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("Fully/\(current)", forHTTPHeaderField: "User-Agent")
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            var found: String? = nil
            if (resp as? HTTPURLResponse)?.statusCode == 200, let data,
               let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let tag = j["tag_name"] as? String, j["draft"] as? Bool != true, j["prerelease"] as? Bool != true {
                let v = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
                d.set(Date(), forKey: checkedKey)
                d.set(v, forKey: "FullyAppUpdateLatest")
                if isNewer(v, than: current) { found = v }
            }
            DispatchQueue.main.async { completion(found) }
        }.resume()
    }

    /// 這一版的通知發過沒有（同一版只發一次）。
    static func shouldNotify(_ v: String) -> Bool {
        guard UserDefaults.standard.string(forKey: notifiedKey) != v else { return false }
        UserDefaults.standard.set(v, forKey: notifiedKey)
        return true
    }
}
