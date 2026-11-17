import CryptoKit
import Foundation
import XCTest
@testable import KokiriCore

private final class ReferenceProtocol: URLProtocol, @unchecked Sendable {
    static let lock = NSLock()
    nonisolated(unsafe) static var responses: [String: Data] = [:]
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let data = Self.lock.withLock { Self.responses[request.url!.path] }
        let response = HTTPURLResponse(url: request.url!, statusCode: data == nil ? 404 : 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data ?? Data())
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class ShaderLibraryTests: XCTestCase {
    func testPreparedReceiptAllowsExtraIndexedMeshButRejectsMissingCoverage() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        let hash = String(repeating: "a", count: 64)
        for (indexed, accepted) in [(2, true), (0, false)] {
            let app = folder.appendingPathComponent("Game\(indexed).app")
            let file = app.appendingPathComponent("Contents/Resources/totk/build/game-data/oot/preparation-receipt.json")
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            let receipt: [String: Any] = ["schema": "kokiri-preparation-receipt-v1", "prepared": true, "mode": "full", "errors": [], "unresolved_inputs": [],
                "identity": ["runtime_sha256": hash, "chain": "v28"],
                "libraries": ["unique_prepared_files": 2, "unique_requested_files": 2, "failed": 0],
                "pipelines": ["completed": 3, "requested": 3, "failed": 0, "write_failed": 0, "unaccounted": 0, "mesh_requested": 1, "mesh_indexed": indexed]]
            let data = try JSONSerialization.data(withJSONObject: receipt)
            try data.write(to: file)
            let info: [String: Any] = ["CFBundleIdentifier": "test.preparation.\(indexed)", "KokiriPrepared": true, "KokiriShaders": "full", "KokiriBuildRuntimeSHA256": hash,
                "KokiriPreparationReceiptSHA256": CatalogWire.hash(data), "KokiriGameUpdate": "131072"]
            try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: app.appendingPathComponent("Contents/Info.plist"))
            if accepted { XCTAssertEqual(try RuntimePreparation.load(app: app).meshPipelines, 1) }
            else { XCTAssertThrowsError(try RuntimePreparation.load(app: app)) }
        }
    }
    func testLargeMetadataListIncludesRecordsBeyondOldLimitWithoutCountingCommentsOrDuplicates() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("pso_manifest.tsv")
        try Data(("#" + String(repeating: "x", count: 17 << 20) + "\nR\tone\nM\ttwo\nR\tone\n").utf8).write(to: file)
        XCTAssertEqual(ShaderMetadata.counts(files: [file]), ["R": 1, "M": 1])
    }

    func testReferenceDownloadVerifiesSignatureAndCannotBecomeRuntimeReady() async throws {
        let key = Curve25519.Signing.PrivateKey()
        let context: [String: Any] = ["game_id": "oot", "game_version": "131072", "shader_chain": "v28", "recipe_format": "mng-list-v1", "backend": "metal",
            "game_content_sha256": String(repeating: "1", count: 64), "translator_sha256": String(repeating: "2", count: 64),
            "compiler_sha256": String(repeating: "3", count: 64), "target_sha256": NSNull(), "options_sha256": NSNull()]
        let contextData = try CatalogWire.canonical(context), cid = CatalogWire.hash(contextData)
        let row = "C\t" + String(repeating: "a", count: 64) + "-" + String(repeating: "b", count: 12) + "_b\tm"
        let identity = try CatalogWire.canonical(["kind": "C", "row": row])
        let pack = try CatalogWire.canonical(["protocol": CatalogWire.version, "context_id": cid,
            "records": [["id": CatalogWire.hash(identity), "kind": "C", "row": row]]])
        let hash = CatalogWire.hash(pack)
        let manifest: [String: Any] = ["protocol": CatalogWire.version, "context": context, "context_id": cid, "compatibility": "reference-only", "dataset_license": "MIT",
            "attribution": [["name": "Fixture", "source_url": "https://example.com", "source_commit": String(repeating: "a", count: 40), "license": "MIT"]],
            "revision": 1, "record_count": 1, "packs": [["sha256": hash, "bytes": pack.count, "record_count": 1]]]
        let signed = try CatalogWire.canonical(["manifest": manifest, "key_id": "fixture", "signature": key.signature(for: CatalogWire.canonical(manifest)).base64EncodedString()])
        ReferenceProtocol.lock.withLock { ReferenceProtocol.responses = ["/v1/catalogs/\(cid)/manifest": signed, "/v1/packs/\(hash)": pack] }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        let configuration = URLSessionConfiguration.ephemeral; configuration.protocolClasses = [ReferenceProtocol.self]
        let client = try CatalogClient(store: folder, endpoint: URL(string: "https://catalog.invalid"), trustedKeys: ["fixture": key.publicKey.rawRepresentation], sessionConfiguration: configuration)
        let index = try await client.refreshReference(context: contextData)
        XCTAssertEqual(index.deletingLastPathComponent().lastPathComponent, "reference")
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent("runtime-ready").path))
        do { _ = try await client.refresh(context: contextData); XCTFail("Reference data must not qualify for runtime adoption") } catch is KokiriError {}
        var corrupt = signed; corrupt[corrupt.count - 3] ^= 1
        ReferenceProtocol.lock.withLock { ReferenceProtocol.responses["/v1/catalogs/\(cid)/manifest"] = corrupt }
        do { _ = try await client.refreshReference(context: contextData); XCTFail("Corrupt signed metadata must be rejected") } catch {}
        let status = await client.status(); XCTAssertEqual(status.reviewedRecords, 1)
    }
}
