// ClipCard.swift — 複製就跳預覽卡
//
// 為什麼：複製網址是最順的入口，但一複製就直接開抓沒得反悔——所以先跳一張卡問一聲。
// 在任何 app 裡複製一個網址，螢幕右上角滑進一張卡（縮圖、名稱、幾張、能拿到多大、抓過沒），
// 點「抓下來」就開抓，卡片原地變成進度環、存好了變「打開看看」；不理它，9 秒後自己退場（滑鼠停在卡上就停）。
// 畫面在 card.html（跟主面板同一套規矩）；這裡管視窗：不搶焦點、浮在所有 app 上面、跟著滑鼠所在的螢幕。
// 同類的做法：grinich/replay（MIT，剪貼簿預覽卡）——Fully 的卡不搶鍵盤，複製完繼續打字不會誤觸。
import AppKit
import WebKit

/// 不在前景的視窗裡，第一下點擊也要算數（不然要點兩下：第一下只是把視窗叫醒）
final class FirstClickWebView: WKWebView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// 滑鼠進出（卡片不是 key window，WKWebView 自己的 hover 不可靠；用 .activeAlways 追蹤區）
final class HoverView: NSView {
    var onHover: ((Bool) -> Void)?
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                                       owner: self, userInfo: nil))
    }
    override func mouseEntered(with event: NSEvent) { onHover?(true) }
    override func mouseExited(with event: NSEvent) { onHover?(false) }
}

final class ClipCard: NSObject, WKScriptMessageHandler {
    static let shared = ClipCard()

    enum Action { case grab, open, panel }
    /// 使用者在卡片上按了什麼（網址、動作）——Controller 接
    var onAction: ((String, Action) -> Void)?

    private var panel: NSPanel?
    private var web: FirstClickWebView!
    private var ready = false
    private var pending: [[String: Any]] = []
    private(set) var url: String?
    private var hideWork: DispatchWorkItem?
    private var hovering = false
    private var hideAfter: TimeInterval = 0
    // 卡片 420×104＋落影的邊：底下留 24 px、左右 16 px，落影（card.html --drop）在視窗邊界淡到看不見；
    // 留太少的話，落影會在視窗邊被切成一條直線（淺色桌布上看得到）
    private let size = NSSize(width: 452, height: 140)

    var isShowing: Bool { panel?.isVisible == true }

    private func build() {
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "card")
        web = FirstClickWebView(frame: NSRect(origin: .zero, size: size), configuration: cfg)
        web.setValue(false, forKey: "drawsBackground")
        web.autoresizingMask = [.width, .height]
        if let u = Bundle.main.url(forResource: "card", withExtension: "html") {
            web.loadFileURL(u, allowingReadAccessTo: u.deletingLastPathComponent())
        }
        let host = HoverView(frame: NSRect(origin: .zero, size: size))
        host.addSubview(web)
        host.onHover = { [weak self] on in self?.hover(on) }

        let p = NSPanel(contentRect: NSRect(origin: .zero, size: size),
                        styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.isFloatingPanel = true
        p.level = .statusBar
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = false                 // 落影交給 CSS（跟圓角同一個形狀）
        p.hidesOnDeactivate = false
        p.becomesKeyOnlyIfNeeded = true
        p.isReleasedWhenClosed = false
        p.contentView = host
        panel = p
    }

    // MARK: 對外

    /// 複製了一個網址：卡片先出（站名＋網址），縮圖與細節等預覽回來再補
    private static let debug = ProcessInfo.processInfo.environment["FULLY_DEBUG"] == "1"
    private func dlog(_ s: @autoclosure () -> String) { if Self.debug { print("[card] " + s()); fflush(stdout) } }

