from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "officina" / "web" / "statici" / "js"

NODE = shutil.which("node")

COPIONE = """
const catturati = [];
function elemento() {
    const propri = {};
    return new Proxy({}, {
        get(_, chiave) {
            if (chiave in propri) return propri[chiave];
            if (chiave === "classList") return { contains: () => false, add() {}, remove() {}, toggle() {} };
            if (chiave === "dataset" || chiave === "style") return {};
            if (chiave === "then") return undefined;
            return () => elemento();
        },
        set(_, chiave, valore) {
            propri[chiave] = valore;
            if (chiave === "innerHTML") catturati.push(valore);
            return true;
        },
    });
}
globalThis.document = {
    createElement: () => elemento(),
    body: { classList: { contains: () => true }, appendChild() {} },
    addEventListener() {},
};
globalThis.window = { matchMedia: () => ({ matches: true }) };
const f = await import(process.argv[2]);
const MALE = "<img src=x onerror=alert(1)>";
f.chiediSeSi({ titolo: MALE, sotto: `dentro ${MALE}`, tasto: MALE, annulla: MALE });
f.chiediUnNome({ titolo: MALE, sotto: MALE, valore: MALE, segnaposto: MALE, tasto: MALE });
f.chiediAlcuni({ titolo: MALE, sotto: MALE, voci: [{ id: MALE, testo: MALE, spento: MALE }], tasto: MALE });
f.chiediFraTre({ titolo: MALE, sotto: MALE, primo: MALE, secondo: MALE });
f.chiediSeSi({ titolo: f.htmlFidato("<b>grassetto</b>"), sotto: f.htmlFidato("<b>3</b> nodi"), tasto: "ok" });
console.log(JSON.stringify(catturati));
process.exit(0);
"""


@pytest.fixture(scope="module")
def finestre(tmp_path_factory):
    if NODE is None:
        pytest.skip("manca node")
    cartella = tmp_path_factory.mktemp("js")
    shutil.copy(JS / "finestrina.js", cartella / "finestrina.mjs")
    (cartella / "copione.mjs").write_text(COPIONE, encoding="utf-8")
    fuori = subprocess.run(
        [NODE, str(cartella / "copione.mjs"), (cartella / "finestrina.mjs").as_uri()],
        capture_output=True, text=True, timeout=60)
    assert fuori.returncode == 0, fuori.stderr
    return json.loads(fuori.stdout.strip().splitlines()[-1])


def test_la_finestrina_scampa_titolo_e_sotto_di_base(finestre):
    for html in finestre[:4]:
        assert "<img" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_la_finestrina_scampa_anche_i_tasti_e_le_voci(finestre):
    for html in finestre[:4]:
        assert "onerror=alert(1)>" not in html.replace("&gt;", "")
    voci = finestre[2]
    assert 'value="&lt;img' in voci
    assert "<span>&lt;img" in voci
    assert "<small>&lt;img" in voci


def test_il_campo_di_testo_resta_scampato(finestre):
    assert 'value="&lt;img' in finestre[1]
    assert 'placeholder="&lt;img' in finestre[1]


def test_l_html_fidato_si_chiede_a_voce(finestre):
    ultimo = finestre[4]
    assert "<h2 id=\"finestrina-titolo\"><b>grassetto</b></h2>" in ultimo
    assert "<p class=\"finestrina-sotto\"><b>3</b> nodi</p>" in ultimo


def test_la_galleria_non_mette_nomi_di_nodi_in_html():
    testo = (JS / "galleria.js").read_text(encoding="utf-8")
    assert "${voce.percorso} › </span>" not in testo
    assert "<span>${voce.nome}</span>" not in testo
    assert "nome.textContent = voce.nome" in testo
    assert "cammino.textContent" in testo


def test_la_nota_delle_persone_nell_etichettatura_e_scampata():
    testo = (JS / "officina.js").read_text(encoding="utf-8")
    assert "<small>${nota}</small>" not in testo
    assert "<small>${scampa(nota)}</small>" in testo


def test_il_nome_della_persona_da_dimenticare_e_scampato():
    testo = (JS / "impostazioni.js").read_text(encoding="utf-8")
    assert re.search(r"const chi = scampa\(", testo)


def test_nessuno_scampa_piu_due_volte_per_la_finestrina():
    for nome in ("albero.js", "unisci_persone.js", "programma.js"):
        testo = (JS / nome).read_text(encoding="utf-8")
        for chiamata in re.finditer(
                r"(?:chiediUnNome|chiediSeSi|chiediAlcuni|chiediFraTre)\(\{(.*?)\}\)", testo,
                re.S):
            corpo = chiamata.group(1)
            for campo in re.finditer(r"(?:titolo|sotto):\s*(`[^`]*`|\"[^\"]*\")", corpo):
                assert "scampa(" not in campo.group(1), (nome, campo.group(1))


def test_le_finestrine_con_html_lo_dichiarano():
    testo = (JS / "albero.js").read_text(encoding="utf-8")
    assert testo.count("sotto: htmlFidato(") == 2
    assert "sotto: (sotto" not in testo
