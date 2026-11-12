import CoreImage
import Foundation
import ImageIO
import UniformTypeIdentifiers

let argomenti = CommandLine.arguments
let lineare = CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!
let p3 = CGColorSpace(name: CGColorSpace.displayP3)!
let contesto = CIContext(options: [.workingColorSpace: lineare])
let tipi: [(String, CFString)] = [
    ("mappa_hdr", kCGImageAuxiliaryDataTypeHDRGainMap),
    ("mappa_iso", kCGImageAuxiliaryDataTypeISOGainMap),
    ("disparita", kCGImageAuxiliaryDataTypeDisparity),
    ("profondita", kCGImageAuxiliaryDataTypeDepth),
]

func muori(_ testo: String) -> Never {
    FileHandle.standardError.write((testo + "\n").data(using: .utf8)!)
    exit(2)
}

func matrice(_ per: CGFloat, _ piu: CGFloat = 0) -> [String: Any] {
    return ["inputRVector": CIVector(x: per, y: 0, z: 0, w: 0),
            "inputGVector": CIVector(x: 0, y: per, z: 0, w: 0),
            "inputBVector": CIVector(x: 0, y: 0, z: per, w: 0),
            "inputAVector": CIVector(x: 0, y: 0, z: 0, w: 0),
            "inputBiasVector": CIVector(x: piu, y: piu, z: piu, w: 1)]
}

