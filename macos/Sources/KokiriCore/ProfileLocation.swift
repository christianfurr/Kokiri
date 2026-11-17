import Foundation

public enum ProfileLocation {
    /// A requested private profile never falls back to the ordinary player's data.
    /// Revalidate the marker because the binding can become unavailable after load.
    public static func resolve(previewRequested: Bool, binding: HumanPreviewBinding?) -> URL? {
        guard previewRequested else { return KokiriPaths.profile }
        guard let binding, (try? binding.verifyMarker()) != nil else { return nil }
        return binding.rootURL.appendingPathComponent("profile")
    }
}