    func show(url: String, label: String, seen: String?) {
        dlog("show \(url) panel=\(panel != nil)")
        if panel == nil { build() }
        self.url = url
        let short = url.replacingOccurrences(of: #"^https?://(www\.)?"#, with: "", options: .regularExpression)
        set(["state": "ask", "btn": "grab", "label": label, "title": short, "meta": L("正在看這是什麼…", "Taking a look…"),
             "chip": seen.map { L("抓過了 \($0)", "Saved \($0)") } ?? "", "thumb": "", "loading": true, "frac": -1,
             "lang": Lang.code])
        present()
        schedule(9)
    }

    /// 預覽回來了（引擎 --probe 的 preview 事件）
    func preview(_ p: [String: Any]) {
        guard isShowing, p["url"] as? String == url else { return }
        var d: [String: Any] = ["loading": false]
        if let n = p["name"] as? String, !n.isEmpty { d["title"] = n }
        if let l = p["label"] as? String, !l.isEmpty { d["label"] = l }
        if let t = p["thumb"] as? String, t.hasPrefix("http") { d["thumb"] = t }
        d["meta"] = Self.metaLine(p)
        if p["not_public"] as? Bool == true {
            d["meta"] = L("這不是公開的內容", "This isn't public")
        }
        set(d)
    }

    /// 開抓了／進度（frac <0＝讀取中）
    func progress(url: String, frac: Double, text: String) {
        guard isShowing, url == self.url else { return }
        cancelHide()
        set(["state": "run", "frac": frac, "meta": text, "countdown": 0])
    }

    func done(url: String, title: String, meta: String, thumbData: String?, canOpen: Bool = true) {
        guard isShowing, url == self.url else { return }
        var d: [String: Any] = ["state": "done", "btn": canOpen ? "open" : "panel", "title": title, "meta": meta, "loading": false, "chip": ""]
        if let t = thumbData { d["thumb"] = t }
        set(d)
        schedule(6)
    }

    func failed(url: String, message: String) {
        guard isShowing, url == self.url else { return }
        set(["state": "err", "btn": "panel", "title": L("這個抓不到", "Couldn't grab this"), "meta": message, "loading": false])
        schedule(9)
    }

    func dismiss() {
        dlog("dismiss")
        cancelHide()
        guard let p = panel, p.isVisible else { return }
        web.evaluateJavaScript("window.card.away(true)") { _, _ in }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { p.orderOut(nil) }
        url = nil
    }

    /// 驗收用：把卡片實際渲染的樣子存成 PNG（透明背景，官網可以直接疊）
    func snapshot(to path: String, done: @escaping () -> Void) {
        let cfg = WKSnapshotConfiguration()
        cfg.rect = CGRect(origin: .zero, size: size)
        web.takeSnapshot(with: cfg) { img, _ in
            if let img, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
               let png = rep.representation(using: .png, properties: [:]) {
                try? png.write(to: URL(fileURLWithPath: path))
                print("SNAPSHOT \(path)")
            }
            done()
        }
    }

    /// 預覽事件 → 卡片第三行（幾張／多長／能拿到多大）
    static func metaLine(_ p: [String: Any]) -> String {
        var bits: [String] = []
        let count = p["count"] as? Int ?? 0
        if let v = videoMeta(p, count: count) { return v }     // 影片／清單：長度、幾支、最高畫質
        if count > 1 {
            bits.append(L("\(count) 張", "\(count) images"))
        }
        if let w = p["w"] as? Int, let h = p["h"] as? Int, w > 0, h > 0 {
            bits.append(L("最大 \(w) × \(h)", "up to \(w) × \(h)"))
        }
        if bits.isEmpty { return L("可以抓下來", "Ready to grab") }
        return bits.joined(separator: "・")
    }

    /// 影片線：清單＝幾支、單支＝長度；有畫面尺寸就講最高畫質。不是影片回 nil（走圖片那套）
    private static func videoMeta(_ p: [String: Any], count: Int) -> String? {
        let dur = p["duration"] as? Double ?? (p["duration"] as? Int).map(Double.init)
        let isList = p["list"] as? Bool == true
        guard isList || (dur ?? 0) > 0 || p["fps"] != nil else { return nil }
        var bits: [String] = []
        if isList, count > 0 {
            bits.append(L("\(count) 支", "\(count) videos"))
        } else if let d = dur, d > 0 {
            let s = Int(d)
            bits.append(s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s % 3600 / 60, s % 60) : String(format: "%d:%02d", s / 60, s % 60))
        }
        if let w = p["w"] as? Int, let h = p["h"] as? Int, w > 0, h > 0 {
            let fps = p["fps"] as? Int ?? 0
            bits.append(L("最高 ", "up to ") + "\(min(w, h))p" + (fps > 30 ? "\(fps)" : "") + ((p["hdr"] as? Bool == true) ? " HDR" : ""))
        }
        return bits.isEmpty ? nil : bits.joined(separator: "・")
    }

