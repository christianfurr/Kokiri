import Foundation
import CryptoKit
import CoreFoundation

public struct CatalogClientStatus: Sendable {
    public let consent: Bool?
    public let queued: Int
    public let reviewedRecords: Int
    public let configured: Bool
    public let lastError: String?
}
public struct CatalogIngestResult: Sendable {
    public let queued: Int
    public let alreadyKnown: Int
    public let unsupported: Int
    public let malformed: Int
    public let deferred: Int
}

enum CatalogWire {
    static let version = "kokiri-catalog/1"
    static let contextFields = ["game_id", "game_version", "game_content_sha256", "recipe_format", "backend", "shader_chain", "translator_sha256", "compiler_sha256", "target_sha256", "options_sha256"]
    static let fingerprints = ["game_content_sha256", "translator_sha256", "compiler_sha256", "target_sha256", "options_sha256"]
    static func require(_ ok: Bool, _ message: String) throws {
        guard ok else { throw KokiriError.message(message) }
    }
    static func matches(_ value: String, _ pattern: String) -> Bool {
        value.range(of: "\\A(?:" + pattern + ")\\z", options: .regularExpression) != nil
    }
    static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    static func object(_ value: Any?, _ fields: [String]) throws -> [String: Any] {
        guard let d = value as? [String: Any], Set(d.keys) == Set(fields) else {
            throw KokiriError.message("Unexpected catalog fields.")
        }
        return d
    }
    static func integer(_ value: Any?) -> Int? {
        guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(),
              n.doubleValue.isFinite, n.doubleValue.rounded() == n.doubleValue,
              abs(n.doubleValue) <= 9_007_199_254_740_991 else { return nil }
        return n.intValue
    }
    static func canonical(_ value: Any) throws -> Data {
        if let s = value as? String {
            try require(s.unicodeScalars.allSatisfy { (32...126).contains($0.value) || $0.value == 9 }, "Catalog strings must be ASCII.")
            return try JSONSerialization.data(withJSONObject: s, options: [.fragmentsAllowed, .withoutEscapingSlashes])
        }
        if value is NSNull { return Data("null".utf8) }
        if let n = value as? NSNumber {
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return Data((n.boolValue ? "true" : "false").utf8) }
            guard let i = integer(n) else { throw KokiriError.message("Catalog numbers must be safe integers.") }
            return Data(String(i).utf8)
        }
        if let array = value as? [Any] {
            var data = Data("[".utf8)
            for (index, item) in array.enumerated() { if index > 0 { data.append(44) }; data.append(try canonical(item)) }
            data.append(93); return data
        }
        if let d = value as? [String: Any] {
            var data = Data("{".utf8)
            for (index, key) in d.keys.sorted().enumerated() {
                if index > 0 { data.append(44) }; data.append(try canonical(key)); data.append(58); data.append(try canonical(d[key]!))
            }
            data.append(125); return data
        }
        throw KokiriError.message("Invalid catalog JSON.")
    }
    static func parse(_ data: Data, limit: Int) throws -> Any {
        try require(data.count <= limit, "Catalog input exceeds its size limit.")
        return try JSONSerialization.jsonObject(with: data)
    }
    static func context(_ value: Any?) throws -> [String: Any] {
        let c = try object(value, contextFields)
        for key in ["game_id", "game_version", "shader_chain"] {
            try require((c[key] as? String).map { matches($0, "[a-z0-9][a-z0-9._-]{0,63}") } == true, "Invalid catalog context.")
        }
        try require(c["recipe_format"] as? String == "mng-list-v1" && ["metal", "vulkan", "d3d12"].contains(c["backend"] as? String ?? ""), "Unsupported catalog adapter.")
        for key in fingerprints {
            try require(c[key] is NSNull || (c[key] as? String).map { matches($0, "[a-f0-9]{64}") } == true, "Invalid catalog fingerprint.")
        }
        return c
    }
    static func pipeline(_ text: String) -> Bool {
        if matches(text, "[a-f0-9]{1088}") { return true }
        let fields = text.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
        guard fields.count == 3, fields.prefix(2).allSatisfy({ $0.isEmpty || $0 == "-" || matches($0, "[a-f0-9]{64}-[a-f0-9]{12}_b") }),
              matches(fields[2], "(?:[a-f0-9]{2}|z[a-f0-9]{1,3}\\.)*") else { return false }
        let regex = try! NSRegularExpression(pattern: "z([a-f0-9]+)\\.|[a-f0-9]{2}")
        let rest = fields[2] as NSString
        var bytes = 160
        for token in regex.matches(in: fields[2], range: NSRange(location: 0, length: rest.length)) {
            bytes += token.range(at: 1).location == NSNotFound ? 1 : (Int(rest.substring(with: token.range(at: 1)), radix: 16) ?? 545)
            if bytes > 544 { return false }
        }
        return bytes == 544
    }
    static func row(kind: String, text: String) throws {
        try require(text.utf8.count <= 4096 && matches(text, "[\\x20-\\x7e\\t]+"), "Invalid catalog recipe bytes.")
        var f = text.components(separatedBy: "\t")
        try require(f.first == kind, "Catalog recipe kind mismatch.")
        let variant = "[a-f0-9]{64}-[a-f0-9]{12}_b"
        if kind == "V" || kind == "A" {
            try require(f.count == 3 && matches(f[1], kind == "V" ? "[a-f0-9]{64}" : "[a-f0-9]{12}"), "Invalid binding recipe.")
            guard let d = try parse(Data(f[2].utf8), limit: 4096) as? [String: Any], Set(d.keys).isSubset(of: ["attr", "fout", "img", "tex"]) else { throw KokiriError.message("Invalid binding groups.") }
            func type(_ v: Any?) -> Bool { (v as? String).map { matches($0, "[a-zA-Z0-9_*<>,. -]{1,64}") } == true }
            for (group, slots) in d {
                guard let slots = slots as? [String: Any], slots.count <= 64 else { throw KokiriError.message("Invalid binding slots.") }
                for (slot, value) in slots {
                    try require(matches(slot, "[0-9]{1,3}") && (Int(slot) ?? 256) <= 255, "Invalid binding slot.")
                    if group == "img", let image = value as? [String: Any] {
                        try require(Set(image.keys) == Set(["fmt", "type"]) && image.values.allSatisfy { type($0) }, "Invalid image recipe.")
                    } else { try require(type(value), "Invalid binding type.") }
                }
            }
            try require(try canonical(d) == Data(f[2].utf8), "Binding recipe is not canonical."); return
        }
        guard let flags = f.popLast(), ["", "m", "t", "mt", "tm"].contains(flags) else { throw KokiriError.message("Invalid recipe flags.") }
        var valid = false
        switch kind {
        case "S": valid = f.count == 3 && matches(f[1], variant) && ["0", "1", "5"].contains(f[2])
        case "C": valid = f.count == 2 && matches(f[1], variant)
        case "R": valid = f.count == 2 && pipeline(f[1])
        case "M": valid = f.count == 3 && (f[1] == "-" || matches(f[1], variant)) && pipeline(f[2])
        case "T": valid = f.count == 3 && pipeline(f[1]) && matches(f[2], "(?:[0-9]{1,3}:[0-7];){1,8}")
        default: break
        }
        try require(valid, "Unsupported or malformed catalog recipe.")
    }
    static func record(_ value: Any) throws -> [String: Any] {
        let r = try object(value, ["id", "kind", "row"])
        guard let kind = r["kind"] as? String, let text = r["row"] as? String else { throw KokiriError.message("Invalid catalog record.") }
        try row(kind: kind, text: text)
        try require(r["id"] as? String == hash(try canonical(["kind": kind, "row": text])), "Catalog record hash mismatch.")
        return r
    }
    static func envelope(_ value: Any) throws -> [String: Any] {
        let e = try object(value, ["protocol", "context", "records"])
        try require(e["protocol"] as? String == version, "Catalog protocol mismatch.")
        _ = try context(e["context"])
        guard let records = e["records"] as? [Any], (1...64).contains(records.count) else { throw KokiriError.message("Catalog batch exceeds limits.") }
        let validated = try records.map(record)
        try require(Set(validated.compactMap { $0["id"] as? String }).count == validated.count, "Duplicate catalog record.")
        try require(try canonical(e).count <= 65536, "Catalog batch exceeds limits.")
        return e
    }
}

