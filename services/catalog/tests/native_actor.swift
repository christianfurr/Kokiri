import Foundation
import CryptoKit

private enum FixtureError: Error { case failed(String) }
private var checks = 0
private func expect(_ ok: Bool, _ message: String) throws {
    checks += 1; if !ok { throw FixtureError.failed(message) }
}
private final class Intercept: URLProtocol, @unchecked Sendable {
    static var handler: ((URLRequest) async throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Task {
            do {
                guard request.url?.host == "catalog.invalid", let handler = Self.handler else { throw FixtureError.failed("unexpected network request") }
                let (status, body) = try await handler(request)
                let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type":"application/json"] )!
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                client?.urlProtocol(self, didLoad: body)
                client?.urlProtocolDidFinishLoading(self)
            } catch { client?.urlProtocol(self, didFailWithError: error) }
        }
    }
    override func stopLoading() {}
}
private func json(_ value: Any) throws -> Data { try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes]) }
private func read(_ name: String) throws -> Data { try Data(contentsOf: URL(fileURLWithPath: "tests/fixtures/" + name)) }
private func object(_ data: Data) throws -> [String: Any] { try JSONSerialization.jsonObject(with: data) as! [String: Any] }
private func requestBody(_ request: URLRequest) throws -> Data {
    if let data = request.httpBody { return data }
    guard let stream = request.httpBodyStream else { throw FixtureError.failed("missing request body") }
    stream.open(); defer { stream.close() }
    var data = Data(); var buffer = [UInt8](repeating: 0, count: 4096)
    while stream.hasBytesAvailable {
        let n = stream.read(&buffer, maxLength: buffer.count)
        if n < 0 { throw FixtureError.failed("request body stream failed") }
        if n == 0 { break }; data.append(buffer, count: n)
        if data.count > 65536 { throw FixtureError.failed("request body too large") }
    }
    return data
}
private func actor(store: URL, endpoint: URL, keys: [String: Data]) throws -> CatalogClient {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [Intercept.self]
    return try CatalogClient(store: store, endpoint: endpoint, trustedKeys: keys, sessionConfiguration: config)
}

