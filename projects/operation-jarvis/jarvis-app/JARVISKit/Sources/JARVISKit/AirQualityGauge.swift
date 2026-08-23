import Foundation

/// Shared PM2.5 ring semantics for the iPhone and Watch apps.
/// A full ring means cleaner air: 1 µg/m³ (or lower) is full and the
/// presentation drains linearly to empty at 75 µg/m³.
public enum AirQualityGauge {
    public static func cleanlinessProgress(pm25 value: Int?) -> Double {
        guard let value else { return 0 }
        let pollutedFraction = (Double(value) - 1) / 74
        return 1 - min(max(pollutedFraction, 0), 1)
    }
}
