from __future__ import annotations

from PIL import Image

from officina.descrittori import radio4, torcia
from officina.descrittori.base import (MEZZA, PIENA,
                                       VISIONE_E_LINGUA, VISIVO, Descrittore,
                                       Scheda)
from officina.errori import ErroreOfficina
from officina import istruzioni


class ModelloNonInCasa(ErroreOfficina):
    codice = "modello_non_scaricato"


class MancanoLeLibrerie(ErroreOfficina):
    codice = "mancano_librerie_modelli"


class PrecisioneSbagliata(ErroreOfficina):
    codice = "precisione_sbagliata"


def _come_si_chiama_il_tipo() -> str:
    try:
        import transformers

        pezzi = str(transformers.__version__).split(".")
        maggiore, minore = int(pezzi[0]), int(pezzi[1])
    except Exception:
        return "dtype"
    return "dtype" if (maggiore, minore) >= (4, 56) else "torch_dtype"


def _solo_il_vettore(uscita):
    raccolto = getattr(uscita, "pooler_output", None)
    return uscita if raccolto is None else raccolto


def _controlla_i_pesi(modello, atteso, scheda: Scheda) -> None:
    trovato = None
    for parametro in getattr(modello, "parameters", lambda: [])():
        trovato = getattr(parametro, "dtype", None)
        break
    if trovato is None or trovato == atteso:
        return
    raise PrecisioneSbagliata(
        f"«{scheda.titolo}» doveva essere caricato a {atteso} ed è invece "
        f"a {trovato}. Succede quando la libreria «transformers» in casa "
        "chiama quell'impostazione con un altro nome: si aggiorna\n"
        f"{istruzioni.motori(aggiorna=True)}\n"
        "Meglio fermarsi adesso che a metà della notte con la scheda piena."
    )


def _controlla_le_librerie(scheda: Scheda, quali=None) -> None:
    prove = {
        "torch": torcia.c_e_torch,
        "transformers": torcia.c_e_transformers,
        "torchvision": torcia.c_e_torchvision,
        "safetensors": torcia.c_e_safetensors,
    }
    quali = quali or ("torch", "transformers", "torchvision")
    mancanti = [nome for nome in quali if not prove[nome]()]
    if mancanti:
        raise MancanoLeLibrerie(
            f"Per «{scheda.titolo}» manca {', '.join(mancanti)}. Le librerie "
            "dei modelli si installano a parte perché pesano qualche GB "
            "(regola 74):\n"
            f"{istruzioni.motori()}\n"
            "Senza, tutto il resto del programma funziona lo stesso: le "
            "impronte si calcolano con il descrittore disegnato a mano."
        )


class DaTransformers(Descrittore):

    def __init__(self, cartella_modelli, per_gruppo: int | None = None):
        super().__init__()
        self.cartella = cartella_modelli / self.scheda.nome
        self.per_gruppo = per_gruppo
        self._modello = None
        self._preparatore = None
        self._macchina = torcia.macchina()


    def _apri(self) -> None:
        _controlla_le_librerie(self.scheda)
        if not (self.cartella / "config.json").exists():
            raise ModelloNonInCasa(
                f"«{self.scheda.titolo}» non è ancora in casa. Si scarica una "
                "volta sola (regola 74):\n"
                f"{istruzioni.modello(self.scheda.nome)}\n"
                "Da quel momento il programma non tocca più la rete e funziona "
                "a scheda di rete spenta."
            )

        import torch
        from transformers import AutoImageProcessor, AutoModel

        self._preparatore = AutoImageProcessor.from_pretrained(
            str(self.cartella), local_files_only=True
        )
        tipo = self._tipo_numerico(torch)
        self._modello = AutoModel.from_pretrained(
            str(self.cartella), local_files_only=True, **{_come_si_chiama_il_tipo(): tipo}
        )
        _controlla_i_pesi(self._modello, tipo, self.scheda)
        self._modello.to(self._macchina.dispositivo)
        self._modello.eval()

    def _tipo_numerico(self, torch):
        if self.scheda.precisione == MEZZA and self._macchina.dispositivo == "cuda":
            return torch.float16
        return torch.float32

    def _chiudi(self) -> None:
        self._modello = None
        self._preparatore = None
        torcia.libera()

    def dove_gira(self) -> str:
        return self._macchina.a_parole()

    @property
    def gruppo(self) -> int:
        if self.per_gruppo:
            return self.per_gruppo
        return 16 if self._macchina.e_scheda_video else 4


    def _descrivi(self, immagini: list[Image.Image]) -> list[list[float]]:
        import torch

        fuori: list[list[float]] = []
        for inizio in range(0, len(immagini), self.gruppo):
            gruppo = immagini[inizio:inizio + self.gruppo]
            ingresso = self._preparatore(images=gruppo, return_tensors="pt")
            ingresso = {chiave: valore.to(self._macchina.dispositivo)
                        for chiave, valore in ingresso.items()}
            with torch.inference_mode():
                grezzo = self._estrai(ingresso)
            grezzo = grezzo.float()
            grezzo = grezzo / grezzo.norm(dim=-1, keepdim=True).clamp(min=1e-8)
            fuori.extend(riga.tolist() for riga in grezzo.cpu())
        return fuori

    def _estrai(self, ingresso):
        raise NotImplementedError


