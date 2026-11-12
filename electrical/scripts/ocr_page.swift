import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count >= 2 else {
    fputs("usage: ocr_page <image>\n", stderr)
    exit(2)
}

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: url),
      let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cgImage = bitmap.cgImage
else {
    fputs("cannot read image\n", stderr)
    exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
request.recognitionLanguages = ["zh-Hans", "en-US"]

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("vision failed: \(error)\n", stderr)
    exit(1)
}

struct Piece {
    let y: CGFloat
    let x: CGFloat
    let text: String
}

var pieces: [Piece] = []
for observation in request.results ?? [] {
    guard let text = observation.topCandidates(1).first?.string else { continue }
    let box = observation.boundingBox
    let yTop = 1 - (box.origin.y + box.height / 2)
    let clean = text
        .replacingOccurrences(of: "\t", with: " ")
        .replacingOccurrences(of: "\n", with: " ")
        .trimmingCharacters(in: .whitespacesAndNewlines)
    if clean.isEmpty { continue }
    pieces.append(Piece(y: yTop, x: box.origin.x, text: clean))
}

pieces.sort { a, b in
    if abs(a.y - b.y) > 0.02 { return a.y < b.y }
    return a.x < b.x
}

for piece in pieces {
    let y = String(format: "%.4f", Double(piece.y))
    let x = String(format: "%.4f", Double(piece.x))
    print(y + "\t" + x + "\t" + piece.text)
}
