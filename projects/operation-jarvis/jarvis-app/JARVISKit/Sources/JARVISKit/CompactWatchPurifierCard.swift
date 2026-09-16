import Foundation

/// Target identity is separate from display text; a missing device never selects its peer.
public struct WatchPurifierRow: Identifiable {
    public let id: String
    public let deviceID: String?
    public let name: String
    public let shortName: String
    public let status: String
    public let pm25: String
    public let uncertain: Bool

    public init(id: String, state: PurifierSubsystem, unavailable: Bool, busy: Bool) {
        self.id = id
        deviceID = id == "legacy-default" ? state.deviceID : id
        name = state.name ?? "Air purifier"
        shortName = name.replacingOccurrences(of: " Air Purifier", with: "", options: .caseInsensitive)
        uncertain = unavailable || state.ok != true || state.stale == true || state.verificationPending == true
        status = busy ? "Working" : state.verificationPending == true ? "Pending" : state.refreshing == true ? "Loading" :
            state.ok != true ? "Offline" : unavailable || state.stale == true ? "Stale" :
            state.isOn == false ? "Off" : state.mode?.capitalized ?? "—"
        pm25 = state.pm25.map(String.init) ?? "—"
    }
}

#if canImport(SwiftUI)
import SwiftUI

/// The former Watch purifier panel occupied 68pt. Keep that exact budget:
/// two 30pt direct-selection rows and 4pt vertical padding, with full controls in a sheet.
public struct CompactWatchPurifierCard: View {
    private let purifier: PurifierSubsystem?
    private let unavailable: Bool
    private let busyDeviceID: String?
    private let accent: Color
    private let surface: Color
    private let select: (String?) -> Void

    public init(purifier: PurifierSubsystem?, unavailable: Bool, busyDeviceID: String?,
                accent: Color, surface: Color, select: @escaping (String?) -> Void) {
        self.purifier = purifier; self.unavailable = unavailable; self.busyDeviceID = busyDeviceID
        self.accent = accent; self.surface = surface; self.select = select
    }

    public var body: some View {
        VStack(spacing: 0) {
            if let devices = purifier?.compactDevices, !devices.isEmpty {
                ForEach(Array(devices.prefix(2)), id: \.id) { item in
                    let row = WatchPurifierRow(id: item.id, state: item.state, unavailable: unavailable,
                                              busy: busyDeviceID != nil && busyDeviceID == item.state.deviceID)
                    Button { select(row.deviceID) } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "wind").font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(accent).frame(width: 10)
                            Text(row.shortName).font(.system(size: 11, weight: .semibold))
                                .frame(maxWidth: .infinity, alignment: .leading).minimumScaleFactor(0.85)
                            Text(row.status.uppercased()).font(.system(size: 8, weight: .semibold))
                                .foregroundStyle(row.uncertain ? Color.secondary : accent)
                                .frame(width: 34).minimumScaleFactor(0.85)
                            HStack(alignment: .firstTextBaseline, spacing: 2) {
                                Text("PM").font(.system(size: 8, weight: .medium))
                                Text(row.pm25).font(.system(size: 10, weight: .semibold, design: .rounded)).monospacedDigit()
                            }.frame(width: 34, alignment: .trailing).minimumScaleFactor(0.8)
                        }
                        .lineLimit(1).frame(height: 30).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(row.name), \(row.status), PM2.5 \(row.pm25) micrograms per cubic meter")
                    .accessibilityHint("Opens this purifier's controls and full-size readings")
                    .accessibilityIdentifier("watch-purifier-row-\(row.id)")
                }
            } else {
                Button { select(nil) } label: {
                    Text("Purifier readings unavailable").font(.caption).frame(maxWidth: .infinity, minHeight: 60)
                }.buttonStyle(.plain)
            }
        }
        .frame(height: 60)
        .overlay {
            if (purifier?.compactDevices.count ?? 0) > 1 {
                Rectangle().fill(Color.primary.opacity(0.08)).frame(height: 0.5).allowsHitTesting(false)
            }
        }
        .padding(.horizontal, 9).padding(.vertical, 4)
        .frame(maxWidth: .infinity)
        .background(surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityElement(children: .contain)
    }
}
#endif