@main struct NativeActorTests {
    static func main() async throws {
        _ = URLProtocol.registerClass(Intercept.self)
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("kokiri-catalog-tests-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let keysText = try object(read("trusted-keys.json"))
        let keys = keysText.mapValues { Data(base64Encoded: $0 as! String)! }
        let endpoint = URL(string: "https://catalog.invalid")!
        let contribution = try read("contribution.json")
        let e = try object(contribution)
        let signedData = try read("manifest.json")
        let signed = try object(signedData)
        let manifest = signed["manifest"] as! [String: Any]
        let cid = manifest["context_id"] as! String
        let pack = try read("pack.json")
        // Fixture pack on disk has a newline; server returns canonical pack bytes.
        let packBytes = try json(try object(pack))
        let client = try actor(store: root.appendingPathComponent("positive"), endpoint: endpoint, keys: keys)
        var requests = 0
        Intercept.handler = { request in
            requests += 1
            if request.httpMethod == "POST" {
                let body = try object(requestBody(request))
                let records = body["records"] as! [[String: Any]]
                return (202, try json(["protocol":"kokiri-catalog/1", "context_id":cid,"state":"quarantined","accepted_ids":records.map { $0["id"]! },"inserted":records.count,"duplicates":0]))
            }
            return request.url!.path.hasSuffix("/manifest") ? (200,signedData) : (200,packBytes)
        }
        try await client.flushAutomatic()
        try expect(requests == 0, "undecided made request")
        try await client.setConsent(nil)
        let undecided = await client.status(); try expect(undecided.consent == nil, "undecided was relabeled disabled")
        do { try await client.enqueueValidatedEnvelope(contribution); throw FixtureError.failed("undecided enqueue") } catch is KokiriError { checks += 1 }
        try await client.setConsent(true)
        try await client.enqueueValidatedEnvelope(contribution)
        try await client.enqueueValidatedEnvelope(contribution)
        let queued = await client.status(); try expect(queued.queued == 1, "dedup failed")
        try await client.flushAutomatic()
        let drained = await client.status(); try expect(drained.queued == 0 && requests == 1, "drain failed")
        let artifact = try await client.refresh(context: read("context.json"))
        try expect(FileManager.default.fileExists(atPath: artifact.path), "missing runtime metadata artifact")
        let ready = await client.status(); try expect(ready.reviewedRecords == 1, "verified count")
        let loaded = try actor(store: root.appendingPathComponent("positive"), endpoint: endpoint, keys: keys)
        let remembered = await loaded.status(); try expect(remembered.consent == true && remembered.reviewedRecords == 1, "not durable")

        // Every malformed/tampered test uses actual native validator/crypto, with
        // intercepted HTTPS. No real endpoint or production key exists here.
        var malformed = e; malformed["source"] = "private shader code"
        do { try await client.enqueueValidatedEnvelope(json(malformed)); throw FixtureError.failed("private fields accepted") } catch is KokiriError { checks += 1 }
        let untrusted = try actor(store: root.appendingPathComponent("untrusted"), endpoint: endpoint, keys: [:])
        do { _ = try await untrusted.refresh(context: read("context.json")); throw FixtureError.failed("untrusted signer") } catch is KokiriError { checks += 1 }
        var wrong = try object(read("context.json")); wrong["backend"] = "vulkan"
        do { _ = try await client.refresh(context: json(wrong)); throw FixtureError.failed("wrong backend") } catch is KokiriError { checks += 1 }
        var badSigned = signed; var changed = manifest; changed["revision"] = 2; badSigned["manifest"] = changed
        Intercept.handler = { _ in (200,try json(badSigned)) }
        do { _ = try await client.refresh(context: read("context.json")); throw FixtureError.failed("tampered manifest") } catch is KokiriError { checks += 1 }

        let offline = try actor(store: root.appendingPathComponent("offline"), endpoint: endpoint, keys: keys)
        try await offline.setConsent(true); try await offline.enqueueValidatedEnvelope(contribution)
        Intercept.handler = { _ in throw URLError(.notConnectedToInternet) }
        do { try await offline.flushAutomatic(); throw FixtureError.failed("offline unexpectedly succeeded") } catch is URLError { checks += 1 }
        let kept = await offline.status(); try expect(kept.queued == 1 && kept.lastError != nil, "offline lost queue")

        let cancellation = try actor(store: root.appendingPathComponent("cancellation"), endpoint: endpoint, keys: keys)
        try await cancellation.setConsent(true)
        var records: [[String: Any]] = []
        for n in 0..<65 {
            let row = "S\t" + String(format:"%064x",n) + "-" + String(repeating:"b",count:12) + "_b\t0\tm"
            let content: [String: Any] = ["kind":"S","row":row]
            let id = SHA256.hash(data: try json(content)).map { String(format:"%02x",$0) }.joined()
            records.append(["kind":"S","row":row,"id":id])
        }
        for part in [Array(records.prefix(64)),Array(records.suffix(1))] {
            try await cancellation.enqueueValidatedEnvelope(json(["protocol":"kokiri-catalog/1","context":e["context"]!,"records":part]))
        }
        var chunks = 0
        Intercept.handler = { request in
            chunks += 1
            let body = try object(requestBody(request)); let entries = body["records"] as! [[String: Any]]
            try await cancellation.setConsent(false)
            return (202,try json(["protocol":"kokiri-catalog/1","context_id":cid,"state":"quarantined","accepted_ids":entries.map { $0["id"]! },"inserted":entries.count,"duplicates":0]))
        }
        try await cancellation.flushAutomatic()
        let stopped = await cancellation.status()
        try expect(chunks == 1 && stopped.queued == 1 && stopped.consent == false, "opt-out did not stop chunk2")

        let ingest = try actor(store: root.appendingPathComponent("ingest"), endpoint: endpoint, keys: keys)
        try await ingest.setConsent(true)
        let originalRow = ((e["records"] as! [[String:Any]])[0]["row"] as! String).components(separatedBy:"\t").prefix(3).joined(separator:"\t")
        let runtimeFile = root.appendingPathComponent("pso_user.tsv")
        let raw = "# runtime user records\n" + originalRow + "\nB\tunsupported\nL\tprivate/path\nS\t../../private\t0\n"
        try Data(raw.utf8).write(to: runtimeFile)
        let ingested = try await ingest.ingestRuntimeMetadata(from: runtimeFile, context: read("context.json"))
        try expect(ingested.queued == 1 && ingested.unsupported == 2 && ingested.malformed == 1 && ingested.deferred == 0, "runtime adapter coverage")
        let repeated = try await ingest.ingestRuntimeMetadata(from: runtimeFile, context: read("context.json"))
        try expect(repeated.queued == 0 && repeated.alreadyKnown == 1, "runtime queue dedup")
        Intercept.handler = { request in
            let body = try object(requestBody(request)); let entries = body["records"] as! [[String:Any]]
            try expect((entries[0]["row"] as! String).hasSuffix("\t"), "runtime invented provenance flags")
            return (202,try json(["protocol":"kokiri-catalog/1","context_id":cid,"state":"quarantined","accepted_ids":entries.map { $0["id"]! },"inserted":entries.count,"duplicates":0]))
        }
        try await ingest.flushAutomatic()
        let acknowledged = try await ingest.ingestRuntimeMetadata(from: runtimeFile, context: read("context.json"))
        try expect(acknowledged.queued == 0 && acknowledged.alreadyKnown == 1, "acknowledged runtime records requeued")
        try await ingest.setConsent(false)
        do {
            _ = try await ingest.ingestRuntimeMetadata(from: root.appendingPathComponent("does-not-exist"), context: read("context.json"))
            throw FixtureError.failed("disabled ingested records")
        } catch let error as KokiriError { try expect(error.localizedDescription.contains("Choose metadata"), "disabled accessed file before consent") }

        // Reference-only context cannot make a native download/warm-up request.
        var reference = try object(read("context.json")); reference["compiler_sha256"] = NSNull()
        var referenceRequests = 0
        Intercept.handler = { _ in referenceRequests += 1; throw FixtureError.failed("reference requested") }
        do { _ = try await ingest.refresh(context: json(reference)); throw FixtureError.failed("reference warm-up") } catch is KokiriError { checks += 1 }
        try expect(referenceRequests == 0, "reference download attempted")

        let failureStore = root.appendingPathComponent("failed-off")
        let failure = try actor(store: failureStore, endpoint: endpoint, keys: keys)
        try await failure.setConsent(true); try await failure.enqueueValidatedEnvelope(contribution)
        let queuePath = failureStore.appendingPathComponent("queue.json")
        try FileManager.default.removeItem(at: queuePath)
        try FileManager.default.createDirectory(at: queuePath, withIntermediateDirectories: false)
        try Data([1]).write(to: queuePath.appendingPathComponent("block-replacement"))
        do { try await failure.setConsent(false); throw FixtureError.failed("failed-off unexpectedly persisted") } catch { checks += 1 }
        try await failure.flushAutomatic()
        let failedOff = await failure.status()
        try expect(failedOff.consent == false && failedOff.queued == 1 && failedOff.lastError != nil && referenceRequests == 0, "failed-off did not fail closed")

        // A publication failure after verification must still persist the
        // anti-rollback floor. Both revisions carry valid signatures here.
        let signing = Curve25519.Signing.PrivateKey()
        let revisionStore = root.appendingPathComponent("revision-floor")
        let revisionClient = try actor(store: revisionStore, endpoint: endpoint, keys: ["local-test":signing.publicKey.rawRepresentation])
        let blocked = revisionStore.appendingPathComponent("runtime-ready").appendingPathComponent(cid + ".json")
        var servedRevision = 2
        Intercept.handler = { request in
            if request.url!.path.hasSuffix("/manifest") {
                var m = manifest; m["revision"] = servedRevision
                let sig = try signing.signature(for: json(m))
                return (200,try json(["manifest":m,"key_id":"local-test","signature":sig.base64EncodedString()]))
            }
            // Force the publication failure only after cache/index preflight,
            // while the final pack's HTTPS request is in flight.
            try FileManager.default.createDirectory(at: blocked, withIntermediateDirectories: true)
            try Data([1]).write(to: blocked.appendingPathComponent("block-publication"))
            return (200,packBytes)
        }
        do { _ = try await revisionClient.refresh(context: read("context.json")); throw FixtureError.failed("blocked publication succeeded") }
        catch let error { if error is FixtureError { throw error }; checks += 1 }
        let leftover = try FileManager.default.contentsOfDirectory(atPath: revisionStore.path)
        let failedPacks = try FileManager.default.contentsOfDirectory(atPath: revisionStore.appendingPathComponent("packs").path)
        try expect(!leftover.contains { $0.hasPrefix(".download-") } && failedPacks.isEmpty, "failed publication left partial packs/staging")
        servedRevision = 1
        let reopened = try actor(store: revisionStore, endpoint: endpoint, keys: ["local-test":signing.publicKey.rawRepresentation])
        do { _ = try await reopened.refresh(context: read("context.json")); throw FixtureError.failed("signed rollback accepted") }
        catch let error as KokiriError { try expect(error.localizedDescription.contains("backwards"), "wrong rollback failure") }

        // Initial-game scale gate: 50,376 unique recipes across bounded packs.
        // The server fixture and client both materialize only one pack at once.
        let server = root.appendingPathComponent("synthetic-server")
        try FileManager.default.createDirectory(at: server, withIntermediateDirectories: true)
        let corpusCount = 50376
        var corpusIndex: [[String: Any]] = []
        var packRecords: [[String: Any]] = []
        func savePack() throws {
            guard !packRecords.isEmpty else { return }
            let bytes = try json(["protocol":"kokiri-catalog/1","context_id":cid,"records":packRecords])
            let hash = SHA256.hash(data: bytes).map { String(format:"%02x",$0) }.joined()
            try bytes.write(to: server.appendingPathComponent(hash + ".json"))
            corpusIndex.append(["sha256":hash,"bytes":bytes.count,"record_count":packRecords.count])
            packRecords.removeAll(keepingCapacity: true)
        }
        for n in 0..<corpusCount {
            let row = "S\t" + String(format:"%064x",n) + "-" + String(repeating:"b",count:12) + "_b\t0\tm"
            let id = SHA256.hash(data: try json(["kind":"S","row":row])).map { String(format:"%02x",$0) }.joined()
            packRecords.append(["id":id,"kind":"S","row":row])
            if packRecords.count == 128 { try savePack() }
        }
        try savePack()
        var corpusManifest = manifest
        corpusManifest["packs"] = corpusIndex; corpusManifest["record_count"] = corpusCount
        let corpusSignature = try signing.signature(for: json(corpusManifest))
        let corpusEnvelope = try json(["manifest":corpusManifest,"key_id":"local-test","signature":corpusSignature.base64EncodedString()])
        let corpusStore = root.appendingPathComponent("full-corpus")
        let stale = corpusStore.appendingPathComponent(".download-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: stale, withIntermediateDirectories: true)
        try Data([1]).write(to: stale.appendingPathComponent("interrupted-partial"))
        let corpus = try actor(store: corpusStore, endpoint: endpoint, keys: ["local-test":signing.publicKey.rawRepresentation])
        var packRequests = 0
        Intercept.handler = { request in
            if request.url!.path.hasSuffix("/manifest") { return (200,corpusEnvelope) }
            packRequests += 1
            return (200,try Data(contentsOf: server.appendingPathComponent(request.url!.lastPathComponent + ".json")))
        }
        let corpusArtifact = try await corpus.refresh(context: read("context.json"))
        try expect(!FileManager.default.fileExists(atPath: stale.path), "interrupted staging was not recovered")
        let corpusState = await corpus.status()
        let indexBytes = try Data(contentsOf: corpusArtifact)
        let indexObject = try object(indexBytes)
        try expect(corpusState.reviewedRecords == corpusCount && packRequests == 394, "full first-game corpus was not accepted")
        try expect(indexBytes.count < 1024*1024 && indexObject["packs"] == nil && (indexObject["pack_files"] as? [Any])?.count == 394, "client published aggregate packs instead of bounded index")
        let cached = try FileManager.default.contentsOfDirectory(at: corpusStore.appendingPathComponent("packs"), includingPropertiesForKeys: [.fileSizeKey])
        let diskBytes = try cached.reduce(0) { $0 + (try $1.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? 0) }
        try expect(cached.count == 394 && diskBytes < 64*1024*1024, "full corpus escaped disk bounds")
        _ = try await corpus.refresh(context: read("context.json"))
        try expect(packRequests == 394, "verified immutable packs were fetched twice")
        print("full corpus: \(corpusCount) records / \(cached.count) packs / \(diskBytes) bytes; index \(indexBytes.count) bytes")
        print("PASS native CatalogClient \(checks) checks; intercepted HTTPS only; no production requests")
    }
}
