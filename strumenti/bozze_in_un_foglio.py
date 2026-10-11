from __future__ import annotations

import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
BOZZE = RADICE / "sviluppo" / "bozze" / "visore"
FONDAMENTA = RADICE / "officina" / "web" / "statici" / "css" / "fondamenta.css"
USCITA = BOZZE / "tutte-le-bozze.html"

PAGINE = [
    ("01-apertura.html", "Si apre"),
    ("02-foto.html", "Foto"),
    ("03-foto-aperta.html", "La foto aperta"),
    ("04-nodi.html", "Nodi"),
    ("05-persone.html", "Persone"),
    ("06-persona.html", "Dentro una persona"),
    ("07-cerca.html", "Cerca"),
    ("08-preferiti.html", "Preferiti e raccolte"),
]


def _corpo(testo: str) -> str:
    dentro = re.search(r"<body>(.*)</body>", testo, re.S)
    if dentro is None:
        raise ValueError("pagina senza corpo")
    corpo = dentro.group(1)
    corpo = re.sub(r'<p class="torna">.*?</p>\s*', "", corpo, flags=re.S)
    return corpo.strip()


def _senza_intestazione(css: str) -> str:
    return re.sub(r"\A/\*.*?\*/\s*", "", css, flags=re.S)


def costruisci() -> str:
    fondamenta = _senza_intestazione(FONDAMENTA.read_text(encoding="utf-8"))
    visore = _senza_intestazione((BOZZE / "visore.css").read_text(encoding="utf-8"))
    indice = _corpo((BOZZE / "indice.html").read_text(encoding="utf-8"))

    for nome, _titolo in PAGINE:
        indice = indice.replace(
            'href="%s"' % nome, 'href="#%s"' % nome.split("-")[0]
        )

    pezzi = [indice]
    for numero, (nome, titolo) in enumerate(PAGINE, start=1):
        corpo = _corpo((BOZZE / nome).read_text(encoding="utf-8"))
        pezzi.append(
            '<hr class="stacco">\n'
            '<div class="foglio">\n'
            '<p class="torna"><a href="#in-cima">&laquo; l\'elenco delle otto</a></p>\n'
            "</div>\n"
            '<a id="%02d"></a>\n%s' % (numero, corpo)
        )
        del titolo

    return TELAIO % {
        "fondamenta": fondamenta,
        "visore": visore,
        "pezzi": "\n\n".join(pezzi),
    }


TELAIO = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Le bozze del Visore</title>


<style>
%(fondamenta)s
</style>
<style>
%(visore)s
</style>
<style>
.stacco {
    border: 0; border-top: 1px solid var(--linea);
    margin: var(--s12) auto 0; max-width: 1180px;
}
#in-cima { display: block; }
</style>
</head>

<body>
<a id="in-cima"></a>
%(pezzi)s
</body>
</html>
"""


def main() -> int:
    testo = costruisci()
    if "--controlla" in sys.argv:
        vecchio = USCITA.read_text(encoding="utf-8") if USCITA.exists() else ""
        if vecchio != testo:
            print("Il foglio unico non è aggiornato: rilancia senza --controlla.")
            return 1
        print("Il foglio unico è aggiornato.")
        return 0
    USCITA.write_text(testo, encoding="utf-8")
    print("Scritto %s (%d kB)." % (USCITA.relative_to(RADICE), len(testo.encode()) // 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
