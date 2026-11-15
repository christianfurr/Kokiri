import XCTest
import CryptoKit
import Darwin
@testable import KokiriCore

final class CatalogWarmPlanTests: XCTestCase {
    private final class Fixture {
        let root: URL
        let cache: URL
        let runtime: URL
        let identity: CatalogRuntimeIdentity
        let context: [String: Any]
        let signing = Curve25519.Signing.PrivateKey()
        var records: [[String: Any]] = []
        init() throws {
            root = URL(fileURLWithPath:try CatalogLocalFile.realPath(FileManager.default.temporaryDirectory)).appendingPathComponent("kokiri-warm-plan-" + UUID().uuidString)
            cache = root.appendingPathComponent("shader-cache/owned-context")
            runtime = root.appendingPathComponent("runtime")
            try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
            try Data("synthetic nonexecutable runtime fixture".utf8).write(to: runtime)
            let runtimeHash = try CatalogLocalFile.hash(runtime, limit: 4096).hash
            var size = 0
            XCTAssertEqual(sysctlbyname("kern.osversion", nil, &size, nil, 0), 0)
            var os = [CChar](repeating: 0, count: size)
            XCTAssertEqual(sysctlbyname("kern.osversion", &os, &size, nil, 0), 0)
            // Synthetic API UUID, never an observation of a real Metal device.
            let compiler: [String: Any] = ["schema":"kokiri-compiler-identity/1", "observed":true, "os_build":String(cString:os),
                "kind":"metal-runtime-jit", "platform_compiler_identity":"os-build-and-public-metal-api-image",
                "metal_api_uuid":"11111111-2222-4333-8444-555555555555"]
            let target: [String: Any] = ["schema":"kokiri-target-identity/1", "observed":true, "test_fixture":true]
            let options: [String: Any] = ["schema":"kokiri-options-identity/1", "observed":true, "runtime_sha256":runtimeHash, "test_fixture":true]
            var context: [String: Any] = ["game_id":"oot", "game_version":"131072", "game_content_sha256":String(repeating:"1", count:64),
                "recipe_format":"mng-list-v1", "backend":"metal", "shader_chain":"oot-test-v1", "translator_sha256":String(repeating:"2", count:64),
                "compiler_sha256":NSNull(), "target_sha256":NSNull(), "options_sha256":NSNull()]
            let template = root.appendingPathComponent("template.json")
            try CatalogWire.canonical(context).write(to: template)
            for (name, descriptor) in [("compiler",compiler), ("target",target), ("options",options)] {
                context[name + "_sha256"] = CatalogWire.hash(try CatalogWire.canonical(descriptor))
            }
            self.context = context
            let value: [String: Any] = ["schema":"kokiri-runtime-identity/1", "valid":true, "runtime_sha256":runtimeHash,
                "context":context, "context_id":CatalogWire.hash(try CatalogWire.canonical(context)), "compiler":compiler, "target":target, "options":options,
                "local_variant_directory":cache.path]
            let file = root.appendingPathComponent("identity.json")
            try CatalogWire.canonical(value).write(to: file)
            identity = try CatalogRuntimeIdentity.load(file, runtime: runtime, template: template, allowedCache: root.appendingPathComponent("shader-cache"))
        }
        deinit { try? FileManager.default.removeItem(at: root) }
        var keys: [String: Data] { ["fixture-only":signing.publicKey.rawRepresentation] }
        func variant(_ id: Int, stage: Int) throws -> String {
            let name = String(format:"%064x",id) + "-bbbbbbbbbbbb_b"
            try Data("synthetic nonshader local bytes \(id)".utf8).write(to: cache.appendingPathComponent(name + ".metal"))
            try CatalogWire.canonical(["key":name, "chain":"oot-test-v1", "stage":stage == 0 ? "vs" : stage == 1 ? "ps" : "cs", "entry":"test_fixture_only"])
                .write(to: cache.appendingPathComponent(name + ".json"))
            return name
        }
        func row(_ text: String) throws {
            let kind = String(text.prefix(1))
            let record: [String: Any] = ["kind":kind, "row":text]
            records.append(record.merging(["id":CatalogWire.hash(try CatalogWire.canonical(record))]) { _, new in new })
        }
        func index(revision: Int = 3) throws -> URL {
            let packs = root.appendingPathComponent("packs"), ready = root.appendingPathComponent("runtime-ready")
            try FileManager.default.createDirectory(at: packs, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: ready, withIntermediateDirectories: true)
            var parts: [[String: Any]] = []
            for at in stride(from:0, to:records.count, by:128) {
                let body = try CatalogWire.canonical(["protocol":CatalogWire.version, "context_id":identity.contextID, "records":Array(records[at..<min(at+128,records.count)])])
                let hash = CatalogWire.hash(body)
                try body.write(to: packs.appendingPathComponent(hash + ".json"))
                parts.append(["sha256":hash, "bytes":body.count, "record_count":min(128,records.count-at)])
            }
            let manifest: [String: Any] = ["protocol":CatalogWire.version, "context":context, "context_id":identity.contextID,
                "compatibility":"exact", "dataset_license":"MIT", "attribution":[["name":"Synthetic fixture", "source_url":"https://example.invalid/test", "source_commit":String(repeating:"a", count:40), "license":"MIT"]],
                "revision":revision, "packs":parts, "record_count":records.count]
            let signed: [String: Any] = ["manifest":manifest, "key_id":"fixture-only", "signature":try signing.signature(for:CatalogWire.canonical(manifest)).base64EncodedString()]
            let refs = parts.map { part in part.merging(["relative_path":"../packs/" + (part["sha256"] as! String) + ".json"]) { _, new in new } }
            let file = ready.appendingPathComponent(identity.contextID + ".json")
            try CatalogWire.canonical(["protocol":CatalogWire.version, "context_id":identity.contextID, "signed_manifest":signed, "pack_files":refs]).write(to:file)
            return file
        }
        func prepare(_ index: URL? = nil, floor: Int = 3, keys: [String: Data]? = nil) throws -> CatalogWarmPlan? {
            try CatalogWarmPlan.prepare(index:index ?? self.index(), identity:identity, trustedKeys:keys ?? self.keys, minimumRevision:floor, output:root.appendingPathComponent("session"))
        }
        func rewriteCompilerAndRehash(_ edit: (inout [String: Any]) -> Void) throws {
            let file = root.appendingPathComponent("identity.json")
            var value = try XCTUnwrap(JSONSerialization.jsonObject(with:Data(contentsOf:file)) as? [String:Any])
            var compiler = try XCTUnwrap(value["compiler"] as? [String:Any])
            var context = try XCTUnwrap(value["context"] as? [String:Any])
            edit(&compiler)
            context["compiler_sha256"] = CatalogWire.hash(try CatalogWire.canonical(compiler))
            value["compiler"] = compiler; value["context"] = context
            value["context_id"] = CatalogWire.hash(try CatalogWire.canonical(context))
            try CatalogWire.canonical(value).write(to:file)
        }
        func reloadIdentity() throws -> CatalogRuntimeIdentity {
            try CatalogRuntimeIdentity.load(root.appendingPathComponent("identity.json"), runtime:runtime,
                template:root.appendingPathComponent("template.json"), allowedCache:root.appendingPathComponent("shader-cache"))
        }
    }
    func testSignedNovelComputeRecipeUsesOnlyExistingLocalBytes() throws {
        let fixture = try Fixture(), name = try fixture.variant(1, stage:5)
        try fixture.row("C\t" + name + "\tm")
        let original = try Data(contentsOf:fixture.cache.appendingPathComponent(name + ".metal"))
        let plan = try XCTUnwrap(fixture.prepare())
        let data = try Data(contentsOf:plan.file), handoff = try XCTUnwrap(JSONSerialization.jsonObject(with:data) as? [String:Any])
        XCTAssertEqual(plan.selected,1); XCTAssertEqual(plan.sha256,CatalogWire.hash(data))
        XCTAssertEqual(handoff["rows"] as? [String],["C\t" + name])
        XCTAssertEqual(try Data(contentsOf:fixture.cache.appendingPathComponent(name + ".metal")),original)
        XCTAssertFalse(FileManager.default.fileExists(atPath:fixture.root.appendingPathComponent("profile").path))
    }
    func testPackedRenderUsesProductionABIAndRejectsHostPointers() throws {
        let fixture = try Fixture(), vs = try fixture.variant(1,stage:0), fs = try fixture.variant(2,stage:1)
        var tail = [UInt8](repeating:0,count:384); tail[1] = 1
        let key = vs + ":" + fs + ":" + tail.map { String(format:"%02x",$0) }.joined()
        try fixture.row("R\t" + key + "\tm")
        let plan = try XCTUnwrap(fixture.prepare()), value = try XCTUnwrap(JSONSerialization.jsonObject(with:Data(contentsOf:plan.file)) as? [String:Any])
        let row = try XCTUnwrap((value["rows"] as? [String])?.first)
        XCTAssertEqual(row.count,1090)
        var bytes = [UInt8](repeating:0,count:544)
        bytes.replaceSubrange(0..<vs.utf8.count,with:vs.utf8); bytes[200] = 1
        XCTAssertNil(try CatalogWarmPlan.recipe("R\t" + bytes.map { String(format:"%02x",$0) }.joined() + "\tm"))
    }
    func testSignaturePackAndRollbackGatesPrecedeOutput() throws {
        let fixture = try Fixture(), name = try fixture.variant(1,stage:5)
        try fixture.row("C\t" + name + "\tm")
        let index = try fixture.index()
        XCTAssertThrowsError(try fixture.prepare(index,keys:["fixture-only":Curve25519.Signing.PrivateKey().publicKey.rawRepresentation]))
        XCTAssertThrowsError(try fixture.prepare(index,floor:4))
        let pack = try XCTUnwrap(FileManager.default.contentsOfDirectory(at:fixture.root.appendingPathComponent("packs"),includingPropertiesForKeys:nil).first)
        var bytes = try Data(contentsOf:pack); bytes.append(32); try bytes.write(to:pack)
        XCTAssertThrowsError(try fixture.prepare(index))
        XCTAssertFalse(FileManager.default.fileExists(atPath:fixture.root.appendingPathComponent("session").path))
    }
    func testAbsentAndSymlinkLocalVariantsAreDeferred() throws {
        let fixture = try Fixture(), name = try fixture.variant(1,stage:5)
        try fixture.row("C\t" + name + "\tm")
        let source = fixture.cache.appendingPathComponent(name + ".metal"), moved = fixture.root.appendingPathComponent("source")
        try FileManager.default.moveItem(at:source,to:moved)
        XCTAssertNil(try fixture.prepare())
        try FileManager.default.createSymbolicLink(at:source,withDestinationURL:moved)
        XCTAssertNil(try fixture.prepare())
    }
    func testRetainedRecipeCountIsBoundedAndRestDeferred() throws {
        let fixture = try Fixture()
        for id in 1...513 { try fixture.row("C\t" + fixture.variant(id,stage:5) + "\tm") }
        let plan = try XCTUnwrap(fixture.prepare())
        XCTAssertEqual(plan.selected,512); XCTAssertEqual(plan.deferred,1)
        XCTAssertLessThanOrEqual(try Data(contentsOf:plan.file).count,1024*1024)
    }
    func testRuntimeReplacementInvalidatesPriorObservation() throws {
        let fixture = try Fixture()
        try Data("different runtime fixture".utf8).write(to:fixture.runtime)
        XCTAssertThrowsError(try CatalogRuntimeIdentity.load(fixture.root.appendingPathComponent("identity.json"),runtime:fixture.runtime,
            template:fixture.root.appendingPathComponent("template.json"),allowedCache:fixture.root.appendingPathComponent("shader-cache")))
    }
    func testOfflineAndUnknownCompilerSchemesFailEvenWithConsistentHashes() throws {
        for kind in ["metal-offline", "metal-offline-and-jit", "unknown"] {
            let fixture = try Fixture()
            try fixture.rewriteCompilerAndRehash { $0["kind"] = kind }
            XCTAssertThrowsError(try fixture.reloadIdentity())
        }
    }
    func testOfflineEvidenceCannotBeEmbeddedInTheRuntimeJITDescriptor() throws {
        for (key, value) in [("platform_compiler_identity", "offline-executable-hash"),
                             ("compiler_context_sha256", String(repeating:"a", count:64))] {
            let fixture = try Fixture()
            try fixture.rewriteCompilerAndRehash { $0[key] = value }
            XCTAssertThrowsError(try fixture.reloadIdentity())
        }
    }
    func testCompilerAPIUUIDRequiresTheCanonicalProducerFormat() throws {
        for value in ["not-a-uuid", "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE", "{11111111-2222-4333-8444-555555555555}"] {
            let fixture = try Fixture()
            try fixture.rewriteCompilerAndRehash { $0["metal_api_uuid"] = value }
            XCTAssertThrowsError(try fixture.reloadIdentity())
        }
        let missing = try Fixture()
        try missing.rewriteCompilerAndRehash { _ = $0.removeValue(forKey:"metal_api_uuid") }
        XCTAssertThrowsError(try missing.reloadIdentity())
    }
    func testSignedMeshMetadataRemainsUnchangedWithoutAnOrdinaryWarmPlan() throws {
        let fixture = try Fixture()
        let task = String(repeating:"a", count:64) + "-bbbbbbbbbbbb_b"
        let mesh = String(repeating:"c", count:64) + "-dddddddddddd_b"
        try fixture.row("M\t" + task + "\t" + mesh + ":-:z180.\tm")
        let index = try fixture.index()
        let pack = try XCTUnwrap(FileManager.default.contentsOfDirectory(at:fixture.root.appendingPathComponent("packs"),includingPropertiesForKeys:nil).first)
        let original = try Data(contentsOf:pack)
        XCTAssertNil(try fixture.prepare(index))
        XCTAssertEqual(try Data(contentsOf:pack), original)
        XCTAssertFalse(FileManager.default.fileExists(atPath:fixture.root.appendingPathComponent("session").path))
    }
    func testRepeatedRejectedVariantIsReadOnceAcrossManyRenderRecipes() throws {
        let fixture = try Fixture(), good = try fixture.variant(1,stage:5), wrongStage = try fixture.variant(2,stage:1)
        try fixture.row("C\t" + good + "\tm")
        let reflection = fixture.cache.appendingPathComponent(wrongStage + ".json")
        var metadata = try XCTUnwrap(JSONSerialization.jsonObject(with:Data(contentsOf:reflection)) as? [String:Any])
        metadata["padding"] = String(repeating:"x",count:900000)
        try CatalogWire.canonical(metadata).write(to:reflection)
        for id in 1...1000 {
            var state = [UInt8](repeating:0,count:544)
            state.replaceSubrange(0..<wrongStage.utf8.count,with:wrongStage.utf8)
            state[216] = UInt8(id & 255); state[217] = UInt8(id >> 8)
            try fixture.row("R\t" + state.map { String(format:"%02x",$0) }.joined() + "\tm")
        }
        let plan = try XCTUnwrap(fixture.prepare())
        XCTAssertEqual(plan.selected,1); XCTAssertEqual(plan.variantProofChecks,2)
        XCTAssertLessThan(plan.localProofBytes,1024*1024)
    }
    func testOversizedLocalSourceDoesNotReadPastAggregateProofBudget() throws {
        let fixture = try Fixture(), good = try fixture.variant(1,stage:5), large = try fixture.variant(2,stage:5)
        try fixture.row("C\t" + good + "\tm"); try fixture.row("C\t" + large + "\tm")
        let file = try FileHandle(forWritingTo:fixture.cache.appendingPathComponent(large + ".metal"))
        try file.truncate(atOffset:65*1024*1024); try file.close()
        let plan = try XCTUnwrap(fixture.prepare())
        XCTAssertEqual(plan.selected,1); XCTAssertEqual(plan.variantProofChecks,2)
        XCTAssertLessThan(plan.localProofBytes,4096)
    }
}
