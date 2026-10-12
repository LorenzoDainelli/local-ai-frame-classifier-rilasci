from __future__ import annotations

import json
import math
import struct
import zipfile

from officina.archivio.database import tutti, uno

FIRMA_PERSONE = b"O3P1"
FIRMA_NUVOLA = b"O3N1"
DI_BASE = ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
BECCHEGGIO_MASSIMO = 1.3


def _virgola(numero: float, cifre: int = 1) -> str:
    return f"{numero:.{cifre}f}".replace(".", ",")


def millimetri(campo_verticale: float, proporzione: float) -> int:
    meta = math.tan(campo_verticale / 2.0)
    corto = meta if proporzione >= 1.0 else meta * proporzione
    return int(round(12.0 / max(corto, 1e-6)))


def _sguardo(rotazione) -> str:
    avanti_su = float(rotazione[1][2])
    if avanti_su > 0.5:
        return "guardando in su"
    if avanti_su > 0.18:
        return "guardando un po' in su"
    if avanti_su < -0.5:
        return "guardando in giù"
    if avanti_su < -0.18:
        return "guardando un po' in giù"
    return "guardando dritto"


def descrivi(foto: dict) -> str:
    return f"da {_virgola(max(0.0, foto['centro'][1]))} m di altezza, {_sguardo(foto['rotazione'])}"


def _obiettivo(riga, campo_della_stanza: float | None, proporzione: float) -> str:
    if riga is not None and riga["fonte"] in ("exif", "puffin"):
        come = "dai dati della foto" if riga["fonte"] == "exif" else "stimato da Puffin"
        return f"{millimetri(riga['campo_verticale'], proporzione)} mm, {come}"
    if campo_della_stanza:
        return f"{millimetri(campo_della_stanza, proporzione)} mm, stimato dalla stanza"
    if riga is not None:
        return f"{millimetri(riga['campo_verticale'], proporzione)} mm, a occhio"
    return ""


def _senza_nome(numero: int, volto_id) -> str:
    return f"Persona {numero + 1} · " + ("volto senza nome" if volto_id else "senza volto")


def _la_piu_dentro(connessione, stanze_trovate: list[dict]) -> dict | None:
    from officina.modello import posti

    if not stanze_trovate:
        return None
    return max(stanze_trovate, key=lambda s: (len(posti.antenati(connessione, s["posto_id"])), s["posto_id"]))


def _stanze_del_luogo(connessione, scatto_id: int) -> list[dict]:
    from officina.modello import stanze

    return [dict(r) for r in tutti(
        connessione,
        "SELECT st.*, p.nome FROM posti_negli_scatti n JOIN stanze st ON st.posto_id = n.posto_id "
        "JOIN posti p ON p.id = n.posto_id WHERE n.scatto_id = ? AND st.stato = ? AND p.stato = 'attivo'",
        scatto_id, stanze.FATTA)]


def _principali(connessione, scatti: list[int]) -> dict[int, int]:
    if not scatti:
        return {}
    return {r["scatto_id"]: r["id"] for r in tutti(
        connessione,
        "SELECT scatto_id, id FROM file_media WHERE ruolo = 'principale' "
        "AND scatto_id IN (SELECT value FROM json_each(?))", json.dumps(scatti))}


def _obiettivi(connessione, scatti: list[int]) -> dict[int, object]:
    if not scatti:
        return {}
    return {r["scatto_id"]: r for r in tutti(
        connessione, "SELECT * FROM obiettivi WHERE scatto_id IN (SELECT value FROM json_each(?))",
        json.dumps(scatti))}


def _anni(foto: list[dict]) -> str:
    anni = sorted({f["data"][:4] for f in foto if f.get("data")})
    if not anni:
        return f"{len(foto)} foto"
    if len(anni) == 1:
        return f"{len(foto)} foto, del {anni[0]}"
    return f"{len(foto)} foto, dal {anni[0]} al {anni[-1]}"


