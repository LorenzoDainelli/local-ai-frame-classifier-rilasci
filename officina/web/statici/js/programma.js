import { chiediSeSi } from "/statici/js/finestrina.js";

const DAL_FISSO = new Set(["stato_del_programma", "come_vanno_i_motori", "prepara_i_motori",
    "salva_la_chiave", "togli_la_chiave", "aggiornamento", "aggiorna_adesso",
    "rifiuta_aggiornamento", "apri_l_archivio_sicuro"]);
const locale = () => window.pywebview && window.pywebview.api;
let fisso = null;

async function chiediAlFisso(azione, argomenti) {
    const risposta = await fetch(`/api/programma/${azione}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(argomenti),
    });
    if (!risposta.ok) throw new Error(String(risposta.status));
    return risposta.json();
}

const api = () => fisso || locale();

export const nelProgramma = () => Boolean(api());

export async function apriLArchivioSicuro(password) {
    try {
        return await api().apri_l_archivio_sicuro(password);
    } catch (guasto) {
        return { errore: "Qualcosa è andato storto. Riprova." };
    }
}

async function guardaSeEIlFisso() {
    try {
        await chiediAlFisso("aggiornamento", []);
    } catch (errore) {
        return;
    }
    fisso = new Proxy({}, {
        get: (_, nome) => DAL_FISSO.has(nome)
            ? (...argomenti) => chiediAlFisso(nome, argomenti).catch(() => ({ errore: "Il fisso non risponde." }))
            : locale()[nome],
    });
}

const dentro = (chi) => document.querySelector(`[data-programma="${chi}"]`);
const tasto = (chi) => document.querySelector(`[data-programma-fai="${chi}"]`);

function gb(byte) {
    return `${(byte / 1073741824).toFixed(2).replace(".", ",")} GB`;
}

function scrivi(chi, testo) {
    const dove = dentro(chi);
    if (dove) dove.textContent = testo;
}

function nomeDellaVersione(versione) {
    const beta = /-beta\.?(\d+)$/.exec(versione || "");
    return beta ? `beta ${beta[1]}` : `versione ${versione}`;
}

let strisciaRimandata = null;

function aggiornamentoAParole(a) {
    if (a.canale === "sviluppo") {
        return "Questa copia gira dal codice: non si aggiorna da sola.";
    }
    if (a.fase === "scarico") {
        return a.totale ? `Scarico: ${gb(a.fatti)} di ${gb(a.totale)}.` : "Scarico l'aggiornamento.";
    }
    if (a.fase === "installo") return "Scaricato. Il programma si chiude e si aggiorna.";
    if (a.fase === "pronto_alla_prossima" && a.trovato) {
        return `È pronta la ${nomeDellaVersione(a.trovato.versione)}: riavvia ora, oppure si installa da sola quando chiudi.`;
    }
    if (a.fase === "guasto") return a.guasto;
    if (a.trovato) return `È pronta la versione ${a.trovato.versione}.`;
    if (a.in_sospeso) return `In sospeso: la versione ${a.in_sospeso.versione}, che avevi rifiutato.`;
    if (a.canale === "beta") return "Durante la prova si aggiorna da solo.";
    return "Nessun aggiornamento.";
}

function motoriAParole(m) {
    if (m.lavora) return "Li sto preparando.";
    if (m.mancano.length && m.riavvio) {
        return "C'è una versione nuova dei motori: si prepara la prossima volta che apri il programma.";
    }
    if (m.mancano.length && m.vecchio) {
        return `Quello che hai (torch ${m.vecchio}) è troppo vecchio per aprire i pesi in sicurezza: va scaricato quello nuovo, ${m.quanto}.`;
    }
    if (m.mancano.length) {
        return `Non ci sono ancora: senza, il programma lavora senza i modelli grandi. Da scaricare: ${m.quanto}.`;
    }
    const dove = m.variante === "cpu" ? "sul processore" : `sulla scheda video${m.scheda ? ` (${m.scheda})` : ""}`;
    return `Pronti: i modelli girano ${dove}.`;
}

function chiaveAParole(s) {
    if (s.chiave_dall_ambiente) return "C'è, e arriva dalla variabile HF_TOKEN di questo computer.";
    if (s.chiave) return "C'è, custodita nel Gestore credenziali di Windows.";
    return "Non c'è. Serve solo per scaricare DINOv3.";
}

async function riempi() {
    const stato = await api().stato_del_programma();
    if (!stato || stato.errore) return;
    scrivi("versione", `${stato.versione} · ${stato.canale}`);
    scrivi("aggiornamento", aggiornamentoAParole(stato.aggiornamento));
    const a = stato.aggiornamento;
    tasto("aggiorna").hidden = !(a.trovato || a.in_sospeso)
        || (a.canale === "beta" && a.fase !== "pronto_alla_prossima")
        || ["scarico", "installo"].includes(a.fase);
    scrivi("motori", motoriAParole(stato.motori));
    tasto("motori").hidden = !stato.motori.mancano.length || stato.motori.lavora || stato.motori.riavvio;
    scrivi("chiave", chiaveAParole(stato));
    tasto("togli-chiave").hidden = !stato.chiave || stato.chiave_dall_ambiente;
    dentro("campo-chiave").hidden = stato.chiave;
    return stato;
}

function seguiIMotori() {
    const barra = dentro("barra-motori");
    const giro = setInterval(async () => {
        const m = await api().come_vanno_i_motori();
        barra.hidden = !m.totale;
        barra.querySelector(".fatto").style.width = `${m.percento || 0}%`;
        if (m.fase === "guasto") {
            scrivi("motori", m.guasto);
        } else if (m.totale) {
            scrivi("motori", `${m.detto || "Scarico."} ${gb(m.fatti)} di ${gb(m.totale)}.`);
        } else if (m.detto) {
            scrivi("motori", m.detto);
        }
        if (["finito", "guasto", "fermo"].includes(m.fase)) {
            clearInterval(giro);
            barra.hidden = true;
            if (m.fase !== "guasto") riempi();
        }
    }, 500);
}

function seguiLAggiornamento() {
    const giro = setInterval(async () => {
        const a = await api().aggiornamento();
        mostraLaStriscia(a);
        if (dentro("aggiornamento")) scrivi("aggiornamento", aggiornamentoAParole(a));
        if (a.fase !== "scarico") clearInterval(giro);
    }, 500);
}

function mostraLaStriscia(a) {
    const striscia = document.getElementById("striscia-aggiornamento");
    if (!striscia || !a) return;
    const finale = a.canale === "finale" && a.trovato
        && ["da_chiedere", "scarico", "installo", "guasto"].includes(a.fase);
    const beta = a.canale === "beta" && a.trovato && ["pronto_alla_prossima", "installo"].includes(a.fase)
        && strisciaRimandata !== a.trovato.versione;
    const daMostrare = finale || beta;
    const eraNascosta = striscia.hidden;
    striscia.hidden = !daMostrare;
    if (!daMostrare) return;
    if (eraNascosta) window.movimenti?.strisciaScende?.(striscia);
    striscia.dataset.canale = a.canale;
    striscia.dataset.versione = a.trovato.versione;
    striscia.querySelector('[data-aggiornamento="testo"]').textContent = aggiornamentoAParole(a);
    striscia.querySelector('[data-aggiornamento="aggiorna"]').textContent = beta ? "Riavvia ora" : "Aggiorna";
    striscia.querySelector('[data-aggiornamento="rifiuta"]').textContent = beta ? "Dopo" : "Rifiuta";
    const lavora = ["scarico", "installo"].includes(a.fase);
    striscia.querySelectorAll("button").forEach((b) => { b.hidden = lavora; });
}

async function aggiorna() {
    const a = await api().aggiorna_adesso();
    if (a && a.errore) {
        scrivi("aggiornamento", a.errore);
        return;
    }
    seguiLAggiornamento();
}

function mostraLErrore(modulo, testo) {
    let avviso = modulo.querySelector("[data-errore-del-ponte]");
    if (!avviso) {
        avviso = document.createElement("div");
        avviso.className = "avviso forte";
        avviso.setAttribute("data-errore-del-ponte", "");
        avviso.setAttribute("role", "alert");
        modulo.prepend(avviso);
    }
    avviso.textContent = testo;
}

function passwordDalPonte() {
    const forziere = document.getElementById("modulo-forziere");
    if (forziere) {
        forziere.addEventListener("submit", async (evento) => {
            evento.preventDefault();
            const dati = new FormData(forziere);
            const campi = forziere.querySelectorAll('input[type="password"]');
            const esito = await api().accendi_il_forziere(
                String(dati.get("password") || ""), String(dati.get("ancora") || ""),
                dati.get("su_carta") === "1", String(dati.get("dove_torno") || ""));
            campi.forEach((campo) => { campo.value = ""; });
            if (esito && esito.errore) { mostraLErrore(forziere, esito.errore); return; }
            if (window.movimenti?.forziereAcceso) await window.movimenti.forziereAcceso();
            window.location.href = (esito && esito.vai) || "/";
        });
    }
    const sicuro = document.getElementById("modulo-archivio-sicuro");
    if (sicuro) {
        sicuro.addEventListener("submit", async (evento) => {
            evento.preventDefault();
            const campo = sicuro.querySelector('input[type="password"]');
            const tasto = sicuro.querySelector('button[type="submit"]');
            const valore = campo.value;
            campo.value = "";
            tasto.disabled = true;
            const esito = await api().apri_l_archivio_sicuro(valore);
            tasto.disabled = false;
            if (esito && esito.errore) {
                mostraLErrore(sicuro, esito.errore);
                campo.focus();
                return;
            }
            window.location.reload();
        });
    }
    const spegni = document.getElementById("modulo-spegni-forziere");
    if (spegni) {
        spegni.addEventListener("submit", async (evento) => {
            evento.preventDefault();
            const campo = spegni.querySelector('input[type="password"]');
            const spengo = await chiediSeSi({
                titolo: "Spengo il forziere?",
                sotto: "L'archivio torna una cartella senza password: chi usa il computer può aprire le foto.",
                tasto: "Tieni premuto per spegnere", annulla: "Lascia acceso", pericolo: true,
            });
            const valore = campo.value;
            campo.value = "";
            if (!spengo) return;
            const esito = await api().spegni_il_forziere(valore);
            if (esito && esito.errore) { mostraLErrore(spegni, esito.errore); return; }
            window.location.href = (esito && esito.vai) || "/impostazioni#c6";
        });
    }
    const conWindows = document.querySelector("[data-rientra-windows]");
    if (conWindows) {
        const prova = async () => {
            if (!api() || !api().rientra_con_windows) return;
            conWindows.disabled = true;
            const esito = await api().rientra_con_windows();
            conWindows.disabled = false;
            if (esito && esito.errore) {
                let avviso = document.querySelector(".avviso-blocco");
                if (!avviso) {
                    avviso = document.createElement("p");
                    avviso.className = "avviso-blocco";
                    avviso.setAttribute("role", "alert");
                    conWindows.parentElement.append(avviso);
                }
                avviso.textContent = esito.errore;
                return;
            }
            if (window.movimenti) await window.movimenti.apriArchivio();
            window.location.href = (esito && esito.vai) || "/";
        };
        conWindows.addEventListener("click", prova);
    }
    const blocco = document.querySelector("form.modulo-blocco");
    if (blocco) {
        blocco.addEventListener("submit", async (evento) => {
            evento.preventDefault();
            const campo = blocco.querySelector('input[type="password"]');
            const valore = campo.value;
            campo.value = "";
            const esito = await api().rientra(valore);
            if (esito && esito.errore) {
                if (window.movimenti) {
                    window.movimenti.passwordSbagliata(campo);
                    let avviso = document.querySelector(".avviso-blocco");
                    if (!avviso) {
                        avviso = document.createElement("p");
                        avviso.className = "avviso-blocco";
                        avviso.setAttribute("role", "alert");
                        blocco.after(avviso);
                    }
                    avviso.textContent = "Non è quella. Riprova.";
                    campo.focus();
                    return;
                }
                window.location.href = "/blocco?sbagliata=1";
                return;
            }
            if (window.movimenti) await window.movimenti.apriArchivio();
            window.location.href = (esito && esito.vai) || "/";
        });
    }
}

const PAROLE_DELLA_FORZA = ["troppo corta", "debole", "così così", "discreta", "buona",
                            "molto buona", "forte", "fortissima"];

export function forzaDellaPassword(password) {
    if (!password) return 0;
    let punti = Math.min(password.length, 24) / 3;
    const tipi = [/[a-zà-ù]/, /[A-ZÀ-Ù]/, /\d/, /[^A-Za-z0-9à-ùÀ-Ù]/].filter((tipo) => tipo.test(password)).length;
    punti += (tipi - 1) * 0.75;
    if (/(.)\1\1/.test(password)) punti -= 1;
    if (/^(password|12345678|qwerty|abcdefgh)/i.test(password)) punti = 1;
    if (password.length < 12) punti = Math.min(punti, 1);
    return Math.max(1, Math.min(8, Math.round(punti)));
}

function misuraLaForza() {
    const campo = document.querySelector("[data-misura-forza]");
    const zona = document.querySelector("[data-forza]");
    if (!campo || !zona) return;
    const riempie = zona.querySelector("[data-forza-riempie]");
    const parola = zona.querySelector("[data-forza-parola]");
    let prima = 0;
    campo.addEventListener("input", () => {
        const livello = forzaDellaPassword(campo.value);
        zona.hidden = livello === 0;
        if (livello === prima) return;
        const colore = `hsl(${Math.round(4 + (livello - 1) * 17)} 62% 48%)`;
        const dopo = { transform: `scaleX(${livello / 8})`, backgroundColor: colore };
        if (window.movimenti?.acceso()) {
            window.movimenti.anima(riempie, [{ transform: `scaleX(${prima / 8})`, backgroundColor: getComputedStyle(riempie).backgroundColor }, dopo],
                                   { e: "viva", f: "none" });
        }
        Object.assign(riempie.style, dopo);
        parola.textContent = livello ? PAROLE_DELLA_FORZA[livello - 1] : "";
        parola.style.color = colore;
        prima = livello;
    });
}

misuraLaForza();

function collega() {
    document.querySelectorAll("[data-solo-nel-programma]").forEach((e) => { e.hidden = false; });
    passwordDalPonte();
    window.chiediDiChiudere = (testo) => {
        chiediSeSi({ titolo: "Chiudo il programma?", sotto: testo, tasto: "Chiudi", annulla: "Resta aperto" })
            .then((si) => { if (si) api().chiudi_comunque(); });
        return true;
    };

    const striscia = document.getElementById("striscia-aggiornamento");
    if (striscia) {
        striscia.querySelector('[data-aggiornamento="aggiorna"]').addEventListener("click", aggiorna);
        striscia.querySelector('[data-aggiornamento="rifiuta"]').addEventListener("click", async () => {
            if (striscia.dataset.canale === "beta") {
                strisciaRimandata = striscia.dataset.versione;
                striscia.hidden = true;
                return;
            }
            const a = await api().rifiuta_aggiornamento();
            mostraLaStriscia(a);
            if (dentro("aggiornamento")) riempi();
        });
        api().aggiornamento().then(mostraLaStriscia);
        setInterval(() => { api().aggiornamento().then(mostraLaStriscia).catch(() => {}); }, 30000);
    }

    if (!dentro("versione")) {
        if (dentro("campo-chiave")) collegaLaChiave();
        return;
    }
    riempi().then((stato) => { if (stato && stato.motori.lavora) seguiIMotori(); });
    tasto("aggiorna").addEventListener("click", aggiorna);
    tasto("motori").addEventListener("click", async () => {
        const m = await api().prepara_i_motori();
        if (m && m.errore) { scrivi("motori", m.errore); return; }
        tasto("motori").hidden = true;
        seguiIMotori();
    });
    tasto("salva-chiave").addEventListener("click", async () => {
        const campo = dentro("nuova-chiave");
        const valore = campo.value;
        campo.value = "";
        const esito = await api().salva_la_chiave(valore);
        if (esito && esito.errore) { scrivi("chiave", esito.errore); return; }
        riempi();
    });
    tasto("togli-chiave").addEventListener("click", async () => {
        await api().togli_la_chiave();
        riempi();
    });
}

async function soloLaChiave() {
    const stato = await api().stato_del_programma();
    if (!stato || stato.errore) return;
    scrivi("chiave", chiaveAParole(stato));
    tasto("togli-chiave").hidden = !stato.chiave || stato.chiave_dall_ambiente;
    dentro("campo-chiave").hidden = stato.chiave;
}

function collegaLaChiave() {
    soloLaChiave();
    tasto("salva-chiave").addEventListener("click", async () => {
        const campo = dentro("nuova-chiave");
        const valore = campo.value;
        campo.value = "";
        const esito = await api().salva_la_chiave(valore);
        if (esito && esito.errore) { scrivi("chiave", esito.errore); return; }
        soloLaChiave();
    });
    tasto("togli-chiave").addEventListener("click", async () => {
        await api().togli_la_chiave();
        soloLaChiave();
    });
}

async function parti() {
    await guardaSeEIlFisso();
    collega();
}

if (locale()) {
    parti();
} else {
    window.addEventListener("pywebviewready", parti, { once: true });
}
