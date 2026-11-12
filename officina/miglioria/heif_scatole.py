from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass, field, replace
from pathlib import Path

AUSILIARIA = b"auxl"
DESCRIVE = b"cdsc"
DERIVATA = b"dimg"
GRUPPI = b"grpl"
ALTERNATIVE = b"altr"
MAPPA_ISO = b"tmap"
TRASFORMA = (b"irot", b"imir", b"clap")
HEIF = (".heic", ".heif")
AVIF = (".avif",)
TOLLERANZA = 0.02
TRASPARENZE = ("urn:mpeg:hevc:2015:auxid:1", "urn:mpeg:mpegB:cicp:systems:auxiliary:alpha")


class ScatolaStrana(ValueError):
    pass


@dataclass
class Scatola:
    tipo: bytes
    corpo: bytes


@dataclass
class Pezzo:
    metodo: int
    pezzi: list[tuple[int, int]]


@dataclass
class Voce:
    numero: int
    tipo: bytes
    resto: bytes
    protezione: int = 0
    bandiere: int = 0


@dataclass
class Heif:
    ftyp: bytes
    altre: list[Scatola]
    primaria: int
    voci: dict[int, Voce]
    dove: dict[int, Pezzo]
    rimandi: list[tuple[bytes, int, list[int]]]
    proprieta: list[bytes]
    legami: dict[int, list[tuple[bool, int]]]
    idat: bytes
    dati: bytes
    dopo: list[Scatola] = field(default_factory=list)


def _scatole(dati: bytes, inizio: int, fine: int) -> list[tuple[bytes, int, int]]:
    trovate = []
    while inizio < fine:
        if fine - inizio < 8:
            raise ScatolaStrana("scatola tagliata")
        misura, tipo = struct.unpack(">I4s", dati[inizio:inizio + 8])
        testa = 8
        if misura == 1:
            misura = struct.unpack(">Q", dati[inizio + 8:inizio + 16])[0]
            testa = 16
        elif misura == 0:
            misura = fine - inizio
        if misura < testa or inizio + misura > fine:
            raise ScatolaStrana("misura sbagliata")
        trovate.append((tipo, inizio + testa, inizio + misura))
        inizio += misura
    return trovate


def _numero(dati: bytes, dove: int, quanti: int) -> tuple[int, int]:
    if quanti == 0:
        return 0, dove
    if quanti not in (2, 4, 8):
        raise ScatolaStrana("numero di misura strana")
    return int.from_bytes(dati[dove:dove + quanti], "big"), dove + quanti


def _iloc(corpo: bytes) -> dict[int, Pezzo]:
    versione = corpo[0]
    if versione > 2:
        raise ScatolaStrana("iloc nuovo")
    p = 4
    misure = corpo[p:p + 2]
    p += 2
    spostamento, lunghezza = misure[0] >> 4, misure[0] & 15
    base, indice = misure[1] >> 4, (misure[1] & 15) if versione else 0
    quante, p = _numero(corpo, p, 2 if versione < 2 else 4)
    dove = {}
    for _ in range(quante):
        numero, p = _numero(corpo, p, 2 if versione < 2 else 4)
        metodo = 0
        if versione:
            metodo = int.from_bytes(corpo[p:p + 2], "big") & 15
            p += 2
        riferimento, p = _numero(corpo, p, 2)
        if riferimento:
            raise ScatolaStrana("dati fuori dal file")
        partenza, p = _numero(corpo, p, base)
        estesi, p = _numero(corpo, p, 2)
        pezzi = []
        for _ in range(estesi):
            _, p = _numero(corpo, p, indice)
            da, p = _numero(corpo, p, spostamento)
            lungo, p = _numero(corpo, p, lunghezza)
            pezzi.append((partenza + da, lungo))
        if metodo not in (0, 1):
            raise ScatolaStrana("dati presi da altre voci")
        dove[numero] = Pezzo(metodo, pezzi)
    return dove


