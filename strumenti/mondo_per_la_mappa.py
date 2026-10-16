import json
import sys
from collections import defaultdict
from pathlib import Path


def archi(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    fuori = []
    for arco in topo["arcs"]:
        x = y = 0
        punti = []
        for dx, dy in arco:
            x += dx
            y += dy
            punti.append((x * sx + tx, y * sy + ty))
        fuori.append(punti)
    return fuori


def un_arco(tutti, i):
    return tutti[i] if i >= 0 else tutti[~i][::-1]


def anello(tutti, indici):
    punti = []
    for n, i in enumerate(indici):
        pezzo = un_arco(tutti, i)
        punti.extend(pezzo if n == 0 else pezzo[1:])
    return punti


def poligoni(geometria):
    if geometria["type"] == "Polygon":
        return [geometria["arcs"]]
    if geometria["type"] == "MultiPolygon":
        return geometria["arcs"]
    return []


def quantizza(punti, q, chiuso):
    fuori = []
    for x, y in punti:
        p = (round(x * q), round(max(-85.0, min(85.0, y)) * q))
        if not fuori or fuori[-1] != p:
            fuori.append(p)
    if chiuso and len(fuori) > 1 and fuori[0] == fuori[-1]:
        fuori.pop()
    return fuori


def _distanza(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** 0.5


def semplifica(punti, soglia):
    if len(punti) < 3 or soglia <= 0:
        return punti
    tieni = [False] * len(punti)
    tieni[0] = tieni[-1] = True
    pila = [(0, len(punti) - 1)]
    while pila:
        a, b = pila.pop()
        peggio, dove = 0.0, -1
        for i in range(a + 1, b):
            d = _distanza(punti[i], punti[a], punti[b])
            if d > peggio:
                peggio, dove = d, i
        if peggio > soglia and dove > 0:
            tieni[dove] = True
            pila.append((a, dove))
            pila.append((dove, b))
    return [p for p, si in zip(punti, tieni) if si]


def a_differenze(punti):
    fuori = []
    px = py = 0
    for x, y in punti:
        fuori.extend((x - px, y - py))
        px, py = x, y
    return fuori


def converti(terra_file, paesi_file, q, soglia, minimo):
    terra = json.loads(Path(terra_file).read_text())
    paesi = json.loads(Path(paesi_file).read_text())
    a_terra = archi(terra)
    anelli = []
    for geometria in terra["objects"]["land"]["geometries"]:
        for poligono in poligoni(geometria):
            for indici in poligono:
                punti = semplifica(quantizza(anello(a_terra, indici), q, True), soglia)
                if len(punti) >= minimo:
                    anelli.append(a_differenze(punti))
    a_paesi = archi(paesi)
    usati = defaultdict(set)
    for n, geometria in enumerate(paesi["objects"]["countries"]["geometries"]):
        for poligono in poligoni(geometria):
            for indici in poligono:
                for i in indici:
                    usati[i if i >= 0 else ~i].add(n)
    confini = []
    for i, chi in sorted(usati.items()):
        if len(chi) >= 2:
            punti = semplifica(quantizza(a_paesi[i], q, False), soglia)
            if len(punti) >= 2:
                confini.append(a_differenze(punti))
    return {"q": q, "terra": anelli, "confini": confini}


if __name__ == "__main__":
    sorgente, arrivo = Path(sys.argv[1]), Path(sys.argv[2])
    arrivo.mkdir(parents=True, exist_ok=True)
    for nome, terra, paesi, q, soglia, minimo in (
        ("mondo-largo.json", "land-50m.json", "countries-50m.json", 100, 3, 4),
        ("mondo-vicino.json", "land-10m.json", "countries-10m.json", 1000, 4, 4),
    ):
        dati = converti(sorgente / terra, sorgente / paesi, q, soglia, minimo)
        testo = json.dumps(dati, separators=(",", ":"))
        (arrivo / nome).write_text(testo)
        punti = sum(len(r) for r in dati["terra"]) // 2
        print(nome, len(testo) // 1024, "KB", len(dati["terra"]), "anelli", punti, "punti",
              len(dati["confini"]), "confini")
