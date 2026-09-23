// make-icon — 產 Fully 的 1024 App icon（橘磚＋暖白弧線箭頭 ↘）
//
// 直接用 AppKit 畫向量，不經網頁截圖：磚角要透明、箭頭邊要銳利。
//   磚＝滿版 1024、圓角 22.37%；標記高＝磚的 58%
//   ⚠ 一定要滿版不留邊：macOS 26 會自己套系統圓角遮罩，留邊的舊式圖示會被塞進一塊淺灰底板（Dock 上＝灰框裡一顆小磚）。
//   箭頭＝右直條＋下橫條＋四分之一環；筆粗 t＝0.3S、弧外半徑 R＝0.7S、內半徑 r＝0.4S
//
// 用法：swift make-icon.swift <輸出 icon_1024.png>

import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("用法：swift make-icon.swift <out.png>\n".data(using: .utf8)!)
    exit(1)
}
let outPath = args[1]
let N: CGFloat = 1024
// 品牌色：一色磚＋標記。橘磚＋暖白箭頭（冷灰白放在橘上會發灰）
let ink = NSColor(red: 0xFA/255, green: 0xF7/255, blue: 0xF2/255, alpha: 1)          // 暖白 #FAF7F2（箭頭）
let brickTop = NSColor(red: 0xFF/255, green: 0x78/255, blue: 0x2A/255, alpha: 1)     // #FF782A 上緣稍亮（上亮下暗）
let brickBottom = NSColor(red: 0xF4/255, green: 0x65/255, blue: 0x12/255, alpha: 1)  // #F46512；兩色夾著品牌橘 #FF6A13

/// 滿版圓角磚（macOS 26 會再套系統遮罩；macOS 12–15 不套，所以自己畫標準比例 22.37%）
func brick() -> NSBezierPath {
    NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: N, height: N), xRadius: N * 0.2237, yRadius: N * 0.2237)
}

/// 2 號箭頭 ↘（y 向上；左下角 (x0,y0)、邊長 S）。三塊同向（逆時針）放同一條路徑，接縫不會漏白。
func arrow(x0: CGFloat, y0: CGFloat, S: CGFloat) -> NSBezierPath {
    let t = 0.3 * S, R = 0.7 * S, r = 0.4 * S
    let p = NSBezierPath()
    p.appendRect(NSRect(x: x0 + S - t, y: y0, width: t, height: S))          // 右直條
    p.appendRect(NSRect(x: x0, y: y0, width: S, height: t))                  // 下橫條
    let c = NSPoint(x: x0, y: y0 + t)                                        // 環心在左邊、下橫條頂上
    p.move(to: NSPoint(x: x0 + r, y: y0 + t))
    p.line(to: NSPoint(x: x0 + R, y: y0 + t))
    p.appendArc(withCenter: c, radius: R, startAngle: 0, endAngle: 90, clockwise: false)
    p.line(to: NSPoint(x: x0, y: y0 + t + r))
    p.appendArc(withCenter: c, radius: r, startAngle: 90, endAngle: 0, clockwise: true)
    p.close()
    p.windingRule = .nonZero
    return p
}

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(N), pixelsHigh: Int(N), bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

// 磚：橘漸層（上亮下暗）。滿版不畫落影——影由系統加
NSGradient(starting: brickTop, ending: brickBottom)!.draw(in: brick(), angle: -90)
// 一圈極淡的邊：7% 黑＝磚緣略深一點的橘，放在橘色桌布上也分得出輪廓
NSColor.black.withAlphaComponent(0.07).setStroke()
let edge = brick(); edge.lineWidth = 8; edge.stroke()     // 一半落在畫布外，實際看得到約 4px

// 箭頭：高＝磚的 58%，置中
let S: CGFloat = N * 0.58
ink.setFill()
arrow(x0: 512 - S / 2, y0: 512 - S / 2, S: S).fill()

NSGraphicsContext.restoreGraphicsState()
guard let png = rep.representation(using: .png, properties: [:]) else { exit(1) }
do { try png.write(to: URL(fileURLWithPath: outPath)) } catch {
    FileHandle.standardError.write("寫檔失敗：\(error)\n".data(using: .utf8)!); exit(1)
}
print("icon → \(outPath)")
