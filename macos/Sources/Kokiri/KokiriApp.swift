import AppKit
import SwiftUI

enum ProductIdentity {
    static var version: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development" }
    static var build: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unbundled" }
}

@main struct KokiriApp: App {
    @Environment(\.openWindow) private var openWindow
    @NSApplicationDelegateAdaptor(LauncherDelegate.self) private var delegate
    @StateObject private var model = AppModel()
    var body: some Scene {
        Window("KOKIRI", id: "main") {
            Group {
                if model.onboarding {
                    SetupView().frame(width: 600, height: 620)
                } else {
                    MainView().frame(minWidth: 960, minHeight: 680)
                }
            }.environmentObject(model).onAppear { delegate.model = model }
                .tint(Palette.forest)
        }
        .defaultSize(width: 960, height: 680)
        .windowResizability(.contentSize)
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button("Settings…") { model.selection = .settings; openWindow(id: "main"); NSApp.activate() }
                    .keyboardShortcut(",", modifiers: .command)
            }
            CommandGroup(after: .appInfo) {
                UpdateCommand(service: model.updates)
            }
            CommandGroup(after: .newItem) {
                Button("Connect Game…", action: model.chooseInstallation).keyboardShortcut("o").disabled(!model.canManageGame)
                Button("Open Performance Recording…", action: model.chooseRecording).keyboardShortcut("o", modifiers: [.command, .shift])
                Divider()
                Button(model.running ? "Bring Game Forward" : "Play", action: model.play)
                    .keyboardShortcut("r").disabled(model.busy || model.building)
            }
        }

    }
}

private struct UpdateCommand: View {
    @ObservedObject var service: UpdateService
    var body: some View { Button("Check for Updates…", action: service.check).disabled(!service.canCheck) }
}

@MainActor final class LauncherDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard model?.building == true else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "Game preparation is running"
        alert.informativeText = "Keep Kokiri open until preparation finishes. Completed work is saved for reuse if preparation fails."
        alert.addButton(withTitle: "Keep Preparing")
        alert.runModal()
        return .terminateCancel
    }
}
