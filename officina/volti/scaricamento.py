from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import ScaricamentoFallito, _dettaglio_tecnico
from officina.errori import ErroreOfficina
from officina.volti import rilevatore as rilevatore_mod
from officina import istruzioni

SCHEDA_SUL_DISCO = "scheda.json"


@dataclass(frozen=True)
class Fonte:

    repo: str
    nome_sul_sito: str
    provata: bool
    sha256: str = ""
    byte: int = 0
    licenza: str = ""
    riserve: tuple[str, ...] = ()
    genere: str = "model"

    @property
    def pagina(self) -> str:
        return f"https://huggingface.co/{self.repo}"


DA_DOVE: dict[str, Fonte] = {
    rilevatore_mod.FILE_RILEVATORE: Fonte(
        "public-data/insightface", "models/buffalo_l/det_10g.onnx",
        provata=True, byte=16_923_827, genere="dataset",
        licenza="InsightFace — uso non commerciale, regola 177",
        riserve=("menglaoda/_insightface", "deepinsight/insightface")),
    rilevatore_mod.FILE_RICONOSCITORE: Fonte(
        "Evn9172/cvlface_adaface_ir101_webface12m_onnx", "adaface_ir101.onnx",
        provata=True, byte=249_000_000,
        licenza="InsightFace/AdaFace — uso non commerciale, regola 177",
        riserve=("minchul/cvlface_adaface_ir101_webface12m",
                 "minchul/cvlface_adaface_ir101_webface4m")),
}


@dataclass
class Rapporto:
    dove: Path
    file: int = 0
    byte: int = 0
    gia_c_erano: bool = False


def gia_in_casa(cartella_modelli: Path) -> bool:
    return rilevatore_mod.ci_sono_i_modelli(cartella_modelli)


def scarica(cartella_modelli: Path, fonti: dict[str, Fonte] | None = None,
            al_passo: Callable[[str], None] | None = None,
            rifai: bool = False, chiave: str | None = None) -> Rapporto:
    dove = rilevatore_mod.dove_stanno(cartella_modelli)
    if gia_in_casa(cartella_modelli) and not rifai:
        return _conta(dove, gia_c_erano=True)

    fonti = fonti or dict(DA_DOVE)

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as errore:
        raise ScaricamentoFallito(
            "Per scaricare i modelli serve la libreria «huggingface-hub», che "
            "si installa insieme alle altre dei modelli:\n"
            f"{istruzioni.motori()}"
        ) from errore

    dove.mkdir(parents=True, exist_ok=True)
    arrivati: list[str] = []
    corrisponde: dict[str, bool | None] = {}
    prima = torcia.con_la_rete_accesa()
    try:
        for nome_in_casa, fonte in fonti.items():
            if al_passo:
                al_passo(f"scarico {fonte.nome_sul_sito} da {fonte.repo}")
            provati: list[Guardato] = []
            try:
                preso, fonte = _prendi(hf_hub_download, fonte, chiave,
                                       al_passo, provati)
                fonti[nome_in_casa] = fonte
            except Exception as errore:
                registro.errore("volti.scaricamento_fallito")
                raise ScaricamentoFallito(
                    "Non sono riuscito a scaricare i modelli dei volti.\n"
                    + _perche(errore, nome_in_casa, fonte, arrivati, chiave,
                              provati)
                    + "\n  Il resto del programma funziona lo stesso senza i volti."
                ) from errore
            (dove / nome_in_casa).write_bytes(Path(preso).read_bytes())
            arrivati.append(nome_in_casa)
            esito = e_quello_giusto(dove / nome_in_casa, fonte)
            corrisponde[nome_in_casa] = esito
            if esito is False and al_passo:
                al_passo(_non_corrisponde(dove / nome_in_casa, fonte))
    finally:
        torcia.rimetti_la_rete_com_era(prima)

    for vecchio in rilevatore_mod.FILE_VECCHI:
        (dove / vecchio).unlink(missing_ok=True)
    _annota(dove, fonti, corrisponde)
    rapporto = _conta(dove)
    registro.evento("volti.scaricati", file=rapporto.file)
    if al_passo:
        al_passo(f"volti: {rapporto.file} file, {rapporto.byte / 1e6:.0f} MB")
    return rapporto