def _iinf(corpo: bytes) -> dict[int, Voce]:
    versione = corpo[0]
    quante, p = _numero(corpo, 4, 2 if versione == 0 else 4)
    voci = {}
    for tipo, da, a in _scatole(corpo, p, len(corpo)):
        if tipo != b"infe":
            continue
        infe = corpo[da:a]
        v = infe[0]
        if v < 2:
            raise ScatolaStrana("infe vecchia")
        q = 4
        numero, q = _numero(infe, q, 2 if v == 2 else 4)
        protezione, q = _numero(infe, q, 2)
        voci[numero] = Voce(numero, infe[q:q + 4], infe[q + 4:], protezione,
                            int.from_bytes(infe[1:4], "big"))
    if len(voci) != quante:
        raise ScatolaStrana("voci contate male")
    return voci


def _iref(corpo: bytes) -> list[tuple[bytes, int, list[int]]]:
    largo = 2 if corpo[0] == 0 else 4
    rimandi = []
    for tipo, da, a in _scatole(corpo, 4, len(corpo)):
        da_chi, q = _numero(corpo, da, largo)
        quanti, q = _numero(corpo, q, 2)
        verso = []
        for _ in range(quanti):
            uno, q = _numero(corpo, q, largo)
            verso.append(uno)
        rimandi.append((tipo, da_chi, verso))
    return rimandi


def _ipma(corpo: bytes) -> dict[int, list[tuple[bool, int]]]:
    versione, bandiere = corpo[0], int.from_bytes(corpo[1:4], "big")
    quante, p = _numero(corpo, 4, 4)
    legami = {}
    for _ in range(quante):
        numero, p = _numero(corpo, p, 2 if versione < 1 else 4)
        quanti = corpo[p]
        p += 1
        uniti = []
        for _ in range(quanti):
            if bandiere & 1:
                valore, p = _numero(corpo, p, 2)
                uniti.append((bool(valore >> 15), valore & 0x7FFF))
            else:
                valore = corpo[p]
                p += 1
                uniti.append((bool(valore >> 7), valore & 0x7F))
        legami[numero] = uniti
    return legami


def leggi(dati: bytes) -> Heif:
    fuori = _scatole(dati, 0, len(dati))
    if not fuori or fuori[0][0] != b"ftyp":
        raise ScatolaStrana("non è un HEIF")
    ftyp = dati[fuori[0][1]:fuori[0][2]]
    meta = [s for s in fuori if s[0] == b"meta"]
    if len(meta) != 1:
        raise ScatolaStrana("meta mancante o doppia")
    _, da, a = meta[0]
    altre, voci, dove, rimandi = [], {}, {}, []
    proprieta, legami, idat, primaria = [], {}, b"", None
    for tipo, d, f in _scatole(dati, da + 4, a):
        corpo = dati[d:f]
        if tipo == b"iloc":
            dove = _iloc(corpo)
        elif tipo == b"iinf":
            voci = _iinf(corpo)
        elif tipo == b"iref":
            rimandi = _iref(corpo)
        elif tipo == b"pitm":
            primaria, _ = _numero(corpo, 4, 2 if corpo[0] == 0 else 4)
        elif tipo == b"idat":
            idat = corpo
        elif tipo == b"iprp":
            for t, d2, f2 in _scatole(corpo, 0, len(corpo)):
                if t == b"ipco":
                    proprieta =[corpo[s:e] for s, e in _inizi(corpo, d2, f2)]
                elif t == b"ipma":
                    legami.update(_ipma(corpo[d2:f2]))
        else:
            altre.append(Scatola(tipo, corpo))
    if primaria is None or primaria not in voci:
        raise ScatolaStrana("manca la voce principale")
    dopo = [Scatola(t, dati[d:f]) for t, d, f in fuori[1:]
            if t not in (b"meta", b"mdat", b"free", b"skip")]
    return Heif(ftyp, altre, primaria, voci, dove, rimandi, proprieta, legami, idat,
                dati, dopo)


