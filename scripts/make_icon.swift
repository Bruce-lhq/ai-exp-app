import AppKit
let directory = URL(fileURLWithPath: CommandLine.arguments[1])
let iconset = directory.appendingPathComponent("AppIcon.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for (points, scale) in [(16,1),(16,2),(32,1),(32,2),(128,1),(128,2),(256,1),(256,2),(512,1),(512,2)] {
    let size = points * scale
    let image = NSImage(size: NSSize(width: size,height: size))
    image.lockFocus()
    let f = CGFloat(size) / 1024
    NSColor(calibratedRed: 0.12,green: 0.26,blue: 0.56,alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x:48*f,y:48*f,width:928*f,height:928*f),xRadius:200*f,yRadius:200*f).fill()
    let curve = NSBezierPath(); curve.lineWidth=48*f; curve.lineCapStyle = .round
    curve.move(to:NSPoint(x:230*f,y:730*f))
    curve.curve(to:NSPoint(x:790*f,y:300*f),controlPoint1:NSPoint(x:320*f,y:210*f),controlPoint2:NSPoint(x:510*f,y:480*f))
    NSColor.white.setStroke();curve.stroke()
    NSColor(calibratedRed:0.46,green:0.84,blue:0.79,alpha:1).setFill()
    for (x,y) in [(230,730),(470,427),(790,300)] {
        NSBezierPath(ovalIn:NSRect(x:CGFloat(x-45)*f,y:CGFloat(y-45)*f,width:90*f,height:90*f)).fill()
    }
    image.unlockFocus()
    let bitmap=NSBitmapImageRep(data:image.tiffRepresentation!)!
    let suffix=scale==2 ? "@2x" : ""
    try bitmap.representation(using:.png,properties:[:])!.write(to:iconset.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
}
let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/bin/iconutil")
p.arguments=["-c","icns",iconset.path,"-o",directory.appendingPathComponent("AppIcon.icns").path]
try p.run();p.waitUntilExit()
if p.terminationStatus != 0 { exit(p.terminationStatus) }
