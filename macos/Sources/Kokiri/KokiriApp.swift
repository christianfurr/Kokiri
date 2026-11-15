import AppKit
import SwiftUI

enum ProductIdentity {
    static var version: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development" }
    static var build: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unbundled" }
}

@main struct KokiriApp: App {
    @StateObject private var model = AppModel()
    var body: some Scene {
        WindowGroup("KOKIRI") {
            MainView().environmentObject(model)
                .frame(minWidth: 960, minHeight: 680)
                .tint(Palette.forest)
        }
        .defaultSize(width: 1180, height: 800)
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(after: .appInfo) {
                UpdateCommand(service: model.updates)
            }
            CommandGroup(after: .newItem) {
                Button("Connect Game…", action: model.chooseInstallation).keyboardShortcut("o")
                Button("Open Performance Recording…", action: model.chooseRecording).keyboardShortcut("o", modifiers: [.command, .shift])
                Divider()
                Button(model.running ? "Bring Game Forward" : "Play", action: model.play)
                    .keyboardShortcut("r").disabled(model.busy || model.building)
            }
        }
        Settings { SettingsView().environmentObject(model).frame(width: 620, height: 580).tint(Palette.forest) }
    }
}

private struct UpdateCommand: View {
    @ObservedObject var service: UpdateService
    var body: some View { Button("Check for Updates…", action: service.check).disabled(!service.canCheck) }
}
