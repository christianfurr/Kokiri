import Foundation
import CryptoKit
import Darwin
import CoreFoundation

/// A previous owned execution is a candidate identity. The renderer compares a
/// fresh observation before accepting any prepared rows on the next launch.
public struct CatalogRuntimeIdentity: Sendable {
    public let data: Data
    public let context: Data
    public let contextID: String
    public let runtimeHash: String
    public let variants: URL

    public static func load(_ file: URL, runtime: URL, template: URL, allowedCache: URL) throws -> Self {
        let data = try CatalogLocalFile.read(file, limit: 65536)
        let value = try CatalogWire.object(CatalogWire.parse(data, limit: 65536),
            ["schema", "valid", "context", "context_id", "runtime_sha256", "compiler", "target", "options", "local_variant_directory"])
        try CatalogWire.require(value["schema"] as? String == "kokiri-runtime-identity/1" && CatalogLocalFile.isTrue(value["valid"]), "Runtime catalog identity was invalidated or is unavailable.")
        let context = try CatalogWire.context(value["context"])
        let packaged = try CatalogWire.context(CatalogWire.parse(CatalogLocalFile.read(template, limit: 65536), limit: 65536))
        for field in CatalogWire.contextFields where !["compiler_sha256", "target_sha256", "options_sha256"].contains(field) {
            try CatalogWire.require(try CatalogWire.canonical(context[field]!) == CatalogWire.canonical(packaged[field]!), "The runtime catalog identity belongs to another build.")
        }
        let runtimeHash = try CatalogLocalFile.hash(runtime, limit: 1024 * 1024 * 1024).hash
        try CatalogWire.require(value["runtime_sha256"] as? String == runtimeHash, "Runtime executable changed after catalog observation.")
        for name in ["compiler", "target", "options"] {
            guard let descriptor = value[name] as? [String: Any], descriptor["schema"] as? String == "kokiri-\(name)-identity/1",
                  CatalogLocalFile.isTrue(descriptor["observed"]) else { throw KokiriError.message("Missing observed catalog identity.") }
            try CatalogWire.require(context[name + "_sha256"] as? String == CatalogWire.hash(try CatalogWire.canonical(descriptor)), "Catalog identity descriptor changed.")
        }
        let options = value["options"] as! [String: Any]
        let compiler = value["compiler"] as! [String: Any]
        var size = 0
        guard sysctlbyname("kern.osversion", nil, &size, nil, 0) == 0, size > 0, size < 128 else { throw KokiriError.message("The current OS build could not be observed.") }
        var os = [CChar](repeating: 0, count: size)
        guard sysctlbyname("kern.osversion", &os, &size, nil, 0) == 0 else { throw KokiriError.message("The current OS build could not be observed.") }
        try CatalogWire.require(compiler["os_build"] as? String == String(cString: os) && options["runtime_sha256"] as? String == runtimeHash, "Runtime compiler/platform identity changed.")
        let encoded = try CatalogWire.canonical(context), id = CatalogWire.hash(encoded)
        try CatalogWire.require(value["context_id"] as? String == id, "Runtime catalog context hash changed.")
        guard let path = value["local_variant_directory"] as? String else { throw KokiriError.message("The runtime did not identify its local variant cache.") }
        let variants = URL(fileURLWithPath: path)
        let allowed = try CatalogLocalFile.realPath(allowedCache)
        try CatalogWire.require(variants.path == CatalogLocalFile.realPath(variants) && variants.path.hasPrefix(allowed + "/"), "The local variant directory is outside Kokiri’s cache.")
        return Self(data: data, context: encoded, contextID: id, runtimeHash: runtimeHash, variants: variants)
    }
}

