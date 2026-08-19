import Foundation

/// Time formatting utilities
enum TimeFormatter {
    private static let timeOnly: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()

    private static let dateTime: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM/dd HH:mm"
        return f
    }()

    private static let fullDateTime: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy/MM/dd HH:mm"
        return f
    }()

    /// Format message timestamp for display
    static func format(_ date: Date) -> String {
        let calendar = Calendar.current
        if calendar.isDateInToday(date) {
            return timeOnly.string(from: date)
        } else if calendar.isDate(date, equalTo: Date(), toGranularity: .year) {
            return dateTime.string(from: date)
        } else {
            return fullDateTime.string(from: date)
        }
    }

    /// Should show time separator between two messages
    static func shouldShowTime(previous: Date?, current: Date) -> Bool {
        guard let prev = previous else { return true }
        return current.timeIntervalSince(prev) > 300 // 5 minutes
    }
}