func variante(_ foto: CIImage, _ nome: String) -> CIImage {
    switch nome {
    case "buio":
        return foto.applyingFilter("CIExposureAdjust", parameters: ["inputEV": -3.0])
    case "rumore":
        let rumore = CIFilter(name: "CIRandomGenerator")!.outputImage!
            .cropped(to: foto.extent).applyingFilter("CIColorMatrix",
                                                     parameters: matrice(0.3, -0.15))
        return rumore.applyingFilter("CIAdditionCompositing",
                                     parameters: [kCIInputBackgroundImageKey: foto])
            .cropped(to: foto.extent)
    case "compresso":
        let opzioni = [CIImageRepresentationOption(
            rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.05]
        guard let dati = contesto.jpegRepresentation(of: foto, colorSpace: p3,
                                                     options: opzioni),
              let rifatta = CIImage(data: dati) else { muori("jpeg") }
        return rifatta
    default:
        return foto
    }
}

func mappa(_ url: URL) -> String? {
    guard let fonte = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    if CGImageSourceCopyAuxiliaryDataInfoAtIndex(
        fonte, 0, kCGImageAuxiliaryDataTypeISOGainMap) != nil {
        return "iso"
    }
    if CGImageSourceCopyAuxiliaryDataInfoAtIndex(
        fonte, 0, kCGImageAuxiliaryDataTypeHDRGainMap) != nil {
        return "apple"
    }
    return nil
}

func scriviCI(_ sdr: CIImage, _ verso: URL, _ opzioni: [CIImageRepresentationOption: Any]) {
    do {
        try contesto.writeHEIFRepresentation(of: sdr, to: verso, format: .RGBA8,
                                             colorSpace: p3, options: opzioni)
    } catch {
        muori("heif: \(error)")
    }
}

func scriviISO(_ hdr: CIImage, _ verso: URL) {
    let spazio = CGColorSpace(name: CGColorSpace.extendedLinearDisplayP3)!
    let fatta = contesto.createCGImage(hdr, from: hdr.extent, format: .RGBAh,
                                       colorSpace: spazio)
        ?? contesto.createCGImage(hdr, from: hdr.extent, format: .RGBAf,
                                  colorSpace: spazio)
    guard let immagine = fatta else {
        muori("iso: niente immagine HDR da \(hdr.extent)")
    }
    guard let destino = CGImageDestinationCreateWithURL(
        verso as CFURL, "public.heic" as CFString, 1, nil) else {
        muori("iso: niente destinazione per \(verso.path)")
    }
    let opzioni: [CFString: Any] = [
        kCGImageDestinationEncodeRequest: kCGImageDestinationEncodeToISOGainmap]
    CGImageDestinationAddImage(destino, immagine, opzioni as CFDictionary)
    if !CGImageDestinationFinalize(destino) {
        muori("iso non scritta")
    }
}

func luce(_ url: URL) -> Double {
    guard let piatta = CIImage(contentsOf: url) else { return -1 }
    let senza = massimoDi(piatta)
    return senza > 0 ? massimo(url) / senza : -1
}

func scrivi(_ sorgente: URL, _ uscita: URL, _ nome: String) {
    guard let base = CIImage(contentsOf: sorgente) else { muori("non apro \(sorgente)") }
    let sdr = variante(base, nome)
    let hdr = sdr.applyingFilter("CIColorMatrix", parameters: matrice(3.0))
    let profondita = CIFilter(name: "CILinearGradient", parameters: [
        "inputPoint0": CIVector(x: 0, y: 0),
        "inputPoint1": CIVector(x: sdr.extent.width, y: sdr.extent.height),
        "inputColor0": CIColor(red: 0.1, green: 0.1, blue: 0.1),
        "inputColor1": CIColor(red: 0.9, green: 0.9, blue: 0.9),
    ])!.outputImage!.cropped(to: sdr.extent)
        .transformed(by: CGAffineTransform(scaleX: 0.25, y: 0.25))
    if nome == "iso" {
        scriviISO(hdr, uscita)
        FileHandle.standardError.write("mappa \(nome): \(mappa(uscita) ?? "nessuna")\n"
            .data(using: .utf8)!)
        return
    }
    var opzioni: [CIImageRepresentationOption: Any] = [.hdrImage: hdr]
    if nome != "senza_profondita" {
        opzioni[.disparityImage] = profondita
    }
    let piatta = uscita.deletingPathExtension().appendingPathExtension("piatta.heic")
    let verso = nome == "girata" ? piatta : uscita
    scriviCI(sdr, verso, opzioni)
    var modo = "hdrImage"
    if mappa(verso) == nil {
        opzioni.removeValue(forKey: .hdrImage)
        opzioni[.hdrGainMapImage] = sdr.applyingFilter("CIPhotoEffectNoir")
        scriviCI(sdr, verso, opzioni)
        modo = "hdrGainMapImage"
    }
    FileHandle.standardError.write("mappa \(nome): \(mappa(verso) ?? "nessuna") (\(modo))\n"
        .data(using: .utf8)!)
    if nome == "girata" {
        gira(piatta, uscita)
    }
}

func gira(_ piatta: URL, _ uscita: URL) {
    guard let fonte = CGImageSourceCreateWithURL(piatta as CFURL, nil),
          let destino = CGImageDestinationCreateWithURL(
              uscita as CFURL, UTType.heic.identifier as CFString, 1, nil) else {
        muori("girata")
    }
    CGImageDestinationAddImageFromSource(
        destino, fonte, 0, [kCGImagePropertyOrientation: 6] as CFDictionary)
    for (_, tipo) in tipi {
        if let dentro = CGImageSourceCopyAuxiliaryDataInfoAtIndex(fonte, 0, tipo) {
            CGImageDestinationAddAuxiliaryDataInfo(destino, tipo, dentro)
        }
    }
    if !CGImageDestinationFinalize(destino) {
        muori("girata non scritta")
    }
}

func ausiliaria(_ fonte: CGImageSource, _ tipo: CFString) -> [String: Any]? {
    guard let dentro = CGImageSourceCopyAuxiliaryDataInfoAtIndex(fonte, 0, tipo)
            as? [String: Any] else { return nil }
    var uscita: [String: Any] = [:]
    if let dati = dentro[kCGImageAuxiliaryDataInfoData as String] as? Data {
        uscita["byte"] = dati.count
        uscita["dati"] = dati
    }
    if let descrizione = dentro[kCGImageAuxiliaryDataInfoDataDescription as String]
        as? [String: Any] {
        uscita["larghezza"] = descrizione["Width"] ?? 0
        uscita["altezza"] = descrizione["Height"] ?? 0
    }
    if let meta = dentro[kCGImageAuxiliaryDataInfoMetadata as String] {
        let xmp = CGImageMetadataCreateXMPData(meta as! CGImageMetadata, nil)
        uscita["meta"] = (xmp as Data?) ?? Data()
    }
    return uscita
}

func massimo(_ url: URL) -> Double {
    guard let foto = CIImage(contentsOf: url, options: [.expandToHDR: true]) else {
        return -1
    }
    return massimoDi(foto)
}

func massimoDi(_ foto: CIImage) -> Double {
    let area = foto.applyingFilter("CIAreaMaximum", parameters: [
        kCIInputExtentKey: CIVector(cgRect: foto.extent)])
    var punto = [Float](repeating: 0, count: 4)
    contesto.render(area, toBitmap: &punto, rowBytes: 16,
                    bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
                    format: .RGBAf, colorSpace: lineare)
    return Double(max(punto[0], punto[1], punto[2]))
}

func misure(_ fonte: CGImageSource) -> [String: Any] {
    let dentro = CGImageSourceCopyPropertiesAtIndex(fonte, 0, nil) as? [String: Any] ?? [:]
    let larga = dentro[kCGImagePropertyPixelWidth as String] as? Int ?? 0
    let alta = dentro[kCGImagePropertyPixelHeight as String] as? Int ?? 0
    let verso = dentro[kCGImagePropertyOrientation as String] as? Int ?? 1
    let girata = [5, 6, 7, 8].contains(verso)
    return ["larghezza": girata ? alta : larga, "altezza": girata ? larga : alta,
            "verso": verso]
}

func guarda(_ originale: URL, _ migliorata: URL) -> [String: Any] {
    guard let prima = CGImageSourceCreateWithURL(originale as CFURL, nil),
          let dopo = CGImageSourceCreateWithURL(migliorata as CFURL, nil) else {
        return ["errore": "non si apre"]
    }
    var esito: [String: Any] = ["prima": misure(prima), "dopo": misure(dopo),
                                "massimo_prima": massimo(originale),
                                "massimo_dopo": massimo(migliorata),
                                "luce_prima": luce(originale), "luce_dopo": luce(migliorata)]
    for (nome, tipo) in tipi {
        let vecchia = ausiliaria(prima, tipo)
        let nuova = ausiliaria(dopo, tipo)
        var riga: [String: Any] = ["prima": vecchia != nil, "dopo": nuova != nil]
        if let vecchia = vecchia, let nuova = nuova {
            riga["dati_uguali"] = (vecchia["dati"] as? Data) == (nuova["dati"] as? Data)
            riga["meta_uguali"] = (vecchia["meta"] as? Data) == (nuova["meta"] as? Data)
            riga["larghezza"] = nuova["larghezza"]
            riga["altezza"] = nuova["altezza"]
        }
        esito[nome] = riga
    }
    return esito
}

func bit(_ url: URL) -> [String: Any] {
    guard let fonte = CGImageSourceCreateWithURL(url as CFURL, nil),
          let dentro = CGImageSourceCopyPropertiesAtIndex(fonte, 0, nil) as? [String: Any]
    else { return ["errore": "non si apre"] }
    return ["bit": dentro[kCGImagePropertyDepth as String] as? Int ?? 0,
            "profilo": dentro[kCGImagePropertyProfileName as String] as? String ?? ""]
}

if argomenti.count == 3 && argomenti[1] == "bit" {
    let dati = try! JSONSerialization.data(
        withJSONObject: bit(URL(fileURLWithPath: argomenti[2])), options: [.sortedKeys])
    FileHandle.standardOutput.write(dati)
    exit(0)
}
guard argomenti.count >= 4 else { muori("uso: fai|guarda A B [variante] | bit A") }
let primo = URL(fileURLWithPath: argomenti[2])
let secondo = URL(fileURLWithPath: argomenti[3])
switch argomenti[1] {
case "fai":
    scrivi(primo, secondo, argomenti.count > 4 ? argomenti[4] : "normale")
case "guarda":
    let dati = try! JSONSerialization.data(withJSONObject: guarda(primo, secondo),
                                           options: [.sortedKeys])
    FileHandle.standardOutput.write(dati)
default:
    muori("non so fare \(argomenti[1])")
}
