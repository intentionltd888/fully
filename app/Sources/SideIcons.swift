// SideIcons.swift — Dock 圖示與選單列圖示的下載狀態
//
// 面板收起來的時候，使用者只看得到 Dock 與選單列，所以進度也畫在這兩個地方：
//   Dock 圖示：箭頭下方的留白放一條進度（深色軌道＋暖白填色＝圖示同一組顏色，進度的頭是品牌藍點），
//             右上角一顆深色膠囊寫還有幾個在排，存好了右下角亮一個勾 4 秒。
//   選單列：箭頭外面一圈進度環（template 圖，跟著系統深淺色），讀取中是一小段弧在轉，存好了換成勾 3 秒。
// 幾何跟 app 圖示同一組（fullyArrow）；顏色：深灰 #2B2D33、暖白 #FAF7F2、藍 #003CFF。
import AppKit

private let INK = NSColor(red: 0x2B / 255, green: 0x2D / 255, blue: 0x33 / 255, alpha: 1)
private let WARM = NSColor(red: 0xFA / 255, green: 0xF7 / 255, blue: 0xF2 / 255, alpha: 1)
private let BLUE = NSColor(red: 0x00 / 255, green: 0x3C / 255, blue: 0xFF / 255, alpha: 1)

// ─── Dock 圖示 ───────────────────────────────────────────────────────

final class DockTileView: NSView {
    var progress: Double?          // nil＝沒在下載；<0＝讀取中（不知道總量）；0…1
    var badge = 0                  // 還有幾個在排（含正在抓的那個），>1 才畫
    var done = false
    var phase: CGFloat = 0         // 讀取中那一小段的位置

    override func draw(_ dirtyRect: NSRect) {
        let b = bounds
        NSApp.applicationIconImage?.draw(in: b)
        let s = min(b.width, b.height)

        if let p = progress {
            // 箭頭下方的留白：方磚本身佔畫布 10%–92%（macOS 圖示格線四周留透明邊），箭頭底緣在 26%——
            // 條子放在 13%–20.5%，左右內縮到超橢圓的直邊內（貼在最底緣的話兩端會超出方磚）
            let track = NSRect(x: b.minX + s * 0.22, y: b.minY + s * 0.13, width: s * 0.56, height: s * 0.075)
            let r = track.height / 2
            INK.withAlphaComponent(0.72).setFill()
            NSBezierPath(roundedRect: track, xRadius: r, yRadius: r).fill()
            let inner = track.insetBy(dx: s * 0.012, dy: s * 0.012)
            let ir = inner.height / 2
            if p < 0 {
                // 讀取中：一段 28% 寬的暖白來回滑
                let w = inner.width * 0.28
                let x = inner.minX + (inner.width - w) * (0.5 - 0.5 * cos(phase))
                WARM.setFill()
                NSBezierPath(roundedRect: NSRect(x: x, y: inner.minY, width: w, height: inner.height), xRadius: ir, yRadius: ir).fill()
            } else {
                let w = max(inner.height, inner.width * CGFloat(min(1, p)))
                WARM.setFill()
                NSBezierPath(roundedRect: NSRect(x: inner.minX, y: inner.minY, width: w, height: inner.height), xRadius: ir, yRadius: ir).fill()
                // 進度的頭：家族共用的藍點（介面裡「正在做」只有這個顏色），大圖示才畫得出來
                if s >= 96, p > 0.02, p < 0.995 {
                    let d = inner.height * 0.62
                    BLUE.setFill()
                    NSBezierPath(ovalIn: NSRect(x: inner.minX + w - inner.height / 2 - d / 2, y: inner.midY - d / 2, width: d, height: d)).fill()
                }
            }
        }

        if badge > 1 {
            let txt = badge > 99 ? "99+" : "\(badge)"
            let font = NSFont.systemFont(ofSize: s * 0.17, weight: .semibold)
            let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: WARM]
            let ts = (txt as NSString).size(withAttributes: attrs)
            let h = s * 0.27, w = max(h, ts.width + s * 0.13)
            let pill = NSRect(x: b.maxX - w - s * 0.02, y: b.maxY - h - s * 0.02, width: w, height: h)
            WARM.setFill()
            NSBezierPath(roundedRect: pill.insetBy(dx: -s * 0.018, dy: -s * 0.018), xRadius: h / 2 + s * 0.018, yRadius: h / 2 + s * 0.018).fill()
            INK.setFill()
            NSBezierPath(roundedRect: pill, xRadius: h / 2, yRadius: h / 2).fill()
            (txt as NSString).draw(at: NSPoint(x: pill.midX - ts.width / 2, y: pill.midY - ts.height / 2), withAttributes: attrs)
        }

