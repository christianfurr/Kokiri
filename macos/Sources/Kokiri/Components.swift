import SwiftUI
import AppKit

enum Palette {
    static let paper = Color(red: 0.97, green: 0.96, blue: 0.93)
    static let forest = Color(red: 0.13, green: 0.30, blue: 0.23)
    static let ink = Color(red: 0.13, green: 0.20, blue: 0.17)
    static let moss = Color(red: 0.41, green: 0.51, blue: 0.34)
    static let brass = Color(red: 0.66, green: 0.51, blue: 0.26)
    static let line = Color(red: 0.84, green: 0.86, blue: 0.80)
}
struct KokiriMark: View {
    var size: CGFloat = 38
    var body: some View {
        Group {
            if let url = Bundle.main.url(forResource: "KokiriMark", withExtension: "png"), let image = NSImage(contentsOf: url) {
                Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
            } else { Image(systemName: "leaf.circle.fill").resizable().scaledToFit().foregroundStyle(Palette.forest) }
        }.frame(width: size, height: size).accessibilityLabel("Kokiri")
    }
}

struct Eyebrow: View {
    var text: String
    var body: some View { Text(text.uppercased()).font(.system(size: 10, weight: .semibold)).tracking(2).foregroundStyle(Palette.moss) }
}
struct Surface<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content.padding(22).frame(maxWidth: .infinity, alignment: .leading)
            .background(.background, in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Palette.line.opacity(0.65), lineWidth: 1))
    }
}
struct StatusPill: View {
    var text: String
    var symbol = "circle.fill"
    var body: some View {
        Label(text, systemImage: symbol).font(.system(size: 11, weight: .medium))
            .padding(.horizontal, 10).padding(.vertical, 7)
            .foregroundStyle(Palette.forest).background(Palette.forest.opacity(0.08), in: Capsule())
    }
}
struct PageHeading: View {
    var eyebrow: String
    var title: String
    var detail: String
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: eyebrow)
            Text(title).font(.system(size: 32, weight: .semibold, design: .serif)).foregroundStyle(Palette.ink)
            Text(detail).font(.system(size: 13)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
struct MetricCard: View {
    var label: String
    var value: String
    var unit: String
    var detail: String
    var body: some View {
        Surface {
            VStack(alignment: .leading, spacing: 12) {
                Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(value).font(.system(size: 31, weight: .medium, design: .rounded)).monospacedDigit().foregroundStyle(Palette.ink)
                    Text(unit).font(.system(size: 11)).foregroundStyle(Palette.moss)
                }
                Text(detail).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(2)
            }
        }
    }
}
struct DetailRow: View {
    var title: String
    var value: String
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).foregroundStyle(.secondary)
            Spacer(minLength: 14)
            Text(value).multilineTextAlignment(.trailing).textSelection(.enabled)
        }.font(.system(size: 12)).padding(.vertical, 4)
    }
}

/// Original vector artwork. No game artwork or downloaded assets.
struct ForestScene: View {
    var body: some View {
        Canvas { context, size in
            let rect = CGRect(origin: .zero, size: size)
            context.fill(Path(rect), with: .linearGradient(Gradient(colors: [Color(red: 0.88, green: 0.91, blue: 0.81), Color(red: 0.67, green: 0.75, blue: 0.60)]), startPoint: .zero, endPoint: CGPoint(x: size.width, y: size.height)))
            let sun = CGRect(x: size.width * 0.71, y: size.height * 0.13, width: 68, height: 68)
            context.fill(Path(ellipseIn: sun), with: .color(Color(red: 0.98, green: 0.95, blue: 0.78).opacity(0.8)))
            for layer in 0..<4 {
                let base = size.height * (0.46 + Double(layer) * 0.13)
                var hill = Path(); hill.move(to: CGPoint(x: 0, y: base))
                hill.addCurve(to: CGPoint(x: size.width, y: base + 30), control1: CGPoint(x: size.width * 0.4, y: base - 100), control2: CGPoint(x: size.width * 0.65, y: base + 90))
                hill.addLine(to: CGPoint(x: size.width, y: size.height)); hill.addLine(to: CGPoint(x: 0, y: size.height)); hill.closeSubpath()
                context.fill(hill, with: .color(Palette.forest.opacity(0.10 + Double(layer) * 0.12)))
            }
            for index in 0..<19 {
                let x = size.width * Double(index) / 18
                let height = size.height * (0.27 + Double((index * 7) % 11) / 45)
                let y = size.height * 0.97
                var tree = Path(); tree.move(to: CGPoint(x: x, y: y - height))
                tree.addLine(to: CGPoint(x: x - height * 0.21, y: y)); tree.addLine(to: CGPoint(x: x + height * 0.21, y: y)); tree.closeSubpath()
                context.fill(tree, with: .color(Palette.forest.opacity(index % 3 == 0 ? 0.68 : 0.44)))
            }
        }.accessibilityHidden(true)
    }
}