def _inizi(dati: bytes, inizio: int, fine: int) -> list[tuple[int, int]]:
    posti = []
    while inizio < fine:
        misura = struct.unpack(">I", dati[inizio:inizio + 4])[0]
        if misura == 1:
            misura = struct.unpack(">Q", dati[inizio + 8:inizio + 16])[0]
        elif misura == 0:
            misura = fine - inizio
        if misura < 8 or inizio + misura > fine:
            raise ScatolaStrana("proprietà tagliata")
        posti.append((inizio, inizio + misura))
        inizio += misura
    return posti


def contenuto(heif: Heif, numero: int) -> bytes:
    pezzo = heif.dove.get(numero)
    if pezzo is None:
        return b""
    fonte = heif.idat if pezzo.metodo == 1 else heif.dati
    parti = []
    for da, lungo in pezzo.pezzi:
        if lungo == 0 and len(pezzo.pezzi) == 1 and pezzo.metodo == 0:
            raise ScatolaStrana("voce lunga fino alla fine")
        if da + lungo > len(fonte):
            raise ScatolaStrana("voce fuori dal file")
        parti.append(fonte[da:da + lungo])
    return b"".join(parti)


def tipo_ausiliario(heif: Heif, numero: int) -> str:
    for _, indice in heif.legami.get(numero, []):
        if not indice:
            continue
        scatola = heif.proprieta[indice - 1]
        if scatola[4:8] == b"auxC":
            return scatola[12:].split(b"\0", 1)[0].decode("utf-8", "replace")
    return ""


def ausiliarie(heif: Heif) -> list[int]:
    return [da for tipo, da, verso in heif.rimandi
            if tipo == AUSILIARIA and heif.primaria in verso and da in heif.voci]


def _famiglia(heif: Heif, scelte: list[int]) -> list[int]:
    dentro = list(scelte)
    cambiato = True
    while cambiato:
        cambiato = False
        for tipo, da, verso in heif.rimandi:
            if da in dentro and tipo != AUSILIARIA:
                for uno in verso:
                    if uno not in dentro and uno != heif.primaria and uno in heif.voci:
                        dentro.append(uno)
                        cambiato = True
            if tipo == DESCRIVE and da not in dentro and any(v in dentro for v in verso):
                if da in heif.voci:
                    dentro.append(da)
                    cambiato = True
    return dentro


def _scatola(tipo: bytes, corpo: bytes) -> bytes:
    if len(corpo) + 8 > 0xFFFFFFFF:
        return struct.pack(">I4sQ", 1, tipo, len(corpo) + 16) + corpo
    return struct.pack(">I4s", len(corpo) + 8, tipo) + corpo


def _piena(tipo: bytes, versione: int, bandiere: int, corpo: bytes) -> bytes:
    return _scatola(tipo, bytes([versione]) + bandiere.to_bytes(3, "big") + corpo)