class Dinov3(DaTransformers):

    scheda = Scheda(
        nome="dinov3",
        titolo="DINOv3 ViT-L/16",
        versione="2-f32",
        precisione=PIENA,
        famiglia=VISIVO,
        dimensione=1024,
        licenza="DINOv3 License (Meta) — uso personale consentito, regola 177",
        identificatore="facebook/dinov3-vitl16-pretrain-lvd1689m",
        byte_attesi=1_200_000_000,
        lato=224,
        nota="Sola visione: è il più forte sul «questa immagine assomiglia a "
             "quell'altra», che è il caso degli oggetti specifici.",
    )

    def _estrai(self, ingresso):
        uscita = self._modello(**ingresso)
        raccolto = getattr(uscita, "pooler_output", None)
        if raccolto is None:
            raccolto = uscita.last_hidden_state[:, 0]
        return raccolto


class Siglip2(DaTransformers):

    scheda = Scheda(
        nome="siglip2",
        titolo="SigLIP 2 so400m",
        versione="2-f32",
        precisione=PIENA,
        famiglia=VISIONE_E_LINGUA,
        dimensione=1152,
        licenza="Apache 2.0 — libera, regola 177",
        identificatore="google/siglip2-so400m-patch14-384",
        byte_attesi=3_500_000_000,
        lato=384,
        nota="Immagini e parole nello stesso spazio: è quello che permetterà "
             "di far partire un nodo da zero e di cercare a parole (regola 102).",
    )

    def _estrai(self, ingresso):
        return _solo_il_vettore(self._modello.get_image_features(**ingresso))

    def descrivi_parole(self, frasi: list[str]) -> list[list[float]]:
        import torch
        from transformers import AutoTokenizer

        self.apri()
        divisore = AutoTokenizer.from_pretrained(str(self.cartella), local_files_only=True)
        ingresso = divisore(frasi, padding="max_length", max_length=64,
                            truncation=True, return_tensors="pt")
        ingresso = {chiave: valore.to(self._macchina.dispositivo)
                    for chiave, valore in ingresso.items()}
        with torch.inference_mode():
            grezzo = _solo_il_vettore(self._modello.get_text_features(**ingresso)).float()
        grezzo = grezzo / grezzo.norm(dim=-1, keepdim=True).clamp(min=1e-8)
        return [riga.tolist() for riga in grezzo.cpu()]


class Radio4(Descrittore):

    scheda = Scheda(
        nome="radio4",
        titolo="C-RADIOv4-H",
        versione="1-f32",
        precisione=PIENA,
        famiglia=VISIONE_E_LINGUA,
        dimensione=1536,
        licenza=radio4.LICENZA,
        identificatore=radio4.REPO,
        byte_attesi=4_200_000_000,
        lato=radio4.LATO,
        nota="Immagini e parole nello stesso spazio, con le parole lette da SigLIP 2 "
             "giant: serve per cercare a parole e per far partire un nodo da zero "
             "(regola 580).",
        prova_che_c_e=radio4.SCHEDA,
    )

    def __init__(self, cartella_modelli, per_gruppo: int | None = None):
        super().__init__()
        self.cartella = cartella_modelli / self.scheda.nome
        self.per_gruppo = per_gruppo
        self._visione = None
        self._testo = None
        self._divisore = None
        self._macchina = torcia.macchina()

    def _apri(self) -> None:
        _controlla_le_librerie(self.scheda, ("torch", "transformers", "safetensors"))
        if not radio4.ci_sono(self.cartella):
            raise ModelloNonInCasa(
                f"«{self.scheda.titolo}» non è ancora in casa. Si scarica una "
                "volta sola (regola 74):\n"
                f"{istruzioni.modello(self.scheda.nome)}\n"
                "Da quel momento il programma non tocca più la rete e funziona "
                "a scheda di rete spenta."
            )
        self._visione = radio4.costruisci_visione(self.cartella, self._macchina.dispositivo)

    def _apri_le_parole(self) -> None:
        if self._testo is None:
            self._testo = radio4.costruisci_testo(self.cartella, self._macchina.dispositivo)
            self._divisore = radio4.divisore(self.cartella)

    def _chiudi(self) -> None:
        self._visione = None
        self._testo = None
        self._divisore = None
        torcia.libera()

    def dove_gira(self) -> str:
        return self._macchina.a_parole()

    @property
    def gruppo(self) -> int:
        if self.per_gruppo:
            return self.per_gruppo
        return 8 if self._macchina.e_scheda_video else 2

    def _descrivi(self, immagini: list[Image.Image]) -> list[list[float]]:
        import torch

        fuori: list[list[float]] = []
        for inizio in range(0, len(immagini), self.gruppo):
            x = radio4.tensore(immagini[inizio:inizio + self.gruppo])
            with torch.inference_mode():
                grezzo = self._visione(x.to(self._macchina.dispositivo)).float()
            grezzo = grezzo / grezzo.norm(dim=-1, keepdim=True).clamp(min=1e-8)
            fuori.extend(riga.tolist() for riga in grezzo.cpu())
        return fuori

    def descrivi_parole(self, frasi: list[str]) -> list[list[float]]:
        import torch

        self.apri()
        self._apri_le_parole()
        ingresso = radio4.gettoni(self._divisore, frasi)
        ingresso = {chiave: valore.to(self._macchina.dispositivo)
                    for chiave, valore in ingresso.items()}
        with torch.inference_mode():
            grezzo = self._testo(**ingresso).pooler_output.float()
        grezzo = grezzo / grezzo.norm(dim=-1, keepdim=True).clamp(min=1e-8)
        return [riga.tolist() for riga in grezzo.cpu()]