def _prendi(hf_hub_download, fonte: Fonte, chiave: str | None,
            al_passo: Callable[[str], None] | None,
            provati: list[Guardato] | None = None) -> tuple[Path, Fonte]:
    voluto = fonte.nome_sul_sito
    solo_il_nome = voluto.rsplit("/", 1)[-1]

    provati = provati if provati is not None else []
    posti = [fonte.repo, *fonte.riserve]

    def prova(repo: str) -> tuple[Path, Fonte] | None:
        if any(g.repo == repo for g in provati):
            return None
        esito = _dentro_la_pagina(repo, chiave)
        if esito is None:
            provati.append(Guardato(repo, "", ()))
            return None
        dentro, genere = esito
        provati.append(Guardato(repo, genere, tuple(dentro)))
        if voluto in dentro:
            trovato = voluto
        else:
            uguali = [n for n in dentro if n.rsplit("/", 1)[-1] == solo_il_nome]
            if not uguali:
                return None
            trovato = uguali[0]
        if al_passo and (repo != fonte.repo or trovato != voluto):
            al_passo(f"«{fonte.repo}» non ce l'aveva; lo prendo da "
                     f"{repo}/{trovato}")
        preso = hf_hub_download(repo_id=repo, filename=trovato,
                                repo_type=genere, token=chiave or None)
        from dataclasses import replace

        return Path(preso), replace(fonte, repo=repo, nome_sul_sito=trovato,
                                    genere=genere, provata=True)

    for repo in posti:
        esito = prova(repo)
        if esito:
            return esito

    for repo in _posti_che_somigliano(fonte, chiave):
        esito = prova(repo)
        if esito:
            return esito

    return hf_hub_download(repo_id=fonte.repo, filename=voluto,
                           repo_type=fonte.genere, token=chiave or None), fonte


def e_quello_giusto(percorso: Path, fonte: Fonte) -> bool | None:
    if not fonte.sha256 or not percorso.exists():
        return None
    return _sha256(percorso) == fonte.sha256


def _non_corrisponde(percorso: Path, fonte: Fonte) -> str:
    return ("attenzione: «" + percorso.name + "» non corrisponde all'impronta "
            "pubblicata\n  da chi ha fatto il modello. Lo tengo lo stesso e i "
            "volti funzioneranno,\n  ma potrebbe essere una versione diversa "
            "da quella prevista.\n"
            f"      attesa:  {fonte.sha256[:16]}... ({fonte.byte} byte)\n"
            f"      trovata: {_sha256(percorso)[:16]}... "
            f"({percorso.stat().st_size} byte)")


def _sha256(percorso: Path) -> str:
    import hashlib

    digestore = hashlib.sha256()
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def come_si_chiama(nome_in_casa: str) -> str:
    return Path(nome_in_casa).stem


def _perche(errore: Exception, nome_in_casa: str, fonte: Fonte,
            arrivati: list[str], chiave: str | None,
            provati: list[Guardato] | None = None) -> str:
    from officina.descrittori.scaricamento import _che_genere

    quale = come_si_chiama(nome_in_casa)
    genere = _che_genere(errore)
    righe: list[str] = []

    if genere == "niente_rete":
        righe += ["  Non c'è rete, o non si arriva a chi distribuisce i "
                  "modelli.",
                  "  Riprova con la rete accesa."]
    elif genere == "permesso":
        righe += [f"  «{fonte.repo}» chiede un permesso. Apri la sua pagina,",
                  f"      {fonte.pagina}",
                  "  accetta le condizioni, e riprova con --chiave GETTONE."]
    elif genere == "manca_il_file":
        righe += [f"  Il posto «{fonte.repo}» c'è, ma dentro non c'è "
                  "nessun file",
                  f"  che si chiami «{fonte.nome_sul_sito}»."]
        righe += _quali_file_ci_sono(fonte, quale, chiave)
    elif genere == "non_trovato":
        righe.append(f"  «{fonte.repo}» non esiste, o ha cambiato nome.")
        if not fonte.provata:
            righe += ["  Questo posto non è mai stato verificato da chi ha "
                      "scritto il",
                      "  programma: è il caso più probabile."]
        if not provati or len(provati) <= 1:
            righe += _dove_altro_cercare(fonte, quale, chiave)
    else:
        righe.append("  Qualcosa è andato storto durante lo scaricamento.")

    if provati and len(provati) > 1:
        righe.append(f"  Ho guardato in {len(provati)} posti, uno per uno, e "
                     "in nessuno c'è un file")
        righe.append(f"  che si chiami «{fonte.nome_sul_sito}». Questo è "
                     "quello che c'è invece:")
        righe += _cosa_c_era(provati)
        righe.append("  Se fra questi riconosci quello giusto, dimmelo: il "
                     "nome si cambia")
        righe.append("  in un punto solo del programma.")

    if arrivati:
        nomi = [come_si_chiama(nome) for nome in arrivati]
        gia = " e il ".join(nomi)
        verbo = "è arrivato" if len(nomi) == 1 else "sono arrivati"
        righe.append(f"  Intanto il {gia} {verbo}: manca solo il {quale}.")
    righe.append(_dettaglio_tecnico(errore, chiave))
    return "\n".join(righe)