def c_e(connessione, scatto_id: int) -> bool:
    from officina.modello import stanze

    riga = uno(
        connessione,
        "SELECT EXISTS (SELECT 1 FROM superfici f JOIN corpi c ON c.id = f.corpo_id "
        "WHERE c.scatto_id = ? AND c.fotogramma = 0 AND f.vertici > 0) "
        "OR EXISTS (SELECT 1 FROM posti_negli_scatti n JOIN stanze st ON st.posto_id = n.posto_id "
        "JOIN posti p ON p.id = n.posto_id WHERE n.scatto_id = ? AND st.stato = ? AND p.stato = 'attivo') AS si",
        scatto_id, scatto_id, stanze.FATTA)
    return bool(riga and riga["si"])


def scena(connessione, scatto_id: int) -> dict | None:
    from officina.corpi import superfici
    from officina.modello import corpi as corpi_mod
    from officina.modello import scatti as scatti_mod
    from officina.modello import stanze

    scatto = uno(connessione, "SELECT id, larghezza, altezza, data_locale FROM scatti WHERE id = ?", scatto_id)
    if scatto is None:
        return None
    proporzione = (scatto["larghezza"] or 4) / (scatto["altezza"] or 3)
    corpi = [c for c in corpi_mod.di_scatto(connessione, scatto_id) if c["fotogramma"] == 0]
    con_superficie = superfici.di_scatto(connessione, scatto_id)
    messa = _la_piu_dentro(connessione, stanze.di_scatto(connessione, scatto_id))
    stanza = messa or _la_piu_dentro(connessione, _stanze_del_luogo(connessione, scatto_id))
    persone = []
    for numero, corpo in enumerate(corpi):
        if corpo["id"] not in con_superficie:
            continue
        persone.append({"corpo_id": corpo["id"], "numero": numero,
                        "nome": corpo["persona"] or _senza_nome(numero, corpo["volto_id"]),
                        "con_nome": bool(corpo["persona"])})
    if stanza is None and not persone:
        return None
    foto = []
    if stanza is not None:
        foto = stanze.foto_di(connessione, stanza["posto_id"])
    if messa is None:
        persone = [] if stanza is not None else persone
    principali = _principali(connessione, [f["scatto_id"] for f in foto] + [scatto_id])
    obiettivi = _obiettivi(connessione, [f["scatto_id"] for f in foto] + [scatto_id])
    elenco = []
    for f in foto:
        if f["scatto_id"] not in principali:
            continue
        questa = f["scatto_id"] == scatto_id
        elenco.append({
            "scatto_id": f["scatto_id"], "file_id": principali[f["scatto_id"]], "questa": questa,
            "data": scatti_mod.giorno_a_parole((f["data"] or "")[:10] or None),
            "centro": f["centro"], "rotazione": f["rotazione"], "campo": f["campo"],
            "centro_x": f["centro_x"], "centro_y": f["centro_y"], "proporzione": f["proporzione"],
            "allungo": f["allungo"],
            "descrizione": descrivi(f),
            "obiettivo": _obiettivo(obiettivi.get(f["scatto_id"]), f["campo"], f["proporzione"]),
            "quando": f["data"] or ""})
    elenco.sort(key=lambda f: (not f["questa"], f["quando"] or "9999", f["scatto_id"]))
    for f in elenco:
        f.pop("quando")
    fuori = {"scatto_id": scatto_id, "file_id": principali.get(scatto_id), "proporzione": proporzione,
             "persone": persone, "foto": elenco, "stanza": None,
             "questa_messa": messa is not None, "piano": stanza is None}
    if stanza is not None:
        fuori["stanza"] = {
            "posto_id": stanza["posto_id"], "nome": stanza["nome"],
            "costruita_da": _anni(foto),
            "misure": (f"{_virgola(stanza['larga'] or 0)} × {_virgola(stanza['lunga'] or 0)} m, "
                       f"alta {_virgola(stanza['alta'] or 0)} m"),
            "alta": stanza["alta"] or 2.5, "larga": stanza["larga"] or 4.0, "lunga": stanza["lunga"] or 4.0,
            "versione": f"{stanza['versione']}-{stanza['costruita_il']}"}
    if not elenco or not elenco[0]["questa"]:
        fuori["obiettivo"] = _obiettivo(obiettivi.get(scatto_id), None, proporzione)
    return fuori