def scrivi(heif: Heif, voci: dict[int, Voce], contenuti: dict[int, tuple[int, bytes]],
           rimandi: list[tuple[bytes, int, list[int]]], proprieta: list[bytes],
           legami: dict[int, list[tuple[bool, int]]]) -> bytes:
    larghi = max(voci) > 0xFFFF
    largo = 4 if larghi else 2
    infe = b"".join(
        _piena(b"infe", 3 if larghi else 2, v.bandiere,
               v.numero.to_bytes(largo, "big") + v.protezione.to_bytes(2, "big")
               + v.tipo + v.resto)
        for v in sorted(voci.values(), key=lambda v: v.numero))
    iinf = _piena(b"iinf", 1 if len(voci) > 0xFFFF else 0, 0,
                  len(voci).to_bytes(4 if len(voci) > 0xFFFF else 2, "big") + infe)
    iref = _piena(b"iref", 1 if larghi else 0, 0, b"".join(
        _scatola(tipo, da.to_bytes(largo, "big") + len(verso).to_bytes(2, "big")
                 + b"".join(v.to_bytes(largo, "big") for v in verso))
        for tipo, da, verso in rimandi)) if rimandi else b""
    lunghi = any(i > 0x7F for uniti in legami.values() for _, i in uniti)
    ipma_corpo = len(legami).to_bytes(4, "big")
    for numero in sorted(legami):
        uniti = legami[numero]
        if len(uniti) > 255:
            raise ScatolaStrana("troppe proprietà")
        ipma_corpo += numero.to_bytes(largo, "big") + bytes([len(uniti)])
        for essenziale, indice in uniti:
            if lunghi:
                ipma_corpo += ((0x8000 if essenziale else 0) | indice).to_bytes(2, "big")
            else:
                ipma_corpo += bytes([(0x80 if essenziale else 0) | indice])
    iprp = _scatola(b"iprp", _scatola(b"ipco", b"".join(proprieta))
                    + _piena(b"ipma", 1 if larghi else 0, 1 if lunghi else 0, ipma_corpo))
    pitm = _piena(b"pitm", 1 if larghi else 0, 0, heif.primaria.to_bytes(largo, "big"))
    in_idat = b"".join(c for m, c in contenuti.values() if m == 1)
    idat = _scatola(b"idat", in_idat) if in_idat else b""
    nel_file = sum(len(c) for m, c in contenuti.values() if m == 0)
    otto = nel_file > 0xF0000000
    misura = 8 if otto else 4

    def iloc(partenza: int) -> bytes:
        corpo = bytes([(misura << 4) | misura, 0])
        corpo += len(contenuti).to_bytes(4 if larghi else 2, "big")
        dentro_file, dentro_idat = partenza, 0
        for numero in sorted(contenuti):
            metodo, dati = contenuti[numero]
            corpo += numero.to_bytes(4 if larghi else 2, "big")
            corpo += metodo.to_bytes(2, "big") + b"\0\0" + (1).to_bytes(2, "big")
            if metodo == 1:
                corpo += dentro_idat.to_bytes(misura, "big")
                dentro_idat += len(dati)
            else:
                corpo += dentro_file.to_bytes(misura, "big")
                dentro_file += len(dati)
            corpo += len(dati).to_bytes(misura, "big")
        return _piena(b"iloc", 2 if larghi else 1, 0, corpo)

    ftyp = _scatola(b"ftyp", heif.ftyp)
    resto = b"".join(_scatola(s.tipo, s.corpo) for s in heif.altre)
    resto += pitm + iinf + iref + iprp + idat
    dopo = b"".join(_scatola(s.tipo, s.corpo) for s in heif.dopo)
    testa_mdat = 16 if nel_file + 8 > 0xFFFFFFFF else 8
    prova = iloc(0)
    meta = _piena(b"meta", 0, 0, resto + prova)
    partenza = len(ftyp) + len(meta) + len(dopo) + testa_mdat
    meta = _piena(b"meta", 0, 0, resto + iloc(partenza))
    mdat = _scatola(b"mdat", b"".join(c for m, c in
                                      (contenuti[n] for n in sorted(contenuti)) if m == 0))
    return ftyp + meta + dopo + mdat


def _trapianta(nuova: Heif, vecchia: Heif, famiglia: list[int]):
    prossimo = max(nuova.voci) + 1
    nuovi = {vecchio: prossimo + i for i, vecchio in enumerate(sorted(famiglia))}
    voci = dict(nuova.voci)
    contenuti = {n: (nuova.dove[n].metodo, contenuto(nuova, n)) for n in nuova.dove}
    proprieta = list(nuova.proprieta)
    legami = {n: list(u) for n, u in nuova.legami.items()}
    rimandi = list(nuova.rimandi)
    per_indice: dict[int, int] = {}
    for vecchio in sorted(famiglia):
        voce = vecchia.voci[vecchio]
        voci[nuovi[vecchio]] = replace(voce, numero=nuovi[vecchio])
        if vecchio in vecchia.dove:
            contenuti[nuovi[vecchio]] = (vecchia.dove[vecchio].metodo,
                                         contenuto(vecchia, vecchio))
        uniti = []
        for essenziale, indice in vecchia.legami.get(vecchio, []):
            if indice and indice not in per_indice:
                proprieta.append(vecchia.proprieta[indice - 1])
                per_indice[indice] = len(proprieta)
            uniti.append((essenziale, per_indice.get(indice, 0)))
        if uniti:
            legami[nuovi[vecchio]] = uniti
    for tipo, da, verso in vecchia.rimandi:
        if da not in famiglia:
            continue
        if tipo == AUSILIARIA:
            if vecchia.primaria in verso:
                rimandi.append((tipo, nuovi[da], [nuova.primaria]))
            continue
        if tipo == DERIVATA and vecchia.voci[da].tipo == MAPPA_ISO:
            mappa = {**nuovi, vecchia.primaria: nuova.primaria}
            if all(v in mappa for v in verso):
                rimandi.append((tipo, nuovi[da], [mappa[v] for v in verso]))
            continue
        tenuti = [nuovi[v] for v in verso if v in nuovi]
        if tenuti:
            rimandi.append((tipo, nuovi[da], tenuti))
    return nuovi, voci, contenuti, rimandi, proprieta, legami