def _cosa_c_era(provati: list[Guardato]) -> list[str]:
    righe: list[str] = []
    for guardato in provati:
        if not guardato.genere:
            righe.append(f"      {guardato.repo}: non esiste, o non si arriva")
        elif not guardato.file:
            righe.append(f"      {guardato.repo}: nessun modello dentro")
        else:
            righe.append(f"      {guardato.repo}:")
            righe += [f"          {nome}" for nome in guardato.file[:6]]
            if len(guardato.file) > 6:
                righe.append(f"          ...e altri {len(guardato.file) - 6}")
    return righe


def _come_si_riprova(*righe: str) -> list[str]:
    if istruzioni.nel_programma():
        return ["      Il posto del modello è cambiato, e va corretto dentro il "
                "programma: succede con un aggiornamento. Intanto il resto "
                "del programma funziona."]
    return list(righe)


def _quali_file_ci_sono(fonte: Fonte, quale: str, chiave: str | None) -> list[str]:
    dentro = _gli_onnx_di(fonte.repo, chiave)
    if dentro is None:
        return ["  Apri la sua pagina e guarda come si chiama davvero:",
                f"      {fonte.pagina}",
                *_come_si_riprova("      python -m officina modelli --scarica volti \\",
                                  f"          --file-{quale} NOME.onnx")]
    if not dentro:
        return ["  Lì dentro non c'è nessun file .onnx: è il posto sbagliato.",
                *_dove_altro_cercare(fonte, quale, chiave)]
    righe = ["  Di file .onnx, lì dentro, ci sono questi:"]
    righe += [f"      {nome}" for nome in dentro[:8]]
    righe += ["  Riprova indicando quello giusto:",
              *_come_si_riprova("      python -m officina modelli --scarica volti \\",
                                f"          --file-{quale} {dentro[0]}")]
    return righe


def _dove_altro_cercare(fonte: Fonte, quale: str, chiave: str | None) -> list[str]:
    simili = _posti_che_somigliano(fonte, chiave)
    if not simili:
        return ["  Trovane uno che abbia il file .onnx e passalo così:",
                *_come_si_riprova("      python -m officina modelli --scarica volti \\",
                                  f"          --repo-{quale} NOME/DEL/POSTO --file-{quale} NOME.onnx")]
    righe = ["  Posti che potrebbero averlo, cercati adesso:"]
    righe += [f"      {nome}" for nome in simili]
    righe += ["  Quando hai visto quale è quello giusto:",
              *_come_si_riprova("      python -m officina modelli --scarica volti \\",
                                f"          --repo-{quale} {simili[0]} --file-{quale} NOME.onnx")]
    return righe


GENERI = ("model", "dataset", "space")

ROBA_DA_MODELLI = (".onnx", ".zip")


@dataclass(frozen=True)
class Guardato:

    repo: str
    genere: str
    file: tuple[str, ...]


def _dentro_la_pagina(repo: str, chiave: str | None) -> tuple[list[str], str] | None:
    from huggingface_hub import HfApi

    for genere in GENERI:
        try:
            dentro = HfApi().list_repo_files(repo, repo_type=genere,
                                             token=chiave or None)
        except Exception:
            continue
        return (sorted(n for n in dentro
                       if n.endswith(ROBA_DA_MODELLI)), genere)
    return None


