import Combine
import Foundation
import KokiriCore
import Sparkle

@MainActor final class UpdateService: ObservableObject {
    @Published private(set) var configured = false
    @Published private(set) var canCheck = false
    @Published private(set) var status = "Signed updates are not configured in this build."
    private var controller: SPUStandardUpdaterController?
    private var observation: AnyCancellable?

    init() {
        guard (try? UpdateConfiguration(feed: Bundle.main.object(forInfoDictionaryKey: "SUFeedURL") as? String,
                                       publicKey: Bundle.main.object(forInfoDictionaryKey: "SUPublicEDKey") as? String)) != nil,
              Bundle.main.object(forInfoDictionaryKey: "SURequireSignedFeed") as? Bool == true,
              Bundle.main.object(forInfoDictionaryKey: "SUVerifyUpdateBeforeExtraction") as? Bool == true,
              Bundle.main.object(forInfoDictionaryKey: "SUSignedFeedFailureExpirationInterval") as? Int == 0 else { return }
        let controller = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: nil, userDriverDelegate: nil)
        do {
            try controller.updater.start()
            self.controller = controller; configured = true
            status = "Signed appcasts and update archives are verified before installation."
            observation = controller.updater.publisher(for: \.canCheckForUpdates).receive(on: RunLoop.main)
                .sink { [weak self] in self?.canCheck = $0 }
        } catch { status = "Updates unavailable: " + error.localizedDescription }
    }
    var automaticChecks: Bool {
        get { controller?.updater.automaticallyChecksForUpdates ?? false }
        set { controller?.updater.automaticallyChecksForUpdates = newValue; objectWillChange.send() }
    }
    var automaticDownloads: Bool {
        get { controller?.updater.automaticallyDownloadsUpdates ?? false }
        set { controller?.updater.automaticallyDownloadsUpdates = newValue; objectWillChange.send() }
    }
    func check() { guard canCheck else { return }; controller?.checkForUpdates(nil) }
}

