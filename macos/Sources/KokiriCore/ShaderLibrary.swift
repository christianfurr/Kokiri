import CryptoKit
import Foundation

public struct RuntimePreparation: Sendable {
    public let libraries: Int
    public let pipelines: Int
    public let meshPipelines: Int
    public let referenceContext: Data

    public static func load(app: URL) throws -> Self {
        guard let bundle = Bundle(url: app), bundle.object(forInfoDictionaryKey: "KokiriPrepared") as? Bool == true,
              bundle.object(forInfoDictionaryKey: "KokiriShaders") as? String == "full",
              let rawHash = bundle.object(forInfoDictionaryKey: "KokiriBuildRuntimeSHA256") as? String,
              CatalogWire.matches(rawHash, "[a-f0-9]{64}") else {
            throw KokiriError.message("This game has no complete preparation receipt.")
        }
        let file = app.appendingPathComponent("Contents/Resources/totk/build/game-data/oot/preparation-receipt.json")
        let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true, (values.fileSize ?? Int.max) <= 1 << 20 else {
            throw KokiriError.message("The preparation receipt is unavailable.")
        }
        let data = try Data(contentsOf: file)
        guard CatalogWire.hash(data) == bundle.object(forInfoDictionaryKey: "KokiriPreparationReceiptSHA256") as? String,
              let receipt = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              receipt["schema"] as? String == "kokiri-preparation-receipt-v1",
              receipt["prepared"] as? Bool == true, receipt["mode"] as? String == "full",
              let errors = receipt["errors"] as? [Any], errors.isEmpty,
              let unresolved = receipt["unresolved_inputs"] as? [Any], unresolved.isEmpty,
              let identity = receipt["identity"] as? [String: Any], identity["runtime_sha256"] as? String == rawHash,
              let libraries = receipt["libraries"] as? [String: Any], let pipelines = receipt["pipelines"] as? [String: Any],
              let prepared = CatalogWire.integer(libraries["unique_prepared_files"]), prepared > 0,
              prepared == CatalogWire.integer(libraries["unique_requested_files"]),
              let completed = CatalogWire.integer(pipelines["completed"]), completed > 0,
              completed == CatalogWire.integer(pipelines["requested"]),
              CatalogWire.integer(libraries["failed"]) == 0, CatalogWire.integer(pipelines["failed"]) == 0,
              CatalogWire.integer(pipelines["write_failed"]) == 0, CatalogWire.integer(pipelines["unaccounted"]) == 0,
              let mesh = CatalogWire.integer(pipelines["mesh_requested"]), mesh >= 0, mesh <= completed,
              let indexedMesh = CatalogWire.integer(pipelines["mesh_indexed"]), indexedMesh >= mesh else {
            throw KokiriError.message("The game’s preparation receipt could not be verified.")
        }
        let context: [String: Any] = ["game_id": "oot", "game_version": bundle.object(forInfoDictionaryKey: "KokiriGameUpdate") as? String ?? "",
            "game_content_sha256": identity["source_romfs_sha256"] ?? NSNull(), "recipe_format": "mng-list-v1", "backend": "metal",
            "shader_chain": identity["chain"] ?? "", "translator_sha256": identity["translator_sha256"] ?? NSNull(),
            "compiler_sha256": receipt["compiler_context_sha256"] ?? NSNull(), "target_sha256": NSNull(), "options_sha256": NSNull()]
        return Self(libraries: prepared, pipelines: completed, meshPipelines: mesh,
                    referenceContext: try CatalogWire.canonical(CatalogWire.context(context)))
    }
}

public enum ShaderMetadata {
    /// Metadata counts remain separate from the compiled-library preparation receipt.
    public static func counts(files: [URL]) -> [String: Int] {
        var counts: [String: Int] = [:]
        var seen = Set<String>()
        for file in files {
            guard let size = try? file.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey]),
                  size.isRegularFile == true, size.isSymbolicLink != true, (size.fileSize ?? Int.max) <= 64 << 20,
                  let text = try? String(contentsOf: file, encoding: .utf8) else { continue }
            for row in text.split(separator: "\n") where !row.hasPrefix("#") {
                guard let kind = row.split(separator: "\t").first,
                      ["V", "A", "S", "C", "R", "B", "T", "M"].contains(String(kind)),
                      seen.insert(String(row)).inserted else { continue }
                counts[String(kind), default: 0] += 1
            }
        }
        return counts
    }
}