def _gli_onnx_di(repo: str, chiave: str | None) -> list[str] | None:
    esito = _dentro_la_pagina(repo, chiave)
    return None if esito is None else esito[0]


def _posti_che_somigliano(fonte: Fonte, chiave: str | None) -> list[str]:
    ultimo_pezzo = fonte.repo.rsplit("/", 1)[-1]
    parole = [ultimo_pezzo]
    coda = ultimo_pezzo.rsplit("_", 1)[-1]
    if coda and coda != ultimo_pezzo:
        parole.append(coda)
    for parola in parole:
        try:
            from huggingface_hub import HfApi

            trovati = [modello.id for modello in
                       HfApi().list_models(search=parola, limit=5,
                                           token=chiave or None)]
        except Exception:
            return []
        if trovati:
            return trovati
    return []


def _annota(dove: Path, fonti: dict[str, Fonte],
            corrisponde: dict[str, bool | None] | None = None) -> None:
    (dove / SCHEDA_SUL_DISCO).write_text(json.dumps({
        "che_cosa": "i due modelli dei volti (regole 33, 339)",
        "versione": rilevatore_mod.VERSIONE,
        "da_dove": {nome: {"repo": fonte.repo,
                           "file": fonte.nome_sul_sito,
                           "licenza": fonte.licenza or "non dichiarata",
                           "corrisponde_all_originale":
                               (corrisponde or {}).get(nome)}
                    for nome, fonte in fonti.items()},
        "impronte": {nome: _impronta(dove / nome)
                     for nome in fonti
                     if (dove / nome).exists()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _impronta(percorso: Path) -> str:
    import hashlib

    digestore = hashlib.blake2b(digest_size=16)
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _conta(dove: Path, gia_c_erano: bool = False) -> Rapporto:
    if not dove.is_dir():
        return Rapporto(dove, gia_c_erano=gia_c_erano)
    file = [p for p in dove.iterdir() if p.is_file()]
    return Rapporto(dove, len(file), sum(p.stat().st_size for p in file),
                    gia_c_erano)


def verifica(cartella_modelli: Path) -> dict:
    dove = rilevatore_mod.dove_stanno(cartella_modelli)
    scheda = dove / SCHEDA_SUL_DISCO
    if not scheda.exists():
        return {"stato": "non_scaricato",
                "dettaglio": "I modelli dei volti non ci sono."}
    try:
        dati = json.loads(scheda.read_text(encoding="utf-8"))
    except (ValueError, OSError) as errore:
        raise ErroreOfficina(
            "La scheda dei modelli dei volti non si legge.") from errore

    rovinati = []
    for nome, attesa in (dati.get("impronte") or {}).items():
        percorso = dove / nome
        if not percorso.exists() or _impronta(percorso) != attesa:
            rovinati.append(nome)
    if rovinati:
        return {"stato": "rovinato", "dettaglio":
                "Non corrispondono più: " + ", ".join(rovinati)
                + ". Riscaricali con --scarica volti --rifai."}
    quanti = len(dati.get("impronte") or {})
    dettaglio = ("volti: intatti (" + str(quanti)
                 + (" file controllato)" if quanti == 1 else " file controllati)"))

    licenze = sorted({(riga or {}).get("licenza") or "non dichiarata"
                      for riga in (dati.get("da_dove") or {}).values()})
    if licenze:
        dettaglio += " — " + ", ".join(licenze)

    diversi = [nome for nome, riga in (dati.get("da_dove") or {}).items()
               if (riga or {}).get("corrisponde_all_originale") is False]
    if diversi:
        dettaglio += ("\n  Ma non corrispondono all'originale pubblicato: "
                      + ", ".join(sorted(diversi))
                      + ".\n  Funzionano; potrebbero essere una versione diversa.")
    return {"stato": "intatto", "dettaglio": dettaglio}


def togli(cartella_modelli: Path) -> bool:
    import shutil

    dove = rilevatore_mod.dove_stanno(cartella_modelli)
    if not dove.is_dir():
        return False
    shutil.rmtree(dove)
    return True
