// Thumbs.swift — 存下來的檔的縮圖
//
// 三個地方要看到「抓到的是什麼」：完成畫面的網址卡、預覽卡的「存好了」、系統通知。
// 介面是 WKWebView，讀不到使用者資料夾裡的檔（只開了 Resources 的讀取權）——所以縮圖在這裡用 Quick Look 做好，
// 轉成 data URL 送過去；各種圖片格式與 SVG 都走同一條（Quick Look 自己認得）。
import AppKit
import QuickLookThumbnailing

enum Thumbs {
    private static func cgImage(for path: String, side: CGFloat, done: @escaping (CGImage?) -> Void) {
        let req = QLThumbnailGenerator.Request(fileAt: URL(fileURLWithPath: path), size: CGSize(width: side, height: side),
                                               scale: 2, representationTypes: .thumbnail)
        QLThumbnailGenerator.shared.generateBestRepresentation(for: req) { rep, _ in
            done(rep?.cgImage)
        }
    }

    private static func jpeg(_ cg: CGImage, quality: CGFloat = 0.82) -> Data? {
        NSBitmapImageRep(cgImage: cg).representation(using: .jpeg, properties: [.compressionFactor: quality])
    }

    /// 介面用：data:image/jpeg;base64,…（主執行緒回呼；做不出來回 nil）
    static func dataURL(for path: String, side: CGFloat = 160, done: @escaping (String?) -> Void) {
        guard FileManager.default.fileExists(atPath: path) else { done(nil); return }
        cgImage(for: path, side: side) { cg in
            let s = cg.flatMap { jpeg($0) }.map { "data:image/jpeg;base64," + $0.base64EncodedString() }
            DispatchQueue.main.async { done(s) }
        }
    }

    /// 通知用：另存一份 JPEG 到暫存夾。通知中心會把附件檔「搬走」，所以絕不能直接給使用者的原檔。
    static func tempFile(for path: String, side: CGFloat = 400, done: @escaping (URL?) -> Void) {
        guard FileManager.default.fileExists(atPath: path) else { done(nil); return }
        cgImage(for: path, side: side) { cg in
            var out: URL?
            if let cg, let data = jpeg(cg) {
                let dir = FileManager.default.temporaryDirectory.appendingPathComponent("fully-notify", isDirectory: true)
                try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let u = dir.appendingPathComponent(UUID().uuidString + ".jpg")
                if (try? data.write(to: u)) != nil { out = u }
            }
            DispatchQueue.main.async { done(out) }
        }
    }
}