    // MARK: 內部

    private func present() {
        guard let p = panel else { return }
        let mouse = NSEvent.mouseLocation
        let scr = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) } ?? NSScreen.main
        guard let v = scr?.visibleFrame else { return }
        let frame = NSRect(x: v.maxX - size.width + 4, y: v.maxY - size.height + 6, width: size.width, height: size.height)   // 卡片頂＝選單列下 6 px、右邊離螢幕 12 px
        p.setFrame(frame, display: false)
        dlog("present frame=\(frame) visible=\(p.isVisible)")
        if !p.isVisible {
            web.evaluateJavaScript("window.card && window.card.away(true)") { _, _ in }
            p.orderFrontRegardless()
            dlog("ordered front: visible=\(p.isVisible) number=\(p.windowNumber) onActiveSpace=\(p.isOnActiveSpace) screen=\(p.screen?.frame ?? .zero) appHidden=\(NSApp.isHidden) appActive=\(NSApp.isActive) policy=\(NSApp.activationPolicy().rawValue) occl=\(p.occlusionState.rawValue) level=\(p.level.rawValue)")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.03) {
                self.web.evaluateJavaScript("window.card && window.card.away(false)") { _, _ in }
            }
        } else {
            p.orderFrontRegardless()
        }
    }

    private func set(_ d: [String: Any]) {
        guard ready else { pending.append(d); return }
        guard let data = try? JSONSerialization.data(withJSONObject: d), let json = String(data: data, encoding: .utf8) else { return }
        if Self.debug {             // 縮圖的 base64 很長：紀錄裡只留長度
            var dd = d
            if let t = dd["thumb"] as? String, t.count > 80 { dd["thumb"] = "data(\(t.count))" }
            if let j = try? JSONSerialization.data(withJSONObject: dd, options: .sortedKeys) { dlog("set " + (String(data: j, encoding: .utf8) ?? "")) }
        }
        web.evaluateJavaScript("window.card.set(\(json))") { _, _ in }
    }

    private func schedule(_ seconds: TimeInterval) {
        cancelHide()
        hideAfter = seconds
        set(["countdown": hovering ? 0 : seconds])
        guard !hovering else { return }
        let w = DispatchWorkItem { [weak self] in self?.dismiss() }
        hideWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: w)
    }

    private func cancelHide() { hideWork?.cancel(); hideWork = nil }

    private func hover(_ on: Bool) {
        hovering = on
        web.evaluateJavaScript("window.card && window.card.hover(\(on))") { _, _ in }
        if on { cancelHide() }
        else if hideAfter > 0, isShowing { schedule(max(4, hideAfter * 0.6)) }    // 離開後給一段短一點的時間再退場
    }

    func userContentController(_ c: WKUserContentController, didReceive msg: WKScriptMessage) {
        guard let body = msg.body as? [String: Any], let action = body["action"] as? String else { return }
        switch action {
        case "ready":
            ready = true
            pending.forEach(set)
            pending.removeAll()
        case "close":
            dismiss()
        case "grab":
            if let u = url { onAction?(u, .grab) }
        case "open":
            if let u = url { onAction?(u, .open) }
            dismiss()
        case "panel":
            if let u = url { onAction?(u, .panel) }
            dismiss()
        default: break
        }
    }
}
