// ShareViewController.swift — 分享選單「Fully」
//
// Safari、Chrome、Finder 的「分享」選單裡多一個 Fully：按下去就把這一頁（或這個網址）交給 Fully，
// 不用複製、不用切 app。這支擴充自己不下載任何東西：只把網址轉成 fully://grab?url=… 交給主程式，
// 主程式照常排隊、右上角的預覽卡顯示進度。App Extension 規定要在沙盒裡跑，所以它只做這一件事。
import AppKit

@objc(ShareViewController)
final class ShareViewController: NSViewController {
    override var nibName: NSNib.Name? { nil }

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 1, height: 1))
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        let items = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
        let providers = items.flatMap { $0.attachments ?? [] }
        guard let p = providers.first(where: { $0.hasItemConformingToTypeIdentifier("public.url") }) else { finish(); return }
        p.loadItem(forTypeIdentifier: "public.url", options: nil) { item, _ in
            var url: URL?
            if let u = item as? URL { url = u }
            else if let d = item as? Data { url = URL(dataRepresentation: d, relativeTo: nil) }
            else if let s = item as? String { url = URL(string: s) }
            DispatchQueue.main.async {
                if let u = url, u.scheme == "http" || u.scheme == "https" {
                    var c = URLComponents()
                    c.scheme = "fully"; c.host = "grab"
                    c.queryItems = [URLQueryItem(name: "url", value: u.absoluteString)]
                    if let target = c.url { NSWorkspace.shared.open(target) }
                }
                self.finish()
            }
        }
    }

    private func finish() { extensionContext?.completeRequest(returningItems: nil, completionHandler: nil) }
}