        if done {
            let d = s * 0.30
            let c = NSRect(x: b.maxX - d - s * 0.03, y: b.minY + s * 0.03, width: d, height: d)
            INK.setFill()
            NSBezierPath(ovalIn: c.insetBy(dx: -s * 0.018, dy: -s * 0.018)).fill()
            WARM.setFill()
            NSBezierPath(ovalIn: c).fill()
            let m = NSBezierPath()
            m.move(to: NSPoint(x: c.minX + d * 0.28, y: c.minY + d * 0.52))
            m.line(to: NSPoint(x: c.minX + d * 0.44, y: c.minY + d * 0.34))
            m.line(to: NSPoint(x: c.minX + d * 0.73, y: c.minY + d * 0.66))
            m.lineWidth = d * 0.11
            m.lineCapStyle = .round
            m.lineJoinStyle = .round
            INK.setStroke()
            m.stroke()
        }
    }
}

final class SideIcons {
    static let shared = SideIcons()

    private let dockView = DockTileView()
    private weak var statusButton: NSStatusBarButton?
    private var timer: Timer?
    private var doneUntil: Date?
    private var lastDraw = Date.distantPast
    private(set) var progress: Double?
    private var badge = 0

    func attach(status: NSStatusBarButton?) {
        statusButton = status
        dockView.frame = NSRect(x: 0, y: 0, width: 128, height: 128)
        NSApp.dockTile.contentView = dockView
        NSApp.dockTile.display()
    }

    /// p：nil＝閒著／<0＝讀取中／0…1；queued：還有幾個（含正在抓的）
    func set(progress p: Double?, queued: Int) {
        progress = p
        badge = queued
        if p != nil { doneUntil = nil }
        let animating = (p ?? 0) < 0
        if animating, timer == nil {
            timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 12, repeats: true) { [weak self] _ in self?.tick() }
        } else if !animating, doneUntil == nil {
            timer?.invalidate(); timer = nil
        }
        redraw(force: p == nil)
    }

    /// 存好了：Dock 右下角與選單列亮一個勾（Dock 4 秒、選單列 3 秒），之後回到平常的樣子
    func flashDone() {
        progress = nil
        doneUntil = Date().addingTimeInterval(4)
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in self?.tick() }
        redraw(force: true)
    }

    private func tick() {
        dockView.phase += 0.35
        if let u = doneUntil, Date() > u {
            doneUntil = nil
            timer?.invalidate(); timer = nil
        }
        redraw(force: true)
    }

    private func redraw(force: Bool) {
        // Dock 重畫不便宜：一般進度最多每 0.2 秒一次，狀態切換（開始／結束／勾）立刻畫
        if !force, Date().timeIntervalSince(lastDraw) < 0.2 { return }
        lastDraw = Date()
        let isDone = doneUntil.map { Date() < $0 } ?? false
        dockView.progress = progress
        dockView.badge = badge
        dockView.done = isDone && progress == nil
        NSApp.dockTile.display()
        let showCheck = isDone && progress == nil && (doneUntil.map { $0.timeIntervalSinceNow > 1 } ?? false)
        statusButton?.image = StatusIcon.make(progress: progress, phase: dockView.phase, done: showCheck)
    }
}

// ─── 選單列圖示 ──────────────────────────────────────────────────────

enum StatusIcon {
    /// 18pt template 圖。平常＝品牌標記；下載中＝標記縮小＋外圈進度環；存好了＝勾
    static func make(progress: Double? = nil, phase: CGFloat = 0, done: Bool = false) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let img = NSImage(size: size, flipped: false) { _ in
            NSColor.black.setFill()
            NSColor.black.setStroke()
            if done {
                let m = NSBezierPath()
                m.move(to: NSPoint(x: 4, y: 9.2))
                m.line(to: NSPoint(x: 7.6, y: 5.6))
                m.line(to: NSPoint(x: 14.2, y: 12.4))
                m.lineWidth = 2.2
                m.lineCapStyle = .round
                m.lineJoinStyle = .round
                m.stroke()
                return true
            }
            guard let p = progress else {
                fullyArrow(x0: 3, y0: 3, S: 12).fill()     // 12pt 標記放在 18pt 格子裡
                return true
            }
            fullyArrow(x0: 5.5, y0: 5.5, S: 7).fill()
            let c = NSPoint(x: 9, y: 9), r: CGFloat = 7.6
            let track = NSBezierPath()
            track.appendArc(withCenter: c, radius: r, startAngle: 0, endAngle: 360)
            track.lineWidth = 1.6
            NSColor.black.withAlphaComponent(0.28).setStroke()
            track.stroke()
            let arc = NSBezierPath()
            if p < 0 {
                let start = 90 - phase * 57.3
                arc.appendArc(withCenter: c, radius: r, startAngle: start, endAngle: start - 80, clockwise: true)
            } else {
                arc.appendArc(withCenter: c, radius: r, startAngle: 90, endAngle: 90 - 360 * CGFloat(max(0.03, min(1, p))), clockwise: true)
            }
            arc.lineWidth = 1.8
            arc.lineCapStyle = .round
            NSColor.black.setStroke()
            arc.stroke()
            return true
        }
        img.isTemplate = true
        return img
    }
}
