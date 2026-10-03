import Foundation
import CoreGraphics
import Darwin
let handle = dlopen("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight", RTLD_LAZY)!
typealias Connection = @convention(c) () -> Int32
typealias CopySpaces = @convention(c) (Int32) -> Unmanaged<CFArray>?
guard let c = dlsym(handle, "CGSMainConnectionID"), let s = dlsym(handle, "CGSCopyManagedDisplaySpaces") else { exit(2) }
let connection = unsafeBitCast(c, to: Connection.self)
let copySpaces = unsafeBitCast(s, to: CopySpaces.self)
guard let raw = copySpaces(connection())?.takeRetainedValue() else { exit(3) }
let displays = (raw as NSArray).compactMap { item -> [String: Any]? in
    guard let d = item as? [String: Any], let current = d["Current Space"] as? [String: Any], let id = current["ManagedSpaceID"] ?? current["id64"] else { return nil }
    return ["display": d["Display Identifier"] ?? "unknown", "space": id]
}
guard !displays.isEmpty else { exit(4) }
let data = try JSONSerialization.data(withJSONObject: displays, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
