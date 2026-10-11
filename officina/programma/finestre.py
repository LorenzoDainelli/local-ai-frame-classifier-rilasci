from __future__ import annotations

import sys
import threading
from pathlib import Path

from officina import registro
from officina.programma import NOME, carta, pagine
from officina.programma.ponti import PonteFinestrina, PontePrincipale

ICONA = Path(__file__).resolve().parent.parent / "web" / "statici" / "officina.ico"

MISURA_FINESTRINA = (560, 640)
MISURA_PRINCIPALE = (1320, 860)
MINIMA_PRINCIPALE = (960, 620)
FONDO = "#262624"
FONDO_CHIARO = "#FAF9F5"
ATTESA_DELLA_PRINCIPALE = 60.0


def windows_e_chiaro() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as chiave:
            return bool(winreg.QueryValueEx(chiave, "AppsUseLightTheme")[0])
    except OSError:
        return False


def fondo_della_finestra() -> str:
    from officina.programma import aspetto

    try:
        tema = aspetto.leggi()["tema"]
    except Exception:
        tema = "sistema"
    chiaro = tema == "chiaro" or (tema == "sistema" and windows_e_chiaro())
    return FONDO_CHIARO if chiaro else FONDO


class Finestre:

    def _schermo(self) -> dict:
        try:
            schermi = self.webview.screens
        except Exception:
            return {}
        return {"screen": schermi[0]} if schermi else {}

    def _geometria(self) -> dict:
        scritta = carta.leggi().get("finestra")
        return scritta if isinstance(scritta, dict) else {}

    def crea_la_principale(self, indirizzo: str | None = None):
        from officina.web import sfoglia

        geometria = self._geometria()
        larga = int(geometria.get("larga") or MISURA_PRINCIPALE[0])
        alta = int(geometria.get("alta") or MISURA_PRINCIPALE[1])
        opzioni = dict(width=max(larga, MINIMA_PRINCIPALE[0]),
                       height=max(alta, MINIMA_PRINCIPALE[1]),
                       min_size=MINIMA_PRINCIPALE, background_color=fondo_della_finestra(),
                       js_api=PontePrincipale(self),
                       maximized=bool(geometria.get("massimizzata")),
                       text_select=True)
        if geometria.get("x") is not None and geometria.get("y") is not None:
            opzioni.update(x=int(geometria["x"]), y=int(geometria["y"]))
        else:
            opzioni.update(self._schermo())
        if indirizzo:
            opzioni["url"] = indirizzo
        else:
            opzioni["html"] = pagine.attesa(self.apertura["titolo"], self.apertura["detto"],
                                            versione=self.versione)
        finestra = self.webview.create_window(NOME, **opzioni)
        finestra.events.closing += self._quando_chiude
        finestra.events.loaded += self._accendi_i_tasti_del_browser
        finestra.events.maximized += lambda: self._segna_massimizzata(True)
        finestra.events.restored += lambda: self._segna_massimizzata(False)
        self.principale = finestra
        sfoglia.imposta_chi_sceglie(self.scegli_cartella)
        return finestra

    def _impostazioni_di_webview2(self, cosa):
        if sys.platform != "win32" or self.principale is None:
            return None
        from System import Func, Type

        forma = self.principale.native
        esito: dict = {}

        def dentro():
            try:
                esito["valore"] = cosa(forma.webview.CoreWebView2)
            except Exception as guasto:
                esito["guasto"] = guasto

        forma.Invoke(Func[Type](dentro))
        if "guasto" in esito:
            raise esito["guasto"]
        return esito.get("valore")

    def _accendi_i_tasti_del_browser(self) -> None:
        def accendi(nucleo):
            nucleo.Settings.AreBrowserAcceleratorKeysEnabled = True
            if not self._richieste_libere:
                from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext

                nucleo.RemoveWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All)
                self._richieste_libere = True
            return True

        try:
            self._impostazioni_di_webview2(accendi)
            self.guasto_dei_tasti = ""
        except Exception as guasto:
            self.guasto_dei_tasti = f"{type(guasto).__name__}: {guasto}"
            registro.avviso("programma.tasti_non_accesi", **registro.dove_si_e_rotto(guasto))

    def tasti_del_browser_accesi(self) -> bool | None:
        try:
            risposta = self._impostazioni_di_webview2(
                lambda nucleo: bool(nucleo.Settings.AreBrowserAcceleratorKeysEnabled))
        except Exception as guasto:
            self.guasto_dei_tasti = f"{type(guasto).__name__}: {guasto}"
            return None
        return None if risposta is None else bool(risposta)

    def _segna_massimizzata(self, si: bool) -> None:
        self._massimizzata = si

    def _mostra_la_principale(self, indirizzo: str) -> None:
        if self.principale is None:
            self.crea_la_principale(indirizzo)
        else:
            self.principale.load_url(indirizzo)
        if self.finestrina is not None:
            self.principale.events.loaded.wait(ATTESA_DELLA_PRINCIPALE)
            vecchia, self.finestrina = self.finestrina, None
            vecchia.destroy()
        threading.Thread(target=self._guarda_gli_aggiornamenti, name="aggiornamenti",
                         daemon=True).start()

    def crea_la_finestrina(self):
        larga, alta = MISURA_FINESTRINA
        finestra = self.webview.create_window(
            NOME, html=pagine.finestrina(self.versione), js_api=PonteFinestrina(self),
            width=larga, height=alta, resizable=False, background_color=fondo_della_finestra(),
            **self._schermo())
        finestra.events.closing += self._quando_chiude_la_finestrina
        self.finestrina = finestra
        return finestra

    def _quando_chiude_la_finestrina(self) -> bool:
        if self.principale is None:
            self.installatore.ferma()
        return True