enum CatalogLocalFile {
    static func isTrue(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber else { return false }
        return CFGetTypeID(number) == CFBooleanGetTypeID() && number.boolValue
    }
    static func realPath(_ url: URL) throws -> String {
        guard let bytes = Darwin.realpath(url.path, nil) else { throw KokiriError.message("Catalog local directory is unavailable.") }
        defer { free(bytes) }
        return String(cString: bytes)
    }
    private static func open(_ url: URL, limit: Int) throws -> (Int32, stat) {
        let path = url.path
        let parts = path.split(separator: "/").map(String.init)
        try CatalogWire.require(path.hasPrefix("/") && path.utf8.count <= 4096 && !parts.isEmpty && parts.allSatisfy { $0 != "." && $0 != ".." }, "Invalid catalog local path.")
        var parent = Darwin.open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC)
        guard parent >= 0 else { throw KokiriError.message("Catalog directory is unavailable.") }
        for part in parts.dropLast() {
            let next = openat(parent, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            Darwin.close(parent); parent = next
            guard parent >= 0 else { throw KokiriError.message("Catalog directory is unavailable or contains a symbolic link.") }
        }
        let fd = openat(parent, parts.last!, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        Darwin.close(parent)
        guard fd >= 0 else { throw KokiriError.message("Catalog local input is unavailable.") }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_size >= 0, info.st_size <= limit else {
            Darwin.close(fd); throw KokiriError.message("Catalog local input exceeds limits or is not a regular file.")
        }
        return (fd, info)
    }
    private static func unchanged(_ fd: Int32, _ before: stat, _ count: Int) throws {
        var after = stat()
        try CatalogWire.require(fstat(fd, &after) == 0 && count == before.st_size && before.st_ino == after.st_ino && before.st_size == after.st_size && before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec, "Catalog local input changed while reading.")
    }
    static func read(_ url: URL, limit: Int) throws -> Data {
        var bytesRead = 0
        return try read(url, limit: limit, bytesRead: &bytesRead)
    }
    static func read(_ url: URL, limit: Int, bytesRead: inout Int) throws -> Data {
        let (fd, before) = try open(url, limit: limit)
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true); defer { try? handle.close() }
        var data = Data()
        while data.count < before.st_size {
            let part = try handle.read(upToCount: min(65536, Int(before.st_size) - data.count)) ?? Data()
            if part.isEmpty { break }
            data.append(part)
            bytesRead += part.count
            try CatalogWire.require(data.count <= limit, "Catalog local input grew beyond its bound.")
        }
        try unchanged(fd, before, data.count)
        return data
    }
    static func hash(_ url: URL, limit: Int) throws -> (hash: String, bytes: Int) {
        var bytesRead = 0
        return try hash(url, limit: limit, bytesRead: &bytesRead)
    }
    static func hash(_ url: URL, limit: Int, bytesRead: inout Int) throws -> (hash: String, bytes: Int) {
        let (fd, before) = try open(url, limit: limit)
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true); defer { try? handle.close() }
        var digest = SHA256(), count = 0
        while count < before.st_size {
            let part = try handle.read(upToCount: min(65536, Int(before.st_size) - count)) ?? Data()
            if part.isEmpty { break }
            count += part.count
            bytesRead += part.count
            try CatalogWire.require(count <= limit, "Catalog local input grew beyond its bound.")
            digest.update(data: part)
        }
        try unchanged(fd, before, count)
        return (digest.finalize().map { String(format: "%02x", $0) }.joined(), count)
    }
}

public struct CatalogWarmPlan: Sendable {
    public let file: URL
    public let sha256: String
    public let selected: Int
    public let skipped: Int
    public let deferred: Int
    let localProofBytes: Int
    let variantProofChecks: Int

