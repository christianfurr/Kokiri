import Charts
import SwiftUI
import KokiriCore

struct PerformanceView: View {
    @EnvironmentObject private var model: AppModel
    private func number(_ value: Double?, decimals: Int = 1) -> String {
        value.map { String(format: "%.*f", decimals, $0) } ?? "—"
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .top) {
                    PageHeading(eyebrow: "Your session", title: "Performance", detail: "Real observations from your game. Generated frames are excluded from the game frame rate.")
                    Button("Open Recording…", action: model.chooseRecording).disabled(model.running || model.busy)
                }
                sourceBanner
                HStack(spacing: 14) {
                    MetricCard(label: "Observed game rate", value: number(model.snapshot.observedFPS), unit: "FPS", detail: model.running ? "Recent game presentations" : "Last session’s presentations")
                    MetricCard(label: "Latest frame interval", value: number(model.snapshot.metrics["@frame_ms"]), unit: "ms", detail: "Game frame timing sample")
                    MetricCard(label: "Physical footprint", value: number(model.snapshot.footprint.map { Double($0) / 1_073_741_824 }, decimals: 2), unit: "GiB", detail: "Process physical footprint · not VRAM")
                }
                Surface {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack {
                            Text("Frame times").font(.system(size: 15, weight: .semibold))
                            Spacer()
                            Label("16.7 ms ≈ 60 FPS", systemImage: "line.diagonal").font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                        if model.snapshot.frames.isEmpty {
                            ContentUnavailableView("No detailed timing samples", systemImage: "waveform.path", description: Text("Open a recording, or enable detailed timing in Settings for the next launch.")).frame(height: 190)
                        } else {
                            Chart(model.snapshot.frames) { point in
                                AreaMark(x: .value("Frame", point.frame), y: .value("Interval", point.milliseconds)).foregroundStyle(Palette.moss.opacity(0.12))
                                LineMark(x: .value("Frame", point.frame), y: .value("Interval", point.milliseconds)).foregroundStyle(Palette.forest).lineStyle(StrokeStyle(lineWidth: 1.5))
                                RuleMark(y: .value("60 FPS interval", 1000.0 / 60)).foregroundStyle(Palette.brass).lineStyle(StrokeStyle(lineWidth: 1, dash: [4,4]))
                            }.chartXScale(domain: frameDomain).chartYAxisLabel("milliseconds").chartXAxisLabel("game frame").frame(height: 205)
                        }
                        Text("The most recent \(model.snapshot.frames.count) available samples. Late or duplicate callbacks can affect a live rate; a recording is not a certified benchmark.")
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                }
                HStack(alignment: .top, spacing: 16) {
                    Surface {
                        VStack(alignment: .leading, spacing: 12) {
                            Eyebrow(text: "Reported location")
                            Text(model.snapshot.area.map(friendlyArea) ?? "Not available").font(.system(size: 21, weight: .medium, design: .serif))
                            if let position = model.snapshot.position {
                                Text(position.map { String(format: "%.2f", $0) }.joined(separator: "   "))
                                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                            }
                            Text("Location is sampled while the game responds.").font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                    }
                    Surface {
                        VStack(alignment: .leading, spacing: 11) {
                            Eyebrow(text: "GPU timing")
                            DetailRow(title: "First-to-last span", value: number(model.snapshot.gpuSpan) + " ms")
                            DetailRow(title: "Command-buffer sum", value: number(model.snapshot.metrics["@gpu_ms"]) + " ms")
                            Text("GPU intervals can include waits and overlapping work.").font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                    }
                }
            }.padding(32)
        }
    }
    private var frameDomain: ClosedRange<Int> {
        let first = model.snapshot.frames.first?.frame ?? 0
        return first...max(first + 1, model.snapshot.frames.last?.frame ?? 1)
    }
    private var sourceBanner: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: model.recording == nil ? "dot.radiowaves.left.and.right" : "clock.arrow.circlepath").foregroundStyle(Palette.brass)
            VStack(alignment: .leading, spacing: 4) {
                if let recording = model.recording {
                    Text("RECORDED SESSION · " + recordingDate(recording.date)).font(.system(size: 10, weight: .semibold)).tracking(1)
                    Text(recording.folder.lastPathComponent).font(.system(size: 11)).foregroundStyle(.secondary)
                    if let build = recording.build { Text("Build " + String(build.prefix(16))).font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary) }
                } else {
                    Text(model.running ? model.isStale ? "SESSION OPEN · NO FRESH FRAME TIMING" : "LIVE OBSERVATION" : model.sessionFolder != nil ? "LAST LOCAL SESSION · CLOSED" : "NO LIVE SESSION").font(.system(size: 10, weight: .semibold)).tracking(1)
                    Text(model.running ? "Observing only the game launched by Kokiri." : model.sessionFolder?.lastPathComponent ?? "Connect your game in Setup, or open a dated recording.").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if let folder = model.recording?.folder ?? model.sessionFolder { Button("Show Files") { model.reveal(folder) } }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.brass.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
    }
    private func friendlyArea(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: "([a-z])([A-Z])", with: "$1 $2", options: .regularExpression)
    }
    private func recordingDate(_ date: Date) -> String {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0); formatter.dateFormat = "MMM d, yyyy 'at' HH:mm 'UTC'"
        return formatter.string(from: date)
    }
}
