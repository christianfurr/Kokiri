import Foundation

/// Availability is separate from the saved connection so a missing drive does not
/// turn a returning player into a new user or discard their selected app.
public enum InstallationAvailability: Equatable, Sendable {
    case unconfigured
    case ready
    case unavailable

    public static func determine(_ configured: GameInstallation?) -> Self {
        guard let configured else { return .unconfigured }
        return (try? GameInstallation.inspect(configured.app)) == nil ? .unavailable : .ready
    }
}

public enum InstallationConnection {
    /// Commits a verified candidate before returning updated in-memory preferences.
    /// Failure leaves the caller's value and existing preference file unchanged.
    public static func connect(_ app: URL, preferences: LauncherPreferences,
                               savingTo file: URL) throws -> LauncherPreferences {
        let installation = try GameInstallation.inspect(app)
        var updated = preferences
        updated.installation = installation
        try updated.save(to: file)
        return updated
    }
}
