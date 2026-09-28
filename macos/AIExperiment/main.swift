import AppKit
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let root = Bundle.main.object(forInfoDictionaryKey: "AIExperimentRoot") as! String
    let origin = "http://127.0.0.1:8765"
    var timer: Timer?
    var opening = false
    var notified = Set<String>()
    let notificationQueue = DispatchQueue(label: "ai-exp.notifications")

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let top = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "打开工作台", action: #selector(openWorkspace), keyEquivalent: "o")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出实验工作台", action: #selector(quit), keyEquivalent: "q")
        top.submenu = appMenu
        menu.addItem(top)
        NSApp.mainMenu = menu
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
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
        if let token = try? String(contentsOfFile: root + "/.local/desktop-token", encoding: .utf8) {
            req.setValue(token.trimmingCharacters(in: .whitespacesAndNewlines), forHTTPHeaderField: "X-Desktop-Token")
        }
        if method == "POST" {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        let semaphore = DispatchSemaphore(value: 0)
        var result: Data?
        URLSession.shared.dataTask(with: req) { data, response, _ in
            if (response as? HTTPURLResponse)?.statusCode == 200 { result = data }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 4)
        return result
    }

    func health() -> Bool {
        guard let data = request("/api/health"), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return value["app"] as? String == "ai-exp-app"
    }

    @objc func openWorkspace() { open(path: "") }

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
                p.executableURL = URL(fileURLWithPath: self.root + "/.venv/bin/python")
                p.arguments = ["-m", "ai_exp_app.desktop"]
                p.currentDirectoryURL = URL(fileURLWithPath: self.root)
                try? FileManager.default.createDirectory(atPath: self.root + "/.local", withIntermediateDirectories: true)
                let log = self.root + "/.local/service.log"
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
                self.alert("本地服务尚未就绪", "请查看 " + self.root + "/.local/service.log")
                DispatchQueue.main.async { self.opening = false }
                return
            }
            DispatchQueue.main.async {
                self.focusBrowser(self.origin + "/" + path)
                self.opening = false
            }
        }
    }

    func focusBrowser(_ address: String) {
        guard let url = URL(string: address), let browser = NSWorkspace.shared.urlForApplication(toOpen: url),
              let bundle = Bundle(url: browser)?.bundleIdentifier else { return }
        let supported = ["com.apple.Safari", "com.google.Chrome", "com.google.Chrome.beta", "com.microsoft.edgemac", "com.brave.Browser", "company.thebrowser.Browser"]
        guard supported.contains(bundle) else {
            NSWorkspace.shared.open(url)
            return
        }
        let safari = bundle == "com.apple.Safari"
        let selection = safari ? "set current tab of w to t" : "set active tab index of w to ti"
        let script = """
        on run argv
          set targetURL to item 1 of argv
          tell application id "\(bundle)"
            repeat with w in windows
              set ti to 0
              repeat with t in tabs of w
                set ti to ti + 1
                try
                  set u to URL of t
                  if u starts with "http://127.0.0.1:8765/" or u starts with "http://localhost:8765/" then
                    \(selection)
                    set index of w to 1
                    if targetURL does not end with "/" then set URL of t to targetURL
                    activate
                    return
                  end if
                end try
              end repeat
            end repeat
            open location targetURL
            activate
          end tell
        end run
        """
        DispatchQueue.global().async {
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            p.arguments = ["-e", script, address]
            let errorPipe = Pipe(); p.standardError = errorPipe
            do {
                try p.run(); p.waitUntilExit()
                if p.terminationStatus != 0 {
                    let data = errorPipe.fileHandleForReading.readDataToEndOfFile()
                    self.alert("需要允许浏览器自动化", "请在系统设置 → 隐私与安全性 → 自动化中允许实验工作台控制浏览器，以复用已有页面。\n" + (String(data: data, encoding: .utf8) ?? ""))
                }
            } catch { self.alert("无法打开浏览器", error.localizedDescription) }
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
        DispatchQueue.global().async {
            _ = self.request("/api/desktop/shutdown", method: "POST")
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