def con_le_ausiliarie(migliorata: bytes, originale: bytes) -> tuple[bytes, list[str]]:
    nuova = leggi(migliorata)
    vecchia = leggi(originale)
    gia = {tipo_ausiliario(nuova, n) for n in ausiliarie(nuova)}
    scelte = [n for n in ausiliarie(vecchia)
              if tipo_ausiliario(vecchia, n) not in gia
              and tipo_ausiliario(vecchia, n) not in TRASPARENZE]
    if not scelte:
        return migliorata, []
    _, *pezzi = _trapianta(nuova, vecchia, _famiglia(vecchia, scelte))
    tipi = [tipo_ausiliario(vecchia, n) for n in scelte]
    return scrivi(nuova, *pezzi), tipi


def mappe_iso(heif: Heif) -> list[tuple[int, int]]:
    return [(da, verso[1]) for tipo, da, verso in heif.rimandi
            if tipo == DERIVATA and da in heif.voci and heif.voci[da].tipo == MAPPA_ISO
            and len(verso) == 2 and verso[0] == heif.primaria and verso[1] in heif.voci]


def _proprieta_di(heif: Heif, numero: int, tipi: tuple[bytes, ...]) -> list[bytes]:
    return [heif.proprieta[indice - 1] for _, indice in heif.legami.get(numero, [])
            if indice and heif.proprieta[indice - 1][4:8] in tipi]


def _girate(heif: Heif, numero: int) -> list[bytes]:
    return [s for s in _proprieta_di(heif, numero, TRASFORMA)
            if s[4:8] != b"irot" or len(s) < 9 or s[8] & 3]


def _misura(heif: Heif, numero: int) -> tuple[int, int] | None:
    for scatola in _proprieta_di(heif, numero, (b"ispe",)):
        if len(scatola) >= 20:
            return struct.unpack(">II", scatola[12:20])
    return None


def _gruppi(altre: list[Scatola], gruppo: bytes) -> list[Scatola]:
    tenute, messo = [], False
    for scatola in altre:
        if scatola.tipo == GRUPPI and not messo:
            scatola = Scatola(GRUPPI, scatola.corpo + gruppo)
            messo = True
        tenute.append(scatola)
    return tenute if messo else [*tenute, Scatola(GRUPPI, gruppo)]


def _numeri_dei_gruppi(heif: Heif) -> list[int]:
    numeri = []
    for scatola in heif.altre:
        if scatola.tipo != GRUPPI:
            continue
        for _, da, _ in _scatole(scatola.corpo, 0, len(scatola.corpo)):
            numeri.append(int.from_bytes(scatola.corpo[da + 4:da + 8], "big"))
    return numeri


