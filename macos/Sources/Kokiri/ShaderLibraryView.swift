import SwiftUI
import KokiriCore

struct ShaderLibraryView: View {
    @EnvironmentObject private var model: AppModel
    private let kinds = [("R", "Render"), ("T", "Tessellation"), ("C", "Compute"), ("M", "Mesh"), ("S", "Shader variants")]
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .top) {
                    PageHeading(eyebrow: "Your game’s shaders", title: "Shader Library", detail: "See what is prepared, what you have collected, and what is available in the public library.")
                    Button("Refresh", action: model.refreshLibrary).disabled(model.shaderRefreshPending || model.catalog.downloadPending)
                    Button("Refresh", action: model.refreshLibrary).disabled(model.shaderRefreshPending || model.catalog.downloadPending)
                    Button { model.refreshShaders(); model.catalog.retryDownload() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                        .disabled(model.shaderRefreshPending || model.catalog.downloadPending)
                }
                HStack(spacing: 14) {
                    MetricCard(label: "Compiled libraries", value: model.preparation.map { $0.libraries.formatted() } ?? "—", unit: "", detail: "Prepared for this game build")
                    MetricCard(label: "Prepared pipelines", value: model.preparation.map { $0.pipelines.formatted() } ?? "—", unit: "", detail: model.preparation.map { "\($0.meshPipelines.formatted()) mesh pipelines included" } ?? "No complete receipt found")
                    MetricCard(label: "Collected locally", value: model.shaderRefreshPending ? "—" : model.collectedRecipeCount.formatted(), unit: "", detail: "Metadata discovered during play")
                }
                Surface {
                    VStack(alignment: .leading, spacing: 15) {
                        HStack {
                            Label("Public library", systemImage: "network").font(.headline)
                            StatusPill(text: model.catalog.downloadPending ? "Checking…" : model.catalog.referenceIndex != nil || model.catalog.verifiedIndex != nil ? "Verified" : model.catalog.configured ? "Connected" : "Not connected", symbol: "checkmark.shield")
                        }
                        if let count = model.catalog.reviewedRecords, count > 0 {
                            Text("\(count.formatted()) shared recipes").font(.system(size: 25, weight: .medium, design: .rounded)).monospacedDigit()
                        }
                        Text(model.catalog.downloadStatus).font(.callout).foregroundStyle(.secondary)
                        Text("The public library contains pipeline recipes, not game files or compiled Metal shaders. Downloads are signature-checked and kept separate from your game’s cache.")
                            .font(.caption).foregroundStyle(.secondary)
                        HStack {
                            if let origin = model.catalog.origin { Link("Open Public Library", destination: origin) }
                            if let url = model.catalog.protocolURL { Link("View Protocol", destination: url) }
                            if let file = model.catalog.referenceIndex ?? model.catalog.verifiedIndex { Button("Show Downloaded Metadata") { model.reveal(file) } }
                        }
                    }
                }
                Surface {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Pipeline metadata on this Mac").font(.headline)
                        if model.shaderRefreshPending {
                            ProgressView("Reading local metadata…").controlSize(.small)
                        } else if model.shaderCounts.isEmpty {
                            Text("Connect a prepared game to see its metadata.").foregroundStyle(.secondary)
                        } else {
                            HStack { Text("Recipe type"); Spacer(); Text("Bundled").frame(width: 95, alignment: .trailing); Text("Collected").frame(width: 95, alignment: .trailing) }.font(.caption).foregroundStyle(.secondary)
                            ForEach(kinds, id: \.0) { kind in
                                HStack {
                                    Text(kind.1)
                                    Spacer()
                                    Spacer()
                                    Text(model.shaderCounts[kind.0, default: 0].formatted()).frame(width: 95, alignment: .trailing)
                                    Text(model.collectedShaderCounts[kind.0, default: 0].formatted()).frame(width: 95, alignment: .trailing)
                                }.font(.callout).monospacedDigit()
                            }
                            Text("These are recipe records. Compiled-library and prepared-pipeline totals are shown separately above.").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Surface {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Your discoveries", systemImage: "externaldrive").font(.headline)
                        Text(model.catalog.status).font(.callout).foregroundStyle(.secondary)
                        if model.catalog.allowsContributions {
                            HStack {
                                Button("Share Reviewed Metadata") { model.setContribution(true) }
                                Button("Keep Local") { model.setContribution(false) }
                            }.disabled(!model.catalog.ready || model.catalog.choicePending)
                        }
                        Text("Saves, logs, shader source and personal paths stay private.").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }.padding(32).frame(maxWidth: 1140)
        }
    }
}