def _binario(firma: bytes, testa: dict, pezzi: list[bytes]) -> bytes:
    scritta = json.dumps(testa, ensure_ascii=False).encode("utf-8")
    scritta += b" " * (-len(scritta) % 4)
    corpo = []
    for pezzo in pezzi:
        corpo.append(pezzo + b"\0" * (-len(pezzo) % 4))
    return firma + struct.pack("<I", len(scritta)) + scritta + b"".join(corpo)


def in_piano(rollio, beccheggio) -> list[list[float]]:
    import numpy as np

    base = np.asarray(DI_BASE)
    try:
        r, p = float(rollio), float(beccheggio)
    except (TypeError, ValueError):
        return base.tolist()
    if not (math.isfinite(r) and math.isfinite(p)) or abs(p) > BECCHEGGIO_MASSIMO:
        return base.tolist()
    su = np.array([-math.sin(r) * math.cos(p), -math.cos(r) * math.cos(p), math.sin(p)])
    avanti = np.array([0.0, 0.0, 1.0]) - su[2] * su
    avanti /= np.linalg.norm(avanti)
    giu = -su
    return (base @ np.stack([np.cross(giu, avanti), giu, avanti])).tolist()


def camera_di_base(proporzione: float, fuoco: float, altezza: float, rotazione=None) -> dict:
    return {"centro": [0.0, altezza, 0.0], "rotazione": [list(r) for r in (rotazione or DI_BASE)],
            "campo": 2.0 * math.atan(0.5 / max(fuoco, 1e-6)), "centro_x": 0.5, "centro_y": 0.5,
            "proporzione": proporzione, "allungo": 1.0}


def nella_scena(vertici, spostamento, fuoco: float, proporzione: float, macchina: dict | None,
                piano=None):
    import numpy as np

    vertici = np.asarray(vertici, dtype=np.float64)
    t = np.asarray(spostamento, dtype=np.float64).copy()
    if macchina is None:
        return (vertici + t) @ np.asarray(piano or DI_BASE, dtype=np.float64).T
    fuoco_stanza = 0.5 / math.tan(float(macchina["campo"]) / 2.0)
    profondita = t[2]
    t[0] -= (float(macchina["centro_x"]) - 0.5) * proporzione * profondita / fuoco
    t[1] -= (float(macchina["centro_y"]) - 0.5) * profondita / fuoco
    t[2] = profondita * fuoco_stanza / fuoco
    nella_camera = vertici + t
    nella_camera[:, 0] /= float(macchina.get("allungo") or 1.0)
    rotazione = np.asarray(macchina["rotazione"], dtype=np.float64)
    return nella_camera @ rotazione.T + np.asarray(macchina["centro"], dtype=np.float64)