def con_la_mappa_iso(migliorata: bytes, originale: bytes) -> bytes | None:
    nuova = leggi(migliorata)
    vecchia = leggi(originale)
    if mappe_iso(nuova):
        return None
    trovate = mappe_iso(vecchia)
    if len(trovate) != 1:
        return None
    mappa, guadagno = trovate[0]
    misura, grande = _misura(nuova, nuova.primaria), _misura(vecchia, guadagno)
    if misura is None or grande is None:
        raise ScatolaStrana("misure mancanti")
    forma = misura[0] / misura[1]
    if abs(grande[0] / grande[1] - forma) > TOLLERANZA * forma:
        raise ScatolaStrana("mappa di forma diversa")
    if _girate(vecchia, vecchia.primaria) != _girate(nuova, nuova.primaria):
        raise ScatolaStrana("girata in modo diverso")
    if _girate(vecchia, mappa) != _girate(vecchia, vecchia.primaria):
        raise ScatolaStrana("mappa girata in modo diverso")
    nuovi, voci, contenuti, rimandi, proprieta, legami = _trapianta(
        nuova, vecchia, _famiglia(vecchia, [mappa]))
    uniti = [u for u in legami[nuovi[mappa]]
             if not u[1] or proprieta[u[1] - 1][4:8] != b"ispe"]
    ispe = [u for u in nuova.legami[nuova.primaria]
            if u[1] and nuova.proprieta[u[1] - 1][4:8] == b"ispe"]
    legami[nuovi[mappa]] = ispe + uniti
    gruppo = max([*voci, *_numeri_dei_gruppi(nuova)]) + 1
    altr = _piena(ALTERNATIVE, 0, 0, struct.pack(">III", gruppo, 2, nuovi[mappa])
                  + nuova.primaria.to_bytes(4, "big"))
    marche = [nuova.ftyp[i:i + 4] for i in range(8, len(nuova.ftyp), 4)]
    ftyp = nuova.ftyp if MAPPA_ISO in marche else nuova.ftyp + MAPPA_ISO
    pronta = replace(nuova, ftyp=ftyp, altre=_gruppi(nuova.altre, altr))
    return scrivi(pronta, voci, contenuti, rimandi, proprieta, legami)


def controlla_iso(prima: bytes, dopo: bytes, originale: bytes) -> bool:
    senza, con, vecchia = leggi(prima), leggi(dopo), leggi(originale)
    if con.primaria != senza.primaria:
        return False
    for numero, voce in senza.voci.items():
        if con.voci.get(numero) != voce:
            return False
        if contenuto(con, numero) != contenuto(senza, numero):
            return False
        tutte = [con.proprieta[i - 1] for _, i in con.legami.get(numero, []) if i]
        if tutte != [senza.proprieta[i - 1] for _, i in senza.legami.get(numero, []) if i]:
            return False
    nuove, vecchie = mappe_iso(con), mappe_iso(vecchia)
    if len(nuove) != 1 or len(vecchie) != 1:
        return False
    qui = sorted(_famiglia(con, [nuove[0][0]]))
    la = sorted(_famiglia(vecchia, [vecchie[0][0]]))
    if len(qui) != len(la):
        return False
    for nuovo, vecchio in zip(qui, la, strict=True):
        if contenuto(con, nuovo) != contenuto(vecchia, vecchio):
            return False
        if con.voci[nuovo].tipo != vecchia.voci[vecchio].tipo:
            return False
    return _misura(con, nuove[0][0]) == _misura(con, con.primaria)


def _byte_di(percorso) -> bytes:
    if hasattr(percorso, "apri"):
        sorgente = percorso.apri()
        try:
            return sorgente.read()
        finally:
            sorgente.close()
    return Path(percorso).read_bytes()


def _quadri(heif_file) -> dict[str, list]:
    import numpy

    quadri: dict[str, list] = {}
    for tipo, numeri in (heif_file.info.get("aux") or {}).items():
        quadri[tipo] = [numpy.asarray(heif_file.get_aux_image(n).to_pillow())
                        for n in numeri]
    quadri["profondita"] = [numpy.asarray(d.to_pillow())
                            for d in heif_file.info.get("depth_images") or []]
    return quadri


def _stessa_forma(quadro, larghezza: int, altezza: int) -> bool:
    alto, largo = quadro.shape[:2]
    return abs(largo / alto - larghezza / altezza) <= TOLLERANZA * larghezza / altezza


