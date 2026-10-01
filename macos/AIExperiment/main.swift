import AppKit
import WebKit
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate, WKUIDelegate, WKNavigationDelegate, WKDownloadDelegate, WKScriptMessageHandlerWithReply {
    let root = ProcessInfo.processInfo.environment["AI_EXP_DATA_DIR"] ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/AI Experiment").path
    var window: NSWindow?
    var webView: WKWebView?
    var downloads = Set<WKDownload>()
    let origin = "http://127.0.0.1:" + (ProcessInfo.processInfo.environment["AI_EXP_PORT"] ?? "8765")
    let localSession: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.connectionProxyDictionary = ["HTTPEnable": 0, "HTTPSEnable": 0]
        return URLSession(configuration: config)
    }()
    var timer: Timer?
    var opening = false
    var notified = Set<String>()
    let notificationQueue = DispatchQueue(label: "ai-exp.notifications")

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let top = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "打开工作台", action: #selector(openWorkspace), keyEquivalent: "o")
        appMenu.addItem(withTitle: "关闭窗口", action: #selector(closeWorkspace), keyEquivalent: "w")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出实验工作台", action: #selector(quit), keyEquivalent: "q")
        top.submenu = appMenu
        menu.addItem(top)
        let edit = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        edit.submenu = editMenu; menu.addItem(edit)
        NSApp.mainMenu = menu
        UNUserNotificationCenter.current().delegate = self
        openWorkspace()
        timer = Timer.scheduledTimer(withTimeInterval: 8, repeats: true) { [weak self] _ in
            self?.notificationQueue.async { self?.pollNotifications() }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openWorkspace()
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func request(_ path: String, method: String = "GET", body: [String: Any] = [:]) -> Data? {
        guard let url = URL(string: origin + path) else { return nil }
        var req = URLRequest(url: url)
        req.timeoutInterval = 3
        req.httpMethod = method
        if let token = try? String(contentsOfFile: root + "/desktop-token", encoding: .utf8) {
            req.setValue(token.trimmingCharacters(in: .whitespacesAndNewlines), forHTTPHeaderField: "X-Desktop-Token")
        }
        if method == "POST" {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        let semaphore = DispatchSemaphore(value: 0)
        var result: Data?
        localSession.dataTask(with: req) { data, response, _ in
            if (response as? HTTPURLResponse)?.statusCode == 200 { result = data }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 4)
        return result
    }

    func health() -> Bool {
        guard let data = request("/api/health"), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        guard let identityData = FileManager.default.contents(atPath: root + "/service.json"),
              let identity = try? JSONSerialization.jsonObject(with: identityData) as? [String: Any] else { return false }
        return value["app"] as? String == "ai-exp-app" && value["instance_id"] as? String == identity["instance_id"] as? String && identity["url"] as? String == origin
    }

    @objc func openWorkspace() { open(path: "") }
    @objc func closeWorkspace() { window?.close() }

    func open(path: String) {
        guard Thread.isMainThread else {
            DispatchQueue.main.async { self.open(path: path) }
            return
        }
        guard !opening else { return }
        opening = true
        DispatchQueue.global().async {
            if !self.health() {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: Bundle.main.resourcePath! + "/server/ai-experiment")
                p.arguments = ["service", "run"]
                var env = ProcessInfo.processInfo.environment
                env["AI_EXP_DATA_DIR"] = self.root
                env["AI_EXP_CACHE_ROOT"] = self.root + "/gpu_downloads"
                env["AI_EXP_WEB_ROOT"] = Bundle.main.resourcePath! + "/web"
                env["PATH"] = FileManager.default.homeDirectoryForCurrentUser.path + "/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
                p.environment = env
                p.currentDirectoryURL = URL(fileURLWithPath: self.root)
                try? FileManager.default.createDirectory(atPath: self.root, withIntermediateDirectories: true)
                let log = self.root + "/service.log"
                if !FileManager.default.fileExists(atPath: log) { FileManager.default.createFile(atPath: log, contents: nil) }
                if let file = FileHandle(forWritingAtPath: log) {
                    file.seekToEndOfFile(); p.standardOutput = file; p.standardError = file
                }
                do { try p.run() } catch { self.alert("无法启动本地服务", error.localizedDescription) }
                for _ in 0..<40 {
                    if self.health() { break }
                    Thread.sleep(forTimeInterval: 0.25)
                }
            }
            guard self.health() else {
                self.alert("本地服务尚未就绪", "请查看 " + self.root + "/service.log")
                DispatchQueue.main.async { self.opening = false }
                return
            }
            DispatchQueue.main.async {
                self.showWindow(self.origin + "/" + path)
                self.opening = false
            }
        }
    }

    func showWindow(_ address: String) {
        if window == nil {
            let config = WKWebViewConfiguration()
            config.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "notifications")
            let view = WKWebView(frame: .zero, configuration: config)
            view.uiDelegate = self; view.navigationDelegate = self
            let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1380, height: 920),
                               styleMask: [.titled, .closable, .miniaturizable, .resizable],
                               backing: .buffered, defer: false)
            win.title = "实验工作台"; win.minSize = NSSize(width: 900, height: 650)
            win.contentView = view; win.isReleasedWhenClosed = false
            win.setFrameAutosaveName("Workspace"); win.center()
            window = win; webView = view
        }
        if webView?.url == nil || !address.hasSuffix("/") {
            webView?.load(URLRequest(url: URL(string: address)!, cachePolicy: .reloadIgnoringLocalCacheData))
        }
        window?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        verifyNativeSmoke()
    }

    func verifyNativeSmoke(attempt: Int = 0) {
        guard let path = ProcessInfo.processInfo.environment["AI_EXP_NATIVE_SMOKE_PATH"], let view = webView else { return }
        view.evaluateJavaScript("JSON.stringify({title:document.title,href:location.href,children:document.querySelector('#root')?.childElementCount||0})") { result, error in
            let value = (result as? String).flatMap { $0.data(using: .utf8) }.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let ready = (value?["children"] as? Int ?? 0) > 0 && (value?["href"] as? String ?? "").hasPrefix(self.origin + "/")
            if ready || attempt >= 100 {
                var payload = value ?? [:]
                payload["ok"] = ready; payload["renderer"] = "webkit"
                if !ready { payload["error"] = error?.localizedDescription ?? "Native WebView did not render the application" }
                if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) {
                    try? data.write(to: URL(fileURLWithPath: path), options: .atomic)
                }
                NSApp.terminate(nil)
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.verifyNativeSmoke(attempt: attempt + 1) }
            }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if action.shouldPerformDownload { decisionHandler(.download); return }
        if url.scheme == "blob" || url.absoluteString.hasPrefix(origin + "/") {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
            if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let attachment = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")?.contains("attachment") == true
        decisionHandler(attachment || !response.canShowMIMEType ? .download : .allow)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        downloads.insert(download); download.delegate = self
    }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        downloads.insert(download); download.delegate = self
    }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.begin { result in completionHandler(result == .OK ? panel.url : nil) }
    }
    func downloadDidFinish(_ download: WKDownload) { downloads.remove(download) }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.remove(download)
        if (error as NSError).code != NSURLErrorCancelled { alert("下载失败", error.localizedDescription) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let panel = NSAlert(); panel.messageText = message; panel.runModal(); completionHandler()
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let panel = NSAlert(); panel.messageText = message
        panel.addButton(withTitle: "确认"); panel.addButton(withTitle: "取消")
        completionHandler(panel.runModal() == .alertFirstButtonReturn)
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let panel = NSAlert(); panel.messageText = prompt
        let input = NSTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 26))
        input.stringValue = defaultText ?? ""; panel.accessoryView = input
        panel.addButton(withTitle: "确认"); panel.addButton(withTitle: "取消")
        panel.window.initialFirstResponder = input
        completionHandler(panel.runModal() == .alertFirstButtonReturn ? input.stringValue : nil)
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.begin { response in completionHandler(response == .OK ? panel.urls : nil) }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let source = message.frameInfo.securityOrigin
        guard message.frameInfo.isMainFrame, source.protocol == "http", source.host == "127.0.0.1",
              source.port == URL(string: origin)?.port, message.body as? String == "enable" else {
            replyHandler(nil, "不允许的通知设置请求"); return
        }
        let center = UNUserNotificationCenter.current()
        let openSettings = {
            DispatchQueue.main.async {
                let id = Bundle.main.bundleIdentifier ?? "org.ai-experiment.workbench"
                let url = URL(string: "x-apple.systempreferences:com.apple.preference.notifications?id=" + id)!
                if NSWorkspace.shared.open(url) { replyHandler("settings_opened", nil) }
                else {
                    self.alert("通知设置", "请在系统设置 → 通知 → 实验工作台中开启允许通知。")
                    replyHandler("manual_settings", nil)
                }
            }
        }
        center.getNotificationSettings { settings in
            if settings.authorizationStatus == .notDetermined {
                center.requestAuthorization(options: [.alert, .sound]) { allowed, error in
                    if let error = error { replyHandler(nil, error.localizedDescription) }
                    else if allowed { replyHandler("granted", nil) }
                    else { openSettings() }
                }
            } else { openSettings() }
        }
    }

    func pollNotifications() {
        if let data = request("/api/desktop/picker"),
           let picker = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let id = picker["id"] as? String {
            DispatchQueue.main.async {
                let panel = NSOpenPanel()
                panel.canChooseFiles = false
                panel.canChooseDirectories = true
                panel.allowsMultipleSelection = false
                panel.prompt = "选择实验目录"
                NSApp.activate(ignoringOtherApps: true)
                panel.begin { response in
                    let body: [String: Any] = response == .OK ? ["path": panel.url?.path ?? ""] : [:]
                    self.notificationQueue.async {
                        _ = self.request("/api/desktop/picker/" + id, method: "POST", body: body)
                    }
                }
            }
        }
        guard let data = request("/api/desktop/notifications"),
              let values = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return }
        for item in values {
            guard let id = item["id"] as? String, !notified.contains(id) else { continue }
            notified.insert(id)
            let content = UNMutableNotificationContent()
            content.title = item["title"] as? String ?? "实验状态更新"
            content.body = item["body"] as? String ?? "请查看实验工作台"
            content.sound = .default
            content.userInfo = ["run_id": item["run_id"] as? String ?? ""]
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id, content: content, trigger: nil)) { error in
                if error == nil { _ = self.request("/api/desktop/notifications/" + id + "/delivered", method: "POST") }
                else { self.notificationQueue.async { self.notified.remove(id) } }
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completion: @escaping () -> Void) {
        let run = response.notification.request.content.userInfo["run_id"] as? String ?? ""
        open(path: "?workspace=monitor&run=" + run)
        completion()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completion: @escaping (UNNotificationPresentationOptions) -> Void) {
        completion([.banner, .sound])
    }

    func alert(_ title: String, _ message: String) {
        DispatchQueue.main.async {
            let alert = NSAlert(); alert.messageText = title; alert.informativeText = message
            alert.runModal()
        }
    }

    @objc func quit() {
        timer?.invalidate()
        NSApp.terminate(nil)
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