def persone_in_binario(archivio, scatto_id: int) -> bytes:
    import numpy as np

    from officina.corpi import figure, superfici
    from officina.modello import corpi as corpi_mod
    from officina.modello import stanze

    with archivio.lettura() as connessione:
        dati = scena(connessione, scatto_id)
        righe = superfici.di_scatto(connessione, scatto_id)
        numeri = {}
        for r in tutti(connessione, "SELECT a.corpo_id, a.vettore FROM aspetti a JOIN corpi c "
                       "ON c.id = a.corpo_id WHERE c.scatto_id = ? AND a.modello = ?", scatto_id, figure.ASPETTO):
            try:
                numeri[r["corpo_id"]] = figure.numeri_a_figura(corpi_mod.vettore_da_byte(r["vettore"], 1).tolist())
            except (ValueError, TypeError):
                continue
        macchina = None
        inclinata = uno(connessione, "SELECT rollio, beccheggio FROM obiettivi WHERE scatto_id = ?", scatto_id)
        piano = in_piano(inclinata["rollio"], inclinata["beccheggio"]) if inclinata else None
        if dati and dati["questa_messa"]:
            macchina = next((f for f in dati["foto"] if f["questa"]), None)
            if macchina is None:
                macchina = next((f for f in stanze.foto_di(connessione, dati["stanza"]["posto_id"])
                                 if f["scatto_id"] == scatto_id), None)
    facce = superfici.leggi_le_facce(archivio.dove.superfici)
    if not dati or not dati["persone"] or facce is None:
        return _binario(FIRMA_PERSONE, {"persone": [], "facce": 0, "macchina": None}, [])
    proporzione = dati["proporzione"]
    lette = []
    for persona in dati["persone"]:
        riga = righe.get(persona["corpo_id"])
        figura = numeri.get(persona["corpo_id"])
        if riga is None or figura is None:
            continue
        try:
            superficie = superfici.leggi(archivio.dove.superfici / riga["file"])
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):
            continue
        posti = nella_scena(superficie["locali"], superficie["spostamento"], figura["fuoco"], proporzione,
                            macchina, piano)
        lette.append((persona, posti, superficie, figura["fuoco"]))
    if not lette:
        return _binario(FIRMA_PERSONE, {"persone": [], "facce": 0, "macchina": None}, [])
    camera = None
    if macchina is None:
        basso = min(float(p[:, 1].min()) for _, p, _, _ in lette)
        lette = [(persona, p - np.array([0.0, basso, 0.0]), s, f) for persona, p, s, f in lette]
        camera = camera_di_base(proporzione, float(np.median([f for *_, f in lette])), -basso, piano)
    testa = {"persone": [], "facce": int(len(facce)), "grandi": bool(facce.dtype == np.uint32),
             "macchina": camera}
    pezzi = [np.ascontiguousarray(facce).tobytes()]
    for persona, posti, superficie, _ in lette:
        testa["persone"].append({"corpo_id": persona["corpo_id"], "vertici": int(len(posti))})
        pezzi.append(np.ascontiguousarray(posti, dtype="<f4").tobytes())
        pezzi.append(np.round(np.clip(superficie["uv"], 0, 1) * 65535).astype("<u2").tobytes())
        pezzi.append((superficie["visti"].astype(np.uint8) * 255).tobytes())
    return _binario(FIRMA_PERSONE, testa, pezzi)


def nuvola_in_binario(archivio, posto_id: int) -> bytes | None:
    import numpy as np

    from officina.modello import stanze
    from officina.stanza import costruzione

    with archivio.lettura() as connessione:
        stanza = stanze.di_posto(connessione, posto_id)
        attivo = uno(connessione, "SELECT 1 FROM posti WHERE id = ? AND stato = 'attivo'", posto_id)
    if stanza is None or attivo is None or stanza["stato"] != stanze.FATTA or not stanza["file"]:
        return None
    try:
        punti, colori = costruzione.leggi_la_nuvola(archivio.dove.stanze / stanza["file"])
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):
        return None
    if not len(punti):
        return _binario(FIRMA_NUVOLA, {"punti": 0, "centro": [0, 0, 0], "mezzo": [1, 1, 1]}, [b"", b""])
    basso, alto = punti.min(axis=0), punti.max(axis=0)
    centro = (basso + alto) / 2
    mezzo = np.maximum((alto - basso) / 2, 1e-6)
    stretti = np.round((punti - centro) / mezzo * 32767).clip(-32767, 32767).astype("<i2")
    testa = {"punti": int(len(punti)), "centro": centro.tolist(), "mezzo": mezzo.tolist()}
    return _binario(FIRMA_NUVOLA, testa, [stretti.tobytes(), np.ascontiguousarray(colori, dtype=np.uint8).tobytes()])
