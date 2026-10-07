import AppKit
let directory = URL(fileURLWithPath: CommandLine.arguments[1])
let iconset = directory.appendingPathComponent("AppIcon.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for (points, scale) in [(16,1),(16,2),(32,1),(32,2),(128,1),(128,2),(256,1),(256,2),(512,1),(512,2)] {
    let size = points * scale
    let image = NSImage(size: NSSize(width: size,height: size))
    image.lockFocus()
    let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("assets/aiexp-logo.jpg")
    guard let logo = NSImage(contentsOf: source) else { fatalError("Missing application logo") }
    logo.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
    image.unlockFocus()
    let bitmap=NSBitmapImageRep(data:image.tiffRepresentation!)!
    let suffix=scale==2 ? "@2x" : ""
    try bitmap.representation(using:.png,properties:[:])!.write(to:iconset.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
}
let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/bin/iconutil")
p.arguments=["-c","icns",iconset.path,"-o",directory.appendingPathComponent("AppIcon.icns").path]
try p.run();p.waitUntilExit()
if p.terminationStatus != 0 { exit(p.terminationStatus) }
