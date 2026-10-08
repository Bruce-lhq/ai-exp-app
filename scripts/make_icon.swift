import AppKit
let directory = URL(fileURLWithPath: CommandLine.arguments[1])
let iconset = directory.appendingPathComponent("AppIcon.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for (points, scale) in [(16,1),(16,2),(32,1),(32,2),(128,1),(128,2),(256,1),(256,2),(512,1),(512,2)] {
    let size = points * scale
    let image = NSImage(size: NSSize(width: size,height: size))
    image.lockFocus()
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: size, height: size).fill()
    let inset = CGFloat(size) * 0.06
    let bounds = NSRect(x: inset, y: inset, width: CGFloat(size) - inset * 2, height: CGFloat(size) - inset * 2)
    let radius = bounds.width * 0.22
    NSBezierPath(roundedRect: bounds, xRadius: radius, yRadius: radius).addClip()
    let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("assets/aiexp-logo.jpg")
    guard let logo = NSImage(contentsOf: source) else { fatalError("Missing application logo") }
    logo.draw(in: bounds)
    image.unlockFocus()
    let bitmap=NSBitmapImageRep(data:image.tiffRepresentation!)!
    let suffix=scale==2 ? "@2x" : ""
    try bitmap.representation(using:.png,properties:[:])!.write(to:iconset.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
}
let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/bin/iconutil")
p.arguments=["-c","icns",iconset.path,"-o",directory.appendingPathComponent("AppIcon.icns").path]
try p.run();p.waitUntilExit()
if p.terminationStatus != 0 { exit(p.terminationStatus) }