    /// Validates signed metadata again and admits only locally present, scoped
    /// ordinary render/compute variants. No source, binary, profile or normal
    /// warm list is written. Actual device/options validation stays in renderer.
    public static func prepare(index: URL, identity: CatalogRuntimeIdentity, trustedKeys: [String: Data], minimumRevision: Int,
                               output: URL) throws -> Self? {
        let value = try CatalogWire.object(CatalogWire.parse(CatalogLocalFile.read(index, limit: 1024 * 1024), limit: 1024 * 1024), ["protocol", "context_id", "signed_manifest", "pack_files"])
        let signed = try CatalogWire.object(value["signed_manifest"], ["manifest", "key_id", "signature"])
        guard let keyID = signed["key_id"] as? String, let key = trustedKeys[keyID],
              let signatureText = signed["signature"] as? String, let signature = Data(base64Encoded: signatureText), signature.count == 64 else { throw KokiriError.message("Warm-plan catalog signing key is not trusted.") }
        let manifest = try CatalogWire.object(signed["manifest"], ["protocol", "context", "context_id", "compatibility", "dataset_license", "attribution", "revision", "packs", "record_count"])
        try CatalogWire.require(try Curve25519.Signing.PublicKey(rawRepresentation: key).isValidSignature(signature, for: CatalogWire.canonical(manifest)), "Warm-plan catalog signature is invalid.")
        let context = try CatalogWire.context(manifest["context"])
        try CatalogWire.require(try CatalogWire.canonical(context) == identity.context && manifest["compatibility"] as? String == "exact" && manifest["dataset_license"] as? String == "MIT", "Warm-plan catalog context is incompatible.")
        try CatalogWire.require(manifest["protocol"] as? String == CatalogWire.version && value["protocol"] as? String == CatalogWire.version && manifest["context_id"] as? String == identity.contextID && value["context_id"] as? String == identity.contextID, "Warm-plan catalog identity mismatch.")
        guard let revision = CatalogWire.integer(manifest["revision"]), revision >= max(1, minimumRevision),
              let count = CatalogWire.integer(manifest["record_count"]), (0...100000).contains(count),
              let parts = manifest["packs"] as? [[String: Any]], parts.count <= 1024,
              let references = value["pack_files"] as? [[String: Any]], references.count == parts.count else { throw KokiriError.message("Warm-plan catalog exceeds limits or went backwards.") }
        guard let attribution = manifest["attribution"] as? [[String: Any]], (1...8).contains(attribution.count) else { throw KokiriError.message("Warm-plan catalog attribution is invalid.") }
        for item in attribution {
            _ = try CatalogWire.object(item, ["name", "source_url", "source_commit", "license"])
            try CatalogWire.require((item["name"] as? String).map { CatalogWire.matches($0, "[A-Za-z0-9 ._-]{1,100}") } == true &&
                item["license"] as? String == "MIT" && (item["source_url"] as? String).map { CatalogWire.matches($0, "https://[A-Za-z0-9./_-]{1,200}") } == true &&
                (item["source_commit"] as? String).map { CatalogWire.matches($0, "[a-f0-9]{40}") } == true, "Warm-plan catalog attribution is invalid.")
        }
        var rows: [String] = [], proofs: [String: Any] = [:], seen = Set<String>(), recordIDs = Set<String>(), packIDs = Set<String>()
        var verifiedVariants: [String: [String: Any]] = [:], rejectedVariants = Set<String>()
        var totalRecords = 0, totalPackBytes = 0, proofBytes = 0, proofChecks = 0, planBytes = 16384, skipped = 0, deferred = 0
        let cache = index.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("packs")
        for (part, reference) in zip(parts, references) {
            _ = try CatalogWire.object(part, ["sha256", "bytes", "record_count"])
            _ = try CatalogWire.object(reference, ["sha256", "bytes", "record_count", "relative_path"])
            guard let hash = part["sha256"] as? String, CatalogWire.matches(hash, "[a-f0-9]{64}"), packIDs.insert(hash).inserted,
                  let bytes = CatalogWire.integer(part["bytes"]), (1...262144).contains(bytes),
                  let records = CatalogWire.integer(part["record_count"]), (1...128).contains(records),
                  reference["sha256"] as? String == hash, CatalogWire.integer(reference["bytes"]) == bytes,
                  CatalogWire.integer(reference["record_count"]) == records, reference["relative_path"] as? String == "../packs/" + hash + ".json" else { throw KokiriError.message("Warm-plan pack reference mismatch.") }
            totalPackBytes += bytes; totalRecords += records
            try CatalogWire.require(totalPackBytes <= 64 * 1024 * 1024 && totalRecords <= 100000, "Warm-plan input exceeds limits.")
            let data = try CatalogLocalFile.read(cache.appendingPathComponent(hash + ".json"), limit: bytes)
            try CatalogWire.require(data.count == bytes && CatalogWire.hash(data) == hash, "Warm-plan pack hash changed.")
            try autoreleasepool {
                let pack = try CatalogWire.object(CatalogWire.parse(data, limit: bytes), ["protocol", "context_id", "records"])
                guard pack["protocol"] as? String == CatalogWire.version, pack["context_id"] as? String == identity.contextID,
                      let entries = pack["records"] as? [Any], entries.count == records else { throw KokiriError.message("Warm-plan pack context/count changed.") }
                for entry in entries {
                    let record = try CatalogWire.record(entry)
                    try CatalogWire.require(recordIDs.insert(record["id"] as! String).inserted, "Duplicate warm-plan catalog record.")
                    guard let recipe = try Self.recipe(record["row"] as! String) else { skipped += 1; continue }
                    if seen.contains(recipe.row) { continue }
                    if rows.count >= 512 || planBytes + recipe.row.utf8.count * 2 + 1024 > 1024 * 1024 { deferred += 1; continue }
                    var additional: [String: Any] = [:], available = true, bounded = false
                    for (name, stage) in recipe.variants where proofs[name] == nil {
                        let memoKey = name + ":" + String(stage)
                        if let proof = verifiedVariants[memoKey] { additional[name] = proof; continue }
                        if rejectedVariants.contains(memoKey) { available = false; break }
                        guard proofBytes < 64 * 1024 * 1024, verifiedVariants.count + rejectedVariants.count < 1024 else {
                            available = false; bounded = true; break
                        }
                        var bytesRead = 0
                        proofChecks += 1
                        do {
                            defer { proofBytes += bytesRead }
                            let reflection = try CatalogLocalFile.read(identity.variants.appendingPathComponent(name + ".json"), limit: min(1024 * 1024, 64 * 1024 * 1024 - proofBytes), bytesRead: &bytesRead)
                            guard let reflected = try CatalogWire.parse(reflection, limit: 1024 * 1024) as? [String: Any],
                                  reflected["key"] as? String == name, reflected["chain"] as? String == context["shader_chain"] as? String,
                                  reflected["stage"] as? String == (stage == 0 ? "vs" : stage == 1 ? "ps" : "cs"), reflected["mesh_stage"] == nil else { rejectedVariants.insert(memoKey); available = false; break }
                            let source = try CatalogLocalFile.hash(identity.variants.appendingPathComponent(name + ".metal"), limit: 64 * 1024 * 1024 - proofBytes - bytesRead, bytesRead: &bytesRead)
                            let proof: [String: Any] = ["stage":stage, "source_sha256":source.hash, "reflection_sha256":CatalogWire.hash(reflection)]
                            verifiedVariants[memoKey] = proof; additional[name] = proof
                        } catch { rejectedVariants.insert(memoKey); available = false; break }
                    }
                    if !available { if bounded { deferred += 1 } else { skipped += 1 }; continue }
                    for (name, stage) in recipe.variants {
                        let proof = (proofs[name] ?? additional[name]) as? [String: Any]
                        try CatalogWire.require(CatalogWire.integer(proof?["stage"]) == stage, "A variant was assigned conflicting shader stages.")
                    }
                    additional.forEach { proofs[$0.key] = $0.value }
                    if let render = recipe.render { proofs[recipe.row.components(separatedBy: "\t")[1]] = render }
                    seen.insert(recipe.row); rows.append(recipe.row); planBytes += recipe.row.utf8.count * 2 + 1024
                }
            }
        }
        try CatalogWire.require(totalRecords == count, "Warm-plan catalog total changed.")
        guard !rows.isEmpty else { return nil }
        let handoff = try CatalogWire.canonical(["schema":"kokiri-catalog-handoff/1", "context":context, "runtime_sha256":identity.runtimeHash,
            "catalog_revision":revision, "rows":rows, "variants":proofs])
        try CatalogWire.require(handoff.count <= 1024 * 1024, "Warm plan exceeds its retained-byte bound.")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true, attributes: [.posixPermissions:0o700])
        try CatalogWire.require(output.path == CatalogLocalFile.realPath(output), "Warm-plan output cannot be a symbolic link.")
        let file = output.appendingPathComponent("catalog-handoff-" + UUID().uuidString + ".json")
        try handoff.write(to: file, options: .withoutOverwriting)
        try FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath: file.path)
        return Self(file: file, sha256: CatalogWire.hash(handoff), selected: rows.count, skipped: skipped, deferred: deferred,
                    localProofBytes: proofBytes, variantProofChecks: proofChecks)
    }

    static func recipe(_ text: String) throws -> (row: String, variants: [(String, Int)], render: [String: String]?)? {
        let f = text.components(separatedBy: "\t")
        guard f[0] == "C" || f[0] == "R" else { return nil }
        try CatalogWire.row(kind: f[0], text: text)
        if f[0] == "C" { return ("C\t" + f[1], [(f[1], 5)], nil) }
        guard f[0] == "R" else { return nil }
        var bytes: [UInt8] = []
        func hex(_ value: String) -> [UInt8] {
            let input = Array(value.utf8); var output: [UInt8] = []
            for at in stride(from: 0, to: input.count, by: 2) { output.append(UInt8(String(bytes:input[at..<at+2], encoding:.ascii)!, radix:16)!) }
            return output
        }
        if CatalogWire.matches(f[1], "[a-f0-9]{1088}") { bytes = hex(f[1]) }
        else {
            let packed = f[1].components(separatedBy: ":")
            for name in packed.prefix(2) { bytes += Array(name.utf8) + [UInt8](repeating:0, count:80-name.utf8.count) }
            let regex = try NSRegularExpression(pattern:"z([a-f0-9]+)\\.|[a-f0-9]{2}"), input = packed[2] as NSString
            for token in regex.matches(in: packed[2], range:NSRange(location:0, length:input.length)) {
                if token.range(at:1).location == NSNotFound { bytes += hex(input.substring(with:token.range)) }
                else { bytes += [UInt8](repeating:0, count:Int(input.substring(with:token.range(at:1)), radix:16)!) }
            }
        }
        guard bytes.count == 544, bytes[200..<216].allSatisfy({$0 == 0}), bytes[536..<544].allSatisfy({$0 == 0}),
              bytes[160] == 0, bytes[162] == 0, bytes[163] == 0,
              bytes[268] & ~1 == 0, bytes[269..<272].allSatisfy({$0 == 0}) else { return nil }
        func name(_ at: Int) -> String? {
            let field = Array(bytes[at..<at+80]), end = field.firstIndex(of:0) ?? 80
            guard field[end...].allSatisfy({$0 == 0}), let value = String(bytes:field[..<end], encoding:.ascii),
                  value.isEmpty || CatalogWire.matches(value, "[a-f0-9]{64}-[a-f0-9]{12}_b") else { return nil }
            return value
        }
        guard let vs = name(0), !vs.isEmpty, let fs = name(80), fs.isEmpty || bytes[161] == 1 else { return nil }
        let key = bytes.map { String(format:"%02x",$0) }.joined()
        return ("R\t" + key, fs.isEmpty ? [(vs,0)] : [(vs,0),(fs,1)], ["vs":vs,"fs":fs])
    }
}