def controlla(prima: bytes, dopo: bytes, originale: bytes) -> bool:
    import numpy
    import pillow_heif

    vecchia = pillow_heif.open_heif(io.BytesIO(originale), convert_hdr_to_8bit=False)
    senza = pillow_heif.open_heif(io.BytesIO(prima), convert_hdr_to_8bit=False)
    con = pillow_heif.open_heif(io.BytesIO(dopo), convert_hdr_to_8bit=False)
    if con.size != senza.size or con.mode != senza.mode:
        return False
    if not numpy.array_equal(numpy.asarray(con.to_pillow()),
                             numpy.asarray(senza.to_pillow())):
        return False
    attese, avute = _quadri(vecchia), _quadri(con)
    larghezza, altezza = con.size
    for tipo, quadri in attese.items():
        if tipo in TRASPARENZE:
            continue
        nuovi = avute.get(tipo, [])
        if len(nuovi) != len(quadri):
            return False
        for vecchio, nuovo in zip(quadri, nuovi, strict=True):
            if not numpy.array_equal(vecchio, nuovo):
                return False
            if not _stessa_forma(nuovo, larghezza, altezza):
                return False
    return True


def _scrivi_sopra(uscita: Path, dati: bytes) -> None:
    nuova = Path(uscita).with_name(Path(uscita).name + ".aux")
    with open(nuova, "wb") as file:
        file.write(dati)
        file.flush()
        os.fsync(file.fileno())
    os.replace(nuova, uscita)


def _con_le_ausiliarie_controllate(prima: bytes, vecchia: bytes) -> tuple[bytes, list[str]]:
    from officina import registro

    try:
        dopo, tipi = con_le_ausiliarie(prima, vecchia)
        if tipi and not controlla(prima, dopo, vecchia):
            registro.avviso("miglioria.ausiliarie_non_uguali")
            return prima, []
    except Exception as errore:
        registro.avviso("miglioria.ausiliarie_non_copiate", motivo=registro.tipo_di(errore))
        return prima, []
    if tipi:
        registro.evento("miglioria.ausiliarie_copiate", quante=len(tipi))
    return dopo, tipi


def _con_la_mappa_iso_controllata(prima: bytes, vecchia: bytes) -> bytes | None:
    from officina import registro

    try:
        dopo = con_la_mappa_iso(prima, vecchia)
        if dopo is None:
            return None
        if not controlla_iso(prima, dopo, vecchia):
            registro.avviso("miglioria.mappa_iso_non_uguale")
            return None
    except Exception as errore:
        registro.avviso("miglioria.mappa_iso_non_copiata", motivo=registro.tipo_di(errore))
        return None
    registro.evento("miglioria.mappa_iso_copiata")
    return dopo


def rimetti(originale, uscita: Path) -> list[str]:
    from officina import registro

    suffisso = Path(str(getattr(originale, "nome", originale))).suffix.casefold()
    if suffisso not in HEIF + AVIF:
        return []
    try:
        prima = Path(uscita).read_bytes()
        vecchia = _byte_di(originale)
    except Exception as errore:
        registro.avviso("miglioria.ausiliarie_non_copiate", motivo=registro.tipo_di(errore))
        return []
    dopo, tipi = prima, []
    if suffisso in HEIF:
        dopo, tipi = _con_le_ausiliarie_controllate(prima, vecchia)
    iso = _con_la_mappa_iso_controllata(dopo, vecchia)
    if iso is not None:
        dopo, tipi = iso, [*tipi, MAPPA_ISO.decode()]
    if dopo is prima:
        return []
    try:
        _scrivi_sopra(uscita, dopo)
    except Exception as errore:
        registro.avviso("miglioria.ausiliarie_non_copiate", motivo=registro.tipo_di(errore))
        return []
    return tipi


__all__ = ["Heif", "ScatolaStrana", "ausiliarie", "con_la_mappa_iso", "con_le_ausiliarie",
           "contenuto", "controlla_iso", "leggi", "mappe_iso", "rimetti", "scrivi",
           "tipo_ausiliario"]