private struct CatalogPending: Codable {
    let contextID: String
    let id: String
    let envelope: Data
}
private struct CatalogState: Codable {
    var consent: Bool?
    var pending: [CatalogPending] = []
    var failures = 0
    var retryAt: Double = 0
    var reviewedRecords = 0
    var revisions: [String: Int] = [:]
    var acknowledged: [String]? = []
}
private final class CatalogNoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

/// Metadata-only client. Own one actor per dedicated local catalog directory.
/// No method touches game saves, bundle contents, shader binaries or game caches.
public actor CatalogClient {
    private let store: URL
    private let endpoint: URL?
    private let trustedKeys: [String: Data]
    private let session: URLSession
    private var state: CatalogState
    private var sessionStopped = false
    private var isFlushing = false
    private var isRefreshing = false
    private var lastError: String?

    public init(store: URL, endpoint: URL?, trustedKeys: [String: Data]) throws {
        try self.init(store: store, endpoint: endpoint, trustedKeys: trustedKeys, sessionConfiguration: .ephemeral)
    }
    // Internal session configuration seam lets CPU-only tests intercept all
    // HTTPS requests without adding a product flag or contacting any endpoint.
    init(store: URL, endpoint: URL?, trustedKeys: [String: Data], sessionConfiguration: URLSessionConfiguration) throws {
        if let endpoint {
            try CatalogWire.require(endpoint.scheme == "https" && endpoint.host != nil && endpoint.user == nil && endpoint.password == nil && endpoint.query == nil && endpoint.fragment == nil && ["", "/"].contains(endpoint.path), "Catalog requires an HTTPS origin.")
        }
        for (id, key) in trustedKeys { try CatalogWire.require(CatalogWire.matches(id, "[a-z0-9][a-z0-9._-]{0,63}") && key.count == 32, "Invalid pinned catalog key.") }
        self.store = store.standardizedFileURL; self.endpoint = endpoint; self.trustedKeys = trustedKeys
        let fm = FileManager.default
        if fm.fileExists(atPath: store.path) {
            try CatalogWire.require(try store.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey]).isSymbolicLink != true, "Catalog store cannot be a symbolic link.")
        }
        let path = store.appendingPathComponent("queue.json")
        if fm.fileExists(atPath: path.path) {
            try CatalogWire.require(try path.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true, "Catalog queue cannot be a symbolic link.")
            let size = try path.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max
            try CatalogWire.require(size <= 24 * 1024 * 1024, "Catalog queue exceeds limits.")
            let loaded = try JSONDecoder().decode(CatalogState.self, from: Data(contentsOf: path))
            try CatalogWire.require(loaded.pending.count <= 4096, "Catalog queue exceeds limits.")
            var ids = Set<String>(); var total = 0
            for p in loaded.pending {
                let e = try CatalogWire.envelope(CatalogWire.parse(p.envelope, limit: 65536))
                let c = try CatalogWire.context(e["context"])
                guard let records = e["records"] as? [[String: Any]], records.count == 1 else { throw KokiriError.message("Invalid persisted catalog queue.") }
                try CatalogWire.require(p.contextID == CatalogWire.hash(try CatalogWire.canonical(c)) && records[0]["id"] as? String == p.id && ids.insert(p.contextID + p.id).inserted, "Invalid persisted catalog identity.")
                total += p.envelope.count
            }
            let acknowledged = loaded.acknowledged ?? []
            try CatalogWire.require(acknowledged.count <= 16384 && acknowledged.allSatisfy { CatalogWire.matches($0, "[a-f0-9]{128}") }, "Invalid acknowledged catalog identities.")
            try CatalogWire.require(total <= 16 * 1024 * 1024 && loaded.failures >= 0 && loaded.failures <= 10 && loaded.retryAt.isFinite && loaded.retryAt >= 0 && loaded.revisions.count <= 256 && (0...100000).contains(loaded.reviewedRecords), "Invalid persisted catalog limits.")
            self.state = loaded
        } else { self.state = CatalogState() }
        let config = sessionConfiguration
        config.httpCookieStorage = nil; config.urlCache = nil; config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30
        self.session = URLSession(configuration: config, delegate: CatalogNoRedirect(), delegateQueue: nil)
    }
    public func status() -> CatalogClientStatus {
        CatalogClientStatus(consent: sessionStopped && state.consent == true ? false : state.consent, queued: state.pending.count,
                            reviewedRecords: state.reviewedRecords, configured: endpoint != nil && !trustedKeys.isEmpty, lastError: lastError)
    }
    /// The native warm-plan verifier uses the same durable anti-rollback floor.
    public func acceptedRevision(contextID: String) -> Int? { state.revisions[contextID] }
    private func persist(_ next: CatalogState) throws {
        let fm = FileManager.default
        if fm.fileExists(atPath: store.path) {
            let values = try store.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
            try CatalogWire.require(values.isSymbolicLink != true && values.isDirectory == true, "Catalog store is not a private directory.")
        }
        try fm.createDirectory(at: store, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let data = try JSONEncoder().encode(next)
        try CatalogWire.require(data.count <= 24 * 1024 * 1024, "Catalog queue exceeds limits.")
        try data.write(to: store.appendingPathComponent("queue.json"), options: .atomic)
        state = next
    }
    public func setConsent(_ enabled: Bool?) throws {
        sessionStopped = true
        var next = state; next.consent = enabled
        do { try persist(next); sessionStopped = enabled != true; lastError = nil }
        catch { lastError = "The sharing choice could not be saved. Requests are paused for this session."; throw error }
    }
    public func enqueueValidatedEnvelope(_ data: Data) throws {
        try CatalogWire.require(state.consent == true && !sessionStopped, "Choose metadata sharing before enqueueing.")
        let e = try CatalogWire.envelope(CatalogWire.parse(data, limit: 65536))
        let c = try CatalogWire.context(e["context"]), cid = CatalogWire.hash(try CatalogWire.canonical(c))
        var next = state; var seen = Set(next.pending.map { $0.contextID + $0.id } + (next.acknowledged ?? []))
        for r in e["records"] as! [[String: Any]] {
            let id = r["id"] as! String
            if seen.insert(cid + id).inserted {
                let one = try CatalogWire.canonical(["protocol": CatalogWire.version, "context": c, "records": [r]])
                next.pending.append(CatalogPending(contextID: cid, id: id, envelope: one))
            }
        }
        try CatalogWire.require(next.pending.count <= 4096 && next.pending.reduce(0, { $0 + $1.envelope.count }) <= 16 * 1024 * 1024, "Catalog queue is full.")
        try persist(next)
    }
    /// Called only for the explicitly owned profile's pso_user.tsv after its
    /// runtime has exited. This is a local adapter, never a raw-file upload.
    @discardableResult
    public func ingestRuntimeMetadata(from file: URL, context data: Data) throws -> CatalogIngestResult {
        try CatalogWire.require(state.consent == true && !sessionStopped, "Choose metadata sharing before processing runtime records.")
        let context = try CatalogWire.context(CatalogWire.parse(data, limit: 2048))
        let cid = CatalogWire.hash(try CatalogWire.canonical(context))
        let values = try file.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey, .fileSizeKey])
        try CatalogWire.require(values.isSymbolicLink != true && values.isRegularFile == true && (values.fileSize ?? Int.max) <= 16 * 1024 * 1024, "Runtime metadata file exceeds safe limits.")
        let raw = try Data(contentsOf: file)
        guard raw.count <= 16 * 1024 * 1024, let text = String(data: raw, encoding: .utf8) else { throw KokiriError.message("Runtime metadata is not bounded UTF-8.") }
        var next = state
        var seen = Set(next.pending.map { $0.contextID + $0.id } + (next.acknowledged ?? []))
        var bytes = next.pending.reduce(0) { $0 + $1.envelope.count }
        var queued = 0, known = 0, unsupported = 0, malformed = 0, deferred = 0, lines = 0
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: true) {
            lines += 1
            try CatalogWire.require(lines <= 100000, "Runtime metadata has too many records.")
            var row = String(rawLine)
            if row.hasSuffix("\r") { row.removeLast() }
            if row.hasPrefix("#") { continue }
            let fields = row.components(separatedBy: "\t")
            guard let kind = fields.first, ["V", "A", "S", "C", "R", "M", "T"].contains(kind) else { unsupported += 1; continue }
            // Production user recorder omits optional t/m provenance flags.
            // Encode an empty flag column, preserving unspecified provenance.
            if let bareFields = ["S":3, "C":2, "R":2, "M":3, "T":3][kind], fields.count == bareFields { row += "\t" }
            do { try CatalogWire.row(kind: kind, text: row) } catch { malformed += 1; continue }
            let id = CatalogWire.hash(try CatalogWire.canonical(["kind":kind, "row":row]))
            if seen.contains(cid + id) { known += 1; continue }
            let record = ["id":id, "kind":kind, "row":row]
            let one = try CatalogWire.canonical(["protocol":CatalogWire.version, "context":context, "records":[record]])
            if next.pending.count >= 4096 || bytes + one.count > 16 * 1024 * 1024 { deferred += 1; continue }
            next.pending.append(CatalogPending(contextID: cid, id: id, envelope: one))
            bytes += one.count; seen.insert(cid + id); queued += 1
        }
        try persist(next)
        return CatalogIngestResult(queued: queued, alreadyKnown: known, unsupported: unsupported, malformed: malformed, deferred: deferred)
    }
    private func request(path: String, body: Data? = nil, limit: Int) async throws -> Data {
        guard let endpoint else { throw KokiriError.message("The public catalog is not configured in this build.") }
        var request = URLRequest(url: endpoint.appendingPathComponent(path))
        request.httpMethod = body == nil ? "GET" : "POST"; request.httpBody = body
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == (body == nil ? 200 : 202) else { throw KokiriError.message("Catalog request was not accepted.") }
        if response.expectedContentLength > Int64(limit) { throw KokiriError.message("Catalog response exceeds limits.") }
        var data = Data()
        for try await byte in bytes { if data.count == limit { throw KokiriError.message("Catalog response exceeds limits.") }; data.append(byte) }
        return data
    }
    public func flushAutomatic() async throws {
        guard !isFlushing else { return }; isFlushing = true; defer { isFlushing = false }
        guard endpoint != nil else { return }
        while state.consent == true && !sessionStopped && state.retryAt <= Date().timeIntervalSince1970 {
            guard let first = state.pending.first else { lastError = nil; return }
            var batch: [CatalogPending] = []; var records: [[String: Any]] = []
            let c = try CatalogWire.context(CatalogWire.envelope(CatalogWire.parse(first.envelope, limit: 65536))["context"])
            for p in state.pending where p.contextID == first.contextID {
                let e = try CatalogWire.envelope(CatalogWire.parse(p.envelope, limit: 65536))
                let record = (e["records"] as! [[String: Any]])[0]
                let trial = try CatalogWire.canonical(["protocol": CatalogWire.version, "context": c, "records": records + [record]])
                if batch.count == 64 || trial.count > 65536 { break }
                batch.append(p); records.append(record)
            }
            do {
                let body = try CatalogWire.canonical(["protocol": CatalogWire.version, "context": c, "records": records])
                let response = try await request(path: "v1/contributions", body: body, limit: 65536)
                let a = try CatalogWire.object(CatalogWire.parse(response, limit: 65536), ["protocol", "context_id", "state", "accepted_ids", "inserted", "duplicates"])
                try CatalogWire.require(a["protocol"] as? String == CatalogWire.version && a["context_id"] as? String == first.contextID && a["state"] as? String == "quarantined" && (a["accepted_ids"] as? [String])?.sorted() == batch.map(\.id).sorted(), "Catalog acknowledgment does not match the batch.")
                let acknowledged = Set(batch.map { $0.contextID + $0.id })
                var next = state // actor may have processed opt-out or enqueue during request
                next.pending.removeAll { acknowledged.contains($0.contextID + $0.id) }
                var ledger = next.acknowledged ?? []
                let previous = Set(ledger)
                ledger.append(contentsOf: batch.map { $0.contextID + $0.id }.filter { !previous.contains($0) })
                next.acknowledged = Array(ledger.suffix(16384))
                next.failures = 0; next.retryAt = 0; try persist(next)
                if !sessionStopped || state.consent != true { lastError = nil }
            } catch {
                var next = state; next.failures = min(next.failures + 1, 10)
                next.retryAt = Date().timeIntervalSince1970 + min(3600, pow(2, Double(next.failures)))
                lastError = "Catalog sharing is waiting for a safe retry. Queued metadata was kept."
                try? persist(next); throw error
            }
        }
    }
    /// Downloads only trusted, exact-context metadata to a separate atomic
    /// artifact. Runtime adoption is explicit; this never replaces a shader cache.
    public func refresh(context data: Data) async throws -> URL {
        try CatalogWire.require(!isRefreshing, "Catalog refresh is already running.")
        isRefreshing = true; defer { isRefreshing = false }
        let expected = try CatalogWire.context(CatalogWire.parse(data, limit: 2048))
        try CatalogWire.require(CatalogWire.fingerprints.allSatisfy { !(expected[$0] is NSNull) }, "The runtime context is not qualified for shared warm-up.")
        let cid = CatalogWire.hash(try CatalogWire.canonical(expected))
        let raw = try await request(path: "v1/catalogs/\(cid)/manifest", limit: 262144)
        let signed = try CatalogWire.object(CatalogWire.parse(raw, limit: 262144), ["manifest", "key_id", "signature"])
        guard let keyID = signed["key_id"] as? String, let key = trustedKeys[keyID],
              let signatureText = signed["signature"] as? String, let signature = Data(base64Encoded: signatureText), signature.count == 64 else { throw KokiriError.message("Catalog signing key is not trusted.") }
        let m = try CatalogWire.object(signed["manifest"], ["protocol", "context", "context_id", "compatibility", "dataset_license", "attribution", "revision", "packs", "record_count"])
        try CatalogWire.require(try Curve25519.Signing.PublicKey(rawRepresentation: key).isValidSignature(signature, for: CatalogWire.canonical(m)), "Catalog signature is invalid.")
        let actual = try CatalogWire.context(m["context"])
        try CatalogWire.require(try CatalogWire.canonical(actual) == CatalogWire.canonical(expected), "Catalog context is incompatible.")
        try CatalogWire.require(m["protocol"] as? String == CatalogWire.version && m["context_id"] as? String == cid && m["compatibility"] as? String == "exact" && m["dataset_license"] as? String == "MIT", "Catalog manifest is incompatible.")
        guard let revision = CatalogWire.integer(m["revision"]), revision >= 1,
              let count = CatalogWire.integer(m["record_count"]), (0...100000).contains(count),
              let index = m["packs"] as? [[String: Any]], index.count <= 1024,
              let attribution = m["attribution"] as? [[String: Any]], (1...8).contains(attribution.count) else { throw KokiriError.message("Catalog manifest exceeds limits.") }
        for a in attribution {
            _ = try CatalogWire.object(a, ["name", "source_url", "source_commit", "license"])
            try CatalogWire.require((a["name"] as? String).map { CatalogWire.matches($0, "[A-Za-z0-9 ._-]{1,100}") } == true && a["license"] as? String == "MIT" && (a["source_url"] as? String).map { CatalogWire.matches($0, "https://[A-Za-z0-9./_-]{1,200}") } == true && (a["source_commit"] as? String).map { CatalogWire.matches($0, "[a-f0-9]{40}") } == true, "Invalid catalog attribution.")
        }
        try CatalogWire.require(revision >= (state.revisions[cid] ?? 0), "Catalog revision went backwards.")
        try CatalogWire.require(state.revisions[cid] != nil || state.revisions.count < 256, "Catalog context history is full.")
        let fm = FileManager.default
        try fm.createDirectory(at: store, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        // Single directory-owner contract: recover only our UUID-named partial
        // downloads from a previously interrupted process, never other folders.
        for file in try fm.contentsOfDirectory(at: store, includingPropertiesForKeys: [.isSymbolicLinkKey, .isDirectoryKey])
        where CatalogWire.matches(file.lastPathComponent, "\\.download-[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}") {
            let values = try file.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
            try CatalogWire.require(values.isDirectory == true && values.isSymbolicLink != true, "Unexpected partial catalog download entry.")
            try fm.removeItem(at: file)
        }
        let cache = store.appendingPathComponent("packs", isDirectory: true)
        if fm.fileExists(atPath: cache.path) {
            let values = try cache.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
            try CatalogWire.require(values.isSymbolicLink != true && values.isDirectory == true, "Catalog pack cache is not a private directory.")
        }
        try fm.createDirectory(at: cache, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        // Reserve one MiB for the new atomic index while the old index exists.
        // Pack files + published indexes + staged bytes remain under64 MiB.
        var cacheBytes = 1024 * 1024
        let readyFolder = store.appendingPathComponent("runtime-ready", isDirectory: true)
        if fm.fileExists(atPath: readyFolder.path) {
            let values = try readyFolder.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
            try CatalogWire.require(values.isDirectory == true && values.isSymbolicLink != true, "Unexpected catalog index folder.")
            let files = try fm.contentsOfDirectory(at: readyFolder, includingPropertiesForKeys: [.isSymbolicLinkKey, .isRegularFileKey, .fileSizeKey])
            try CatalogWire.require(files.count <= 256, "Catalog index history is full.")
            for file in files {
                let v = try file.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey, .fileSizeKey])
                try CatalogWire.require(v.isRegularFile == true && v.isSymbolicLink != true && CatalogWire.matches(file.lastPathComponent, "[a-f0-9]{64}\\.json") && (v.fileSize ?? Int.max) <= 1024 * 1024, "Unexpected catalog index entry.")
                cacheBytes += v.fileSize ?? 1024 * 1024
            }
        }
        try CatalogWire.require(cacheBytes <= 64 * 1024 * 1024, "Catalog index cache is full.")
        // Only this dedicated, flat content-addressed cache is counted. Never
        // enumerate or prune the game's own cache or another application folder.
        for file in try fm.contentsOfDirectory(at: cache, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]) {
            let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            try CatalogWire.require(values.isRegularFile == true && values.isSymbolicLink != true && CatalogWire.matches(file.lastPathComponent, "[a-f0-9]{64}\\.json"), "Unexpected catalog pack cache entry.")
            cacheBytes += values.fileSize ?? 64 * 1024 * 1024
            try CatalogWire.require(cacheBytes <= 64 * 1024 * 1024, "Catalog pack cache is full.")
        }
        let staging = store.appendingPathComponent(".download-" + UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: staging, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        var promoted: [URL] = []; var published = false
        defer {
            try? fm.removeItem(at: staging)
            // New files cannot be referenced by an older published index: their
            // hash paths did not exist before this refresh. Keep them only after
            // the new index's atomic publication point.
            if !published { for file in promoted { try? fm.removeItem(at: file) } }
        }
        var packReferences: [[String: Any]] = []
        var staged: [(URL, URL)] = []
        var seen = Set<String>(); var recordIDs = Set<String>(); var bytesTotal = 0; var recordsTotal = 0
        for p in index {
            _ = try CatalogWire.object(p, ["sha256", "bytes", "record_count"])
            guard let hash = p["sha256"] as? String, CatalogWire.matches(hash, "[a-f0-9]{64}"), seen.insert(hash).inserted,
                  let size = CatalogWire.integer(p["bytes"]), (1...262144).contains(size),
                  let n = CatalogWire.integer(p["record_count"]), (1...128).contains(n) else { throw KokiriError.message("Invalid catalog pack index.") }
            bytesTotal += size; recordsTotal += n
            try CatalogWire.require(bytesTotal <= 64 * 1024 * 1024 && recordsTotal <= 100000, "Catalog download exceeds application limits.")
            let destination = cache.appendingPathComponent(hash + ".json")
            let exists = fm.fileExists(atPath: destination.path)
            let data: Data
            if exists {
                let values = try destination.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
                try CatalogWire.require(values.isRegularFile == true && values.isSymbolicLink != true && values.fileSize == size, "Cached catalog pack size/type mismatch.")
                data = try Data(contentsOf: destination)
            } else {
                cacheBytes += size
                try CatalogWire.require(cacheBytes <= 64 * 1024 * 1024, "Catalog pack cache is full.")
                data = try await request(path: "v1/packs/\(hash)", limit: size)
            }
            try CatalogWire.require(data.count == size && CatalogWire.hash(data) == hash, "Catalog pack integrity check failed.")
            // Bound Foundation's temporary object lifetimes to one pack. Only
            // fixed-size record IDs and small index entries survive this pool.
            try autoreleasepool {
                let pack = try CatalogWire.object(CatalogWire.parse(data, limit: size), ["protocol", "context_id", "records"])
                guard pack["protocol"] as? String == CatalogWire.version, pack["context_id"] as? String == cid,
                      let records = pack["records"] as? [Any], records.count == n else { throw KokiriError.message("Catalog pack context/count mismatch.") }
                for r in records {
                    let validated = try CatalogWire.record(r)
                    try CatalogWire.require(recordIDs.insert(validated["id"] as! String).inserted, "Duplicate catalog record across packs.")
                }
            }
            if !exists {
                let temporary = staging.appendingPathComponent(hash + ".json")
                try data.write(to: temporary, options: .withoutOverwriting)
                staged.append((temporary, destination))
            }
            packReferences.append(["sha256":hash, "bytes":size, "record_count":n, "relative_path":"../packs/" + hash + ".json"])
        }
        try CatalogWire.require(recordsTotal == count, "Catalog total count mismatch.")
        let artifact = try CatalogWire.canonical(["protocol": CatalogWire.version, "context_id": cid, "signed_manifest": signed, "pack_files": packReferences])
        try CatalogWire.require(artifact.count <= 1024 * 1024, "Catalog index exceeds application limits.")
        let folder = store.appendingPathComponent("runtime-ready", isDirectory: true)
        if FileManager.default.fileExists(atPath: folder.path) {
            let values = try folder.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
            try CatalogWire.require(values.isSymbolicLink != true && values.isDirectory == true, "Catalog artifact folder is not a private directory.")
        }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let destination = folder.appendingPathComponent(cid + ".json")
        // Persist the anti-rollback floor before publishing the artifact. If
        // publication fails, retrying the same revision is safe; a lower one
        // remains rejected even after restart. No old cache is adopted here.
        var reserved = state; reserved.revisions[cid] = revision; try persist(reserved)
        for (temporary, final) in staged {
            try fm.moveItem(at: temporary, to: final)
            promoted.append(final)
        }
        try artifact.write(to: destination, options: .atomic)
        published = true
        var next = state; next.reviewedRecords = count; try persist(next); lastError = nil
        return destination
    }
}
