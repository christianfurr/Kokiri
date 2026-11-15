import Combine
import Foundation

/// The protocol adapter owns validation, compatibility, signing and the durable queue.
/// The shell never sends source TSV, logs, game files, or an unvalidated envelope.
@MainActor public final class CatalogFacade: ObservableObject {
    @Published public private(set) var consent: Bool?
    @Published public private(set) var status = "The shared catalog is not configured in this build."
    @Published public private(set) var configured = false
    @Published public private(set) var queued: Int?
    @Published public private(set) var reviewedRecords: Int?
    private var client: CatalogClient?
    private var retryTimer: Timer?
    @Published public private(set) var ready = false
    @Published public private(set) var choicePending = false
    @Published public private(set) var downloadStatus = "Catalog downloads are not configured in this build."
    @Published public private(set) var verifiedIndex: URL?
    @Published public private(set) var downloadPending = false
    private var selectedRuntime: URL?
    private var runtimeGeneration: UInt64 = 0

    public convenience init() {
        let endpoint = (Bundle.main.object(forInfoDictionaryKey: "KokiriCatalogOrigin") as? String).flatMap(URL.init(string:))
        let encodedKeys = Bundle.main.object(forInfoDictionaryKey: "KokiriCatalogPublicKeys") as? [String: String] ?? [:]
        var keys: [String: Data] = [:]
        for (id, value) in encodedKeys {
            guard let data = Data(base64Encoded: value), data.count == 32 else {
                self.init(configurationError: "The catalog verification keys are invalid. Network access is disabled."); return
            }
            keys[id] = data
        }
        self.init(store: KokiriPaths.support.appendingPathComponent("Catalog"), endpoint: endpoint, trustedKeys: keys)
    }
    private init(configurationError: String) { status = configurationError }
    public init(store: URL, endpoint: URL?, trustedKeys: [String: Data]) {
        do { client = try CatalogClient(store: store, endpoint: endpoint, trustedKeys: trustedKeys) }
        catch { status = error.localizedDescription; return }
        // Read durable consent. Never replay a second preference into the queue.
        Task { await reload() }
        retryTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.flush() }
        }
    }
    public func reload() async {
        await updateStatus()
        ready = client != nil
        refreshSelectedRuntime()
    }
    public func choose(_ choice: Bool?) async {
        guard ready, !choicePending, let client else { return }
        choicePending = true
        // An opt-out stops shell-side processing while its durable write completes.
        if choice != true { consent = choice }
        defer { choicePending = false }
        do {
            try await client.setConsent(choice)
            await updateStatus()
            if choice == true { await flush() }
        } catch {
            await updateStatus()
            status = "The sharing choice could not be saved. Requests are paused for this session. " + error.localizedDescription
        }
    }
    /// Only the reviewed runtime metadata adapter may call this; no raw file is queued by the UI.
    public func enqueueValidatedEnvelope(_ data: Data) {
        guard let client, consent == true else { return }
        Task {
            do { try await client.enqueueValidatedEnvelope(data); await updateStatus(); await flush() }
            catch { status = error.localizedDescription }
        }
    }
    public func deferSharing(_ reason: String) { status = reason }
    public func ingestOwnedSession(file: URL, checkpoint: RuntimeMetadataCheckpoint, context: Data, session: URL) {
        guard consent == true, let client else { return }
        Task {
            do {
                let delta = try RuntimeMetadataDelta.appended(file, since: checkpoint)
                guard consent == true else { return }
                if !delta.completeRows.isEmpty {
                    let file = session.appendingPathComponent("catalog-delta.tsv")
                    try delta.completeRows.write(to: file, options: .atomic)
                    let result = try await client.ingestRuntimeMetadata(from: file, context: context)
                    await updateStatus()
                    if result.unsupported > 0 || result.malformed > 0 || delta.deferredBytes > 0 || delta.skippedPrefixContinuationBytes > 0 {
                        status = "Queued \(result.queued) new records. Left local: \(result.unsupported) unsupported, \(result.malformed) malformed; \(delta.deferredBytes) partial bytes deferred."
                    }
                    await flush()
                } else if delta.deferredBytes > 0 { status = "Incomplete runtime metadata was left local for a later session." }
            } catch { status = "Catalog sharing deferred: " + error.localizedDescription }
        }
    }
    public func sessionFinished() { refreshSelectedRuntime() }
    public func selectRuntime(_ app: URL?) {
        guard selectedRuntime != app else { return }
        selectedRuntime = app; runtimeGeneration &+= 1; verifiedIndex = nil
        refreshSelectedRuntime()
    }
    private func refreshSelectedRuntime() {
        guard configured, ready else { return }
        guard let app = selectedRuntime else { downloadStatus = "Connect a runtime to check catalog compatibility."; return }
        do {
            let url = app.appendingPathComponent("Contents/Resources/KokiriCatalogContext.json")
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true, (values.fileSize ?? Int.max) <= 65536 else {
                throw KokiriError.message("The selected runtime has no bounded catalog context.")
            }
            let data = try Data(contentsOf: url)
            guard data.count <= 65536 else { throw KokiriError.message("The runtime catalog context exceeds limits.") }
            refresh(context: data)
        } catch { downloadStatus = "Catalog download deferred: " + error.localizedDescription }
    }
    public func refresh(context: Data) {
        guard let client, configured, !downloadPending else { return }
        let fields = ["game_content_sha256", "translator_sha256", "compiler_sha256", "target_sha256", "options_sha256"]
        guard context.count <= 65536,
              let value = try? JSONSerialization.jsonObject(with: context) as? [String: Any],
              fields.allSatisfy({ key in
                  guard let fingerprint = value[key] as? String else { return false }
                  return fingerprint.range(of: "\\A[a-f0-9]{64}\\z", options: .regularExpression) != nil
              }) else {
            verifiedIndex = nil
            downloadStatus = "This runtime is reference-only: compiler, target or other compatibility fingerprints are unknown. No warm list is downloaded."
            return
        }
        let generation = runtimeGeneration
        downloadPending = true; downloadStatus = "Checking the signed catalog for this exact runtime…"
        Task {
            defer {
                downloadPending = false
                if generation != runtimeGeneration { refreshSelectedRuntime() }
            }
            do {
                let index = try await client.refresh(context: context)
                guard generation == runtimeGeneration else { return }
                verifiedIndex = index
                downloadStatus = "Signed catalog metadata verified. Runtime warm-up preparation is not yet connected."
                await updateStatus()
            } catch { if generation == runtimeGeneration { downloadStatus = "Catalog download deferred: " + error.localizedDescription } }
        }
    }
    private func flush() async {
        guard let client, consent == true, configured else { return }
        do { try await client.flushAutomatic(); await updateStatus() }
        catch { await updateStatus() }
    }
    private func updateStatus() async {
        guard let client else { return }
        let value = await client.status()
        consent = value.consent
        configured = value.configured; queued = value.queued; reviewedRecords = value.reviewedRecords
        status = value.lastError ?? (configured ? consent == true ? "Automatic metadata sharing is enabled. New records are reviewed before publication." : "The catalog is available. Sharing stays off until you choose it."
                                  : "The shared catalog is not configured in this build. Nothing is uploaded.")
    }
}
