import { chiedi, leggiDatiIncorporati, manda, mandaModulo, numeroAParole, quandoSiFerma, scattiAParole, siStaScrivendo } from "/statici/js/comune.js";

const $ = (id) => document.getElementById(id);
const CHIAVE_VISTA = "officina.luoghi.vista";
const CHIAVE_ORDINE = "officina.luoghi.ordine";
const CHIAVE_CHIUSI = "officina.luoghi.chiusi";
const MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
    "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const SEPARATORE = " › ";

const iniziali = leggiDatiIncorporati("lu-dati") || {};
let luoghi = iniziali.luoghi || [];
let perId = new Map();
let perPercorso = new Map();
let scelto = null;
let filtro = "tutti";
let ordine = leggi(CHIAVE_ORDINE, "albero");
let chiusi = new Set(JSON.parse(leggi(CHIAVE_CHIUSI, "[]")).map(Number));
let azioneAperta = null;
let richiestaScheda = null;

function leggi(chiave, predefinito) {
    try { return window.localStorage.getItem(chiave) || predefinito; } catch (errore) { return predefinito; }
}

function scrivi(chiave, valore) {
    try { window.localStorage.setItem(chiave, valore); } catch (errore) {  }
}

function nomeCompleto(voce) {
    return voce.percorso ? `${voce.percorso}${SEPARATORE}${voce.nome}` : voce.nome;
}

function semplice(testo) {
    return String(testo || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase("it-IT");
}

function giornoAParole(giorno, conIlNome = false) {
    if (!giorno) return "";
    const [anno, mese, di] = giorno.split("-").map(Number);
    if (!anno || !mese || !di) return giorno;
    if (conIlNome) {
        const data = new Date(anno, mese - 1, di);
        const nome = data.toLocaleDateString("it-IT", { weekday: "long" });
        return `${nome} ${di} ${MESI[mese - 1]} ${anno}`;
    }
    return `${di} ${MESI[mese - 1]} ${anno}`;
}

function periodoBreve(voce) {
    if (!voce.dal) return "";
    const da = voce.dal.slice(0, 4);
    const a = voce.al ? voce.al.slice(0, 4) : da;
    return da === a ? da : `${da} – ${a}`;
}

function crea(tag, classe, testo) {
    const elemento = document.createElement(tag);
    if (classe) elemento.className = classe;
    if (testo !== undefined && testo !== null) elemento.textContent = testo;
    return elemento;
}

function avvisa(testo, male = false, mossa = null) {
    const esito = $("lu-esito");
    esito.replaceChildren(crea("span", "", testo));
    if (mossa) {
        const tasto = crea("button", "tasto-comando nudo piccolo lu-annulla", "Annulla");
        tasto.type = "button";
        tasto.dataset.annulla = String(mossa);
        esito.append(tasto);
    }
    esito.classList.toggle("male", male);
    esito.hidden = !testo;
    clearTimeout(avvisa.timer);
    if (testo) avvisa.timer = setTimeout(() => { esito.hidden = true; }, mossa ? 20000 : (male ? 9000 : 5000));
}

function comeTornato(esito) {
    const parti = [esito.rimessi ? `${scattiAParole(esito.rimessi)} ${esito.rimessi === 1 ? "è tornato" : "sono tornati"} com'erano.` : "Annullato."];
    if (esito.rimasti) {
        parti.push(`${scattiAParole(esito.rimasti)} nel frattempo ${esito.rimasti === 1 ? "è stato cambiato" : "sono stati cambiati"}: ${esito.rimasti === 1 ? "resta" : "restano"} dove li hai messi.`);
    }
    return parti.join(" ");
}

async function annulla(mossa, tasto) {
    if (tasto) tasto.disabled = true;
    try {
        const esito = await mandaModulo("/api/luoghi/annulla", { mossa });
        avvisa(comeTornato(esito));
        const torna = esito.genere === "unione" && esito.da_id ? esito.da_id : scelto;
        await ricarica(torna);
        caricaLeGiornate(false);
    } catch (errore) {
        avvisa(errore.message || "Non sono riuscito ad annullare.", true);
        if (tasto) tasto.disabled = false;
    }
}

$("lu-esito").addEventListener("click", (evento) => {
    const tasto = evento.target.closest("[data-annulla]");
    if (tasto) annulla(Number(tasto.dataset.annulla), tasto);
});

function indicizza() {
    perId = new Map(luoghi.map((voce) => [voce.id, voce]));
    perPercorso = new Map();
    const elenco = $("lu-tutti");
    elenco.replaceChildren();
    for (const voce of luoghi) {
        const completo = nomeCompleto(voce);
        perPercorso.set(semplice(completo), voce.id);
        if (!perPercorso.has(semplice(voce.nome))) perPercorso.set(semplice(voce.nome), voce.id);
        const scelta = document.createElement("option");
        scelta.value = completo;
        elenco.append(scelta);
    }
}

function luogoScritto(testo) {
    const pulito = semplice(String(testo || "").trim());
    if (!pulito) return null;
    if (perPercorso.has(pulito)) return perPercorso.get(pulito);
    const simili = luoghi.filter((voce) => semplice(voce.nome) === pulito);
    return simili.length === 1 ? simili[0].id : undefined;
}

function aggiornaIConti(conti) {
    if (!conti) return;
    for (const elemento of document.querySelectorAll("[data-conto]")) {
        const valore = conti[elemento.dataset.conto];
        if (valore !== undefined) elemento.textContent = numeroAParole(valore);
    }
}

function nascostoDaUnPadre(voce) {
    let padre = voce.genitore;
    const visti = new Set();
    while (padre !== null && padre !== undefined && !visti.has(padre)) {
        if (chiusi.has(padre)) return true;
        visti.add(padre);
        padre = perId.get(padre)?.genitore ?? null;
    }
    return false;
}

function passaIlFiltro(voce) {
    if (filtro === "senza-gps") return !voce.coordinate;
    if (filtro === "vuoti") return voce.scatti === 0;
    return true;
}

function daMostrare() {
    const parole = semplice($("lu-cerca").value).split(/\s+/).filter(Boolean);
    const cerca = parole.length > 0;
    let elenco = luoghi.filter((voce) => passaIlFiltro(voce)
        && parole.every((parola) => semplice(nomeCompleto(voce)).includes(parola)));
    const piatto = cerca || filtro !== "tutti" || ordine !== "albero";
    if (!piatto) return { elenco: elenco.filter((voce) => !nascostoDaUnPadre(voce)), piatto };
    const confronti = {
        scatti: (a, b) => b.scatti - a.scatti || a.nome.localeCompare(b.nome, "it"),
        nome: (a, b) => a.nome.localeCompare(b.nome, "it") || a.percorso.localeCompare(b.percorso, "it"),
        recenti: (a, b) => (b.al || "").localeCompare(a.al || "") || b.scatti - a.scatti,
        vecchi: (a, b) => ((a.dal || "9999").localeCompare(b.dal || "9999")) || b.scatti - a.scatti,
    };
    if (confronti[ordine]) elenco = [...elenco].sort(confronti[ordine]);
    return { elenco, piatto };
}

function riga(voce, piatto) {
    const bottone = crea("div", "lu-riga");
    bottone.setAttribute("role", "option");
    bottone.dataset.id = String(voce.id);
    bottone.setAttribute("aria-selected", voce.id === scelto ? "true" : "false");
    bottone.style.setProperty("--prof", piatto ? 0 : voce.profondita);
    const freccia = crea("button", "lu-freccia");
    freccia.type = "button";
    if (!piatto && voce.figli) {
        const chiuso = chiusi.has(voce.id);
        freccia.setAttribute("aria-label", chiuso ? `Apri ${voce.nome}` : `Chiudi ${voce.nome}`);
        freccia.setAttribute("aria-expanded", chiuso ? "false" : "true");
        freccia.dataset.apriChiudi = String(voce.id);
    } else {
        freccia.disabled = true;
        freccia.setAttribute("aria-hidden", "true");
        freccia.classList.add("vuota");
    }
    const copertina = crea("span", "lu-copertina");
    if (voce.copertina) {
        const foto = document.createElement("img");
        foto.src = `/miniatura/${Number(voce.copertina)}`;
        foto.alt = "";
        foto.loading = "lazy";
        foto.decoding = "async";
        copertina.append(foto);
    }
    const nomi = crea("span", "lu-nomi");
    nomi.append(crea("b", "", voce.nome));
    if (piatto && voce.percorso) nomi.append(crea("span", "minuscolo tenue", voce.percorso));
    else if (voce.figli) nomi.append(crea("span", "minuscolo tenue", `${voce.figli} ${voce.figli === 1 ? "luogo" : "luoghi"} dentro`));
    const quando = crea("span", "lu-quando minuscolo tenue numeri", periodoBreve(voce));
    const dove = crea("span", "lu-gps bollino");
    if (!voce.coordinate) {
        dove.classList.add("attenzione");
        dove.title = "Senza coordinate";
    } else if (voce.coordinate.da === "padre") {
        dove.title = `Usa le coordinate di ${voce.coordinate.padre}`;
    } else {
        dove.classList.add("bene");
        dove.title = "Ha le sue coordinate";
    }
    const quanti = crea("span", "lu-quanti numeri", numeroAParole(voce.scatti));
    if (!voce.scatti) quanti.classList.add("tenue");
    bottone.append(freccia, copertina, nomi, quando, dove, quanti);
    return bottone;
}

function disegnaLElenco() {
    const { elenco, piatto } = daMostrare();
    const contenitore = $("lu-elenco");
    const frammento = document.createDocumentFragment();
    for (const voce of elenco) frammento.append(riga(voce, piatto));
    contenitore.replaceChildren(frammento);
    const vuoto = $("lu-vuoto");
    if (!luoghi.length) {
        vuoto.textContent = "Nessun luogo, ancora. Premi «Nuovo luogo» per cominciare, oppure trasforma un albero che hai già.";
    } else if (!elenco.length) {
        vuoto.textContent = $("lu-cerca").value.trim()
            ? `Nessun luogo si chiama «${$("lu-cerca").value.trim()}».`
            : "Nessun luogo in questo gruppo.";
    }
    vuoto.hidden = elenco.length > 0;
}

function mostraNellElenco(id) {
    const elenco = $("lu-elenco");
    const riga = elenco.querySelector(`.lu-riga[data-id="${id}"]`);
    if (!riga) return;
    const sopra = riga.offsetTop;
    if (sopra < elenco.scrollTop) elenco.scrollTop = sopra - 4;
    else if (sopra + riga.offsetHeight > elenco.scrollTop + elenco.clientHeight) {
        elenco.scrollTop = sopra + riga.offsetHeight - elenco.clientHeight + 4;
    }
}

function scegli(id, scorri = false) {
    if (!perId.has(id)) return;
    scelto = id;
    for (const elemento of $("lu-elenco").querySelectorAll(".lu-riga")) {
        elemento.setAttribute("aria-selected", Number(elemento.dataset.id) === id ? "true" : "false");
    }
    if (scorri) mostraNellElenco(id);
    try { history.replaceState(null, "", `#luogo-${id}`); } catch (errore) {  }
    chiudiLAzione();
    caricaLaScheda(id);
}

async function caricaLaScheda(id) {
    const voce = perId.get(id);
    $("lu-scheda-vuota").hidden = true;
    $("lu-scheda-piena").hidden = false;
    $("lu-nome").textContent = voce.nome;
    if (richiestaScheda) richiestaScheda.abort();
    const questa = new AbortController();
    richiestaScheda = questa;
    let dati;
    try {
        dati = await chiedi(`/api/luoghi/luogo/${id}`, { signal: questa.signal });
    } catch (errore) {
        if (errore.name === "AbortError") return;
        avvisa(errore.message, true);
        return;
    }
    if (richiestaScheda !== questa) return;
    richiestaScheda = null;
    disegnaLaScheda(voce, dati);
}

function disegnaLaScheda(voce, dati) {
    const catena = $("lu-catena");
    catena.replaceChildren();
    for (const antenato of dati.catena || []) {
        const salto = crea("button", "lu-salto", antenato.nome);
        salto.type = "button";
        salto.dataset.vai = String(antenato.id);
        catena.append(salto, crea("span", "tenue", SEPARATORE.trim()));
    }
    if (!(dati.catena || []).length) catena.append(crea("span", "tenue", "In cima all'albero"));
    $("lu-nome").textContent = dati.nome;

    const mosaico = $("lu-mosaico");
    mosaico.replaceChildren();
    for (const foto of (dati.ultimi || []).slice(0, 6)) {
        const collegamento = document.createElement("a");
        collegamento.href = `/scatto/${Number(foto.scatto_id)}?luogo=${voce.id}`;
        const immagine = document.createElement("img");
        immagine.src = `/miniatura/${Number(foto.file_id)}`;
        immagine.alt = "";
        immagine.loading = "lazy";
        collegamento.append(immagine);
        mosaico.append(collegamento);
    }
    mosaico.hidden = !mosaico.children.length;

    const fatti = $("lu-fatti");
    fatti.replaceChildren();
    const fatto = (titolo, valore) => {
        const gruppo = crea("div", "");
        gruppo.append(crea("dt", "minuscolo tenue", titolo), crea("dd", "numeri", valore));
        fatti.append(gruppo);
    };
    fatto("Scatti", numeroAParole(dati.scatti));
    if (dati.figli_sotto) fatto("Messi proprio qui", numeroAParole(dati.propri));
    fatto("Luoghi dentro", numeroAParole(dati.figli_sotto));
    if (dati.dal) {
        fatto(dati.dal === dati.al ? "Ci sei stato" : "La prima volta", giornoAParole(dati.dal));
        if (dati.al && dati.al !== dati.dal) fatto("L'ultima volta", giornoAParole(dati.al));
    }

    const anni = $("lu-anni");
    anni.replaceChildren();
    const elencoAnni = dati.anni || [];
    if (elencoAnni.length > 1) {
        const primo = Number(elencoAnni[0].anno);
        const ultimo = Number(elencoAnni[elencoAnni.length - 1].anno);
        const perAnno = new Map(elencoAnni.map((a) => [Number(a.anno), a.quanti]));
        const massimo = Math.max(...elencoAnni.map((a) => a.quanti));
        const colonne = crea("div", "lu-anni-barre");
        for (let anno = primo; anno <= ultimo; anno++) {
            const quanti = perAnno.get(anno) || 0;
            const colonna = document.createElement("a");
            colonna.className = "lu-anno";
            colonna.href = `/?luogo=${voce.id}&dal=${anno}-01-01&al=${anno}-12-31`;
            colonna.title = `${anno}: ${scattiAParole(quanti)}`;
            colonna.setAttribute("aria-label", colonna.title);
            const barra = crea("span", quanti ? "" : "zero");
            barra.style.height = `${quanti ? Math.max(8, Math.round((quanti / massimo) * 100)) : 4}%`;
            colonna.append(barra);
            colonne.append(colonna);
        }
        const larghezza = `min(100%, ${(ultimo - primo + 1) * 30}px)`;
        colonne.style.width = larghezza;
        const righello = crea("div", "lu-anni-righello minuscolo tenue numeri");
        righello.style.width = larghezza;
        anni.append(colonne, righello);
        anni.lastChild.append(crea("span", "", String(primo)), crea("span", "", String(ultimo)));
    }
    anni.hidden = !anni.children.length;

    const dove = $("lu-dove");
    dove.replaceChildren();
    const coordinate = dati.coordinate;
    const sullaMappa = $("lu-mappa-tempo");
    if (coordinate) {
        const testo = `${coordinate.latitudine.toFixed(5)}, ${coordinate.longitudine.toFixed(5)}`;
        const origine = {
            foto: `prese dal GPS delle sue foto${coordinate.raggio_metri ? `, in un raggio di ${numeroAParole(Math.round(coordinate.raggio_metri))} m` : ""}`,
            a_mano: "scritte da te",
            scatto: "prese da una foto",
            padre: `quelle di ${coordinate.padre}`,
        }[coordinate.da] || "";
        const pallino = crea("span", `bollino ${coordinate.da === "padre" ? "" : "bene"}`, testo);
        dove.append(pallino, crea("span", "minuscolo tenue", origine));
        sullaMappa.href = `/tempo?posto=${coordinate.da === "padre" ? "" : voce.id}`;
        sullaMappa.hidden = coordinate.da === "padre";
    } else {
        dove.append(crea("span", "bollino attenzione", "Non so dov'è"),
            crea("span", "minuscolo tenue", "Dagli le coordinate, o metti qui qualche foto col GPS."));
        sullaMappa.hidden = true;
    }

    const figli = $("lu-figli");
    figli.replaceChildren();
    if ((dati.figli || []).length) {
        figli.append(crea("span", "minuscolo tenue", "Dentro:"));
        for (const figlio of dati.figli) {
            const salto = crea("button", "lu-salto", figlio.nome);
            salto.type = "button";
            salto.dataset.vai = String(figlio.id);
            figli.append(salto);
        }
    }
    figli.hidden = !figli.children.length;

    const unioni = $("lu-unioni");
    unioni.replaceChildren();
    if ((dati.unioni || []).length) {
        unioni.append(crea("span", "minuscolo tenue", "Unioni fatte qui:"));
        for (const unione of dati.unioni) {
            const riga = crea("div", "lu-unione");
            const quando = unione.fatta_il ? giornoAParole(unione.fatta_il.slice(0, 10)) : "";
            const testo = crea("span", "lu-unione-testo");
            testo.append(crea("span", "piccolo", `«${unione.da || "un luogo"}»`),
                crea("span", "minuscolo tenue", [quando, unione.scatti ? scattiAParole(unione.scatti) : ""].filter(Boolean).join(" · ")));
            const tasto = crea("button", "tasto-comando nudo piccolo", "Annulla");
            tasto.type = "button";
            tasto.dataset.annullaUnione = String(unione.id);
            tasto.title = `Rimette «${unione.da || "il luogo"}» e i suoi scatti com'erano prima dell'unione`;
            riga.append(testo, tasto);
            unioni.append(riga);
        }
    }
    unioni.hidden = !unioni.children.length;
    $("lu-galleria").href = `/?luogo=${voce.id}`;
    $("lu-galleria").classList.toggle("disattivo", !dati.scatti);
}

const AZIONI = {
    rinomina: {
        testo: (voce) => `Nuovo nome per «${voce.nome}»`,
        valore: (voce) => voce.nome,
        bottone: "Cambia nome",
        fai: async (voce, scritto) => {
            await mandaModulo("/api/luoghi/rinomina", { nodo_id: voce.id, nome: scritto });
            return `Ora si chiama «${scritto.trim()}».`;
        },
    },
    dentro: {
        testo: (voce) => `Nome del luogo dentro «${voce.nome}»`,
        segnaposto: "Per esempio Cucina",
        bottone: "Aggiungi",
        fai: async (voce, scritto) => {
            const nuovo = await mandaModulo("/api/luoghi/crea", { nome: scritto, genitore_id: voce.id });
            return { testo: `Aggiunto «${nuovo.nome}».`, vai: nuovo.nodo_id };
        },
    },
    sposta: {
        testo: (voce) => `Dove metto «${voce.nome}»? Con tutto quello che c'è dentro.`,
        segnaposto: "Scrivi il luogo che lo contiene, vuoto = in cima",
        lista: true,
        bottone: "Sposta",
        fai: async (voce, scritto) => {
            const verso = scritto.trim() ? luogoScritto(scritto) : null;
            if (verso === undefined) throw new Error("Non trovo questo luogo: sceglilo dall'elenco che compare mentre scrivi.");
            await mandaModulo("/api/luoghi/sposta", { nodo_id: voce.id, come: verso ? "figlio" : "radice", destinazione: verso || "" });
            return verso ? `Ora sta dentro «${perId.get(verso).nome}».` : "Ora sta in cima all'albero.";
        },
    },
    unisci: {
        testo: (voce) => `Con quale luogo unisco «${voce.nome}»? Le sue foto e i luoghi dentro passano a quello, e «${voce.nome}» va nel cestino.`,
        segnaposto: "Il luogo che resta",
        lista: true,
        bottone: "Unisci",
        conferma: true,
        fai: async (voce, scritto) => {
            const verso = luogoScritto(scritto);
            if (!verso) throw new Error("Non trovo questo luogo: sceglilo dall'elenco che compare mentre scrivi.");
            const esito = await mandaModulo("/api/luoghi/unisci", { da: voce.id, verso });
            return { testo: `Fatto: ${scattiAParole(esito.scatti)} ora stanno in «${esito.percorso}».`, vai: verso, mossa: esito.mossa };
        },
    },
    coordinate: {
        testo: (voce) => `Le coordinate di «${voce.nome}», come le trovi su una mappa`,
        segnaposto: "43.77, 11.25",
        valore: (voce) => (voce.coordinate && voce.coordinate.da !== "padre"
            ? `${voce.coordinate.latitudine.toFixed(6)}, ${voce.coordinate.longitudine.toFixed(6)}` : ""),
        nota: "Due numeri separati da una virgola: prima la latitudine, poi la longitudine.",
        bottone: "Salva",
        fai: async (voce, scritto) => {
            await mandaModulo("/api/luoghi/coordinate", { nodo_id: voce.id, coordinate: scritto });
            return "Coordinate salvate.";
        },
    },
    togli: {
        testo: (voce) => (voce.figli
            ? `Tolgo «${voce.nome}» e i ${voce.figli === 1 ? "luogo" : "luoghi"} dentro? Gli scatti restano, senza questo luogo.`
            : `Tolgo «${voce.nome}»? Gli scatti restano, senza questo luogo.`),
        senzaCampo: true,
        bottone: "Sì, togli",
        fai: async (voce) => {
            await mandaModulo("/api/luoghi/cestina", { nodo_id: voce.id });
            return { testo: `«${voce.nome}» è nel cestino dell'albero.`, vai: voce.genitore };
        },
    },
};

function apriLAzione(nome) {
    const voce = perId.get(scelto);
    const azione = AZIONI[nome];
    if (!voce || !azione) return;
    azioneAperta = { nome, confermata: false };
    const pannello = $("lu-pannello");
    const campo = $("lu-pannello-campo");
    $("lu-pannello-testo").textContent = azione.testo(voce);
    $("lu-pannello-nota").textContent = azione.nota || "";
    $("lu-pannello-nota").hidden = !azione.nota;
    $("lu-pannello-si").textContent = azione.bottone;
    $("lu-pannello-si").classList.toggle("pericolo", nome === "togli");
    campo.hidden = Boolean(azione.senzaCampo);
    campo.required = !azione.senzaCampo && nome !== "sposta" && nome !== "coordinate";
    campo.value = azione.valore ? azione.valore(voce) : "";
    campo.placeholder = azione.segnaposto || "";
    campo.setAttribute("aria-label", azione.testo(voce));
    if (azione.lista) campo.setAttribute("list", "lu-tutti"); else campo.removeAttribute("list");
    pannello.hidden = false;
    for (const tasto of document.querySelectorAll("[data-azione]")) {
        tasto.setAttribute("aria-pressed", tasto.dataset.azione === nome ? "true" : "false");
    }
    if (azione.senzaCampo) $("lu-pannello-si").focus();
    else { campo.focus(); campo.select(); }
}

function chiudiLAzione() {
    azioneAperta = null;
    $("lu-pannello").hidden = true;
    for (const tasto of document.querySelectorAll("[data-azione]")) tasto.setAttribute("aria-pressed", "false");
}

async function faiLAzione() {
    if (!azioneAperta) return;
    const voce = perId.get(scelto);
    const azione = AZIONI[azioneAperta.nome];
    const scritto = $("lu-pannello-campo").value;
    if (azione.conferma && !azioneAperta.confermata) {
        const verso = luogoScritto(scritto);
        if (!verso) { avvisa("Non trovo questo luogo: sceglilo dall'elenco che compare mentre scrivi.", true); return; }
        azioneAperta.confermata = true;
        $("lu-pannello-testo").textContent = `Sicuro? «${voce.nome}» si unisce a «${nomeCompleto(perId.get(verso))}». Potrai annullare subito dopo, oppure più avanti dalla scheda di «${perId.get(verso).nome}».`;
        $("lu-pannello-si").textContent = "Sì, unisci";
        $("lu-pannello-si").classList.add("pericolo");
        return;
    }
    const tasto = $("lu-pannello-si");
    tasto.disabled = true;
    try {
        const esito = await azione.fai(voce, scritto);
        const testo = typeof esito === "string" ? esito : esito.testo;
        chiudiLAzione();
        avvisa(testo, false, typeof esito === "object" ? esito.mossa : null);
        await ricarica(typeof esito === "object" && "vai" in esito ? esito.vai : voce.id);
    } catch (errore) {
        avvisa(errore.message || "Qualcosa non ha funzionato.", true);
    } finally {
        tasto.disabled = false;
    }
}

async function ricarica(vai = scelto) {
    try {
        const dati = await chiedi("/api/luoghi/elenco");
        luoghi = dati.luoghi || [];
        aggiornaIConti(dati.conti);
    } catch (errore) {
        avvisa(errore.message, true);
        return;
    }
    indicizza();
    if (vai && perId.has(vai)) {
        let padre = perId.get(vai).genitore;
        while (padre !== null && padre !== undefined) {
            chiusi.delete(padre);
            padre = perId.get(padre)?.genitore ?? null;
        }
    }
    disegnaLElenco();
    if (vai && perId.has(vai)) scegli(vai, true);
    else {
        scelto = null;
        $("lu-scheda-vuota").hidden = false;
        $("lu-scheda-piena").hidden = true;
    }
    document.dispatchEvent(new CustomEvent("luoghi-cambiati"));
}

$("lu-elenco").addEventListener("click", (evento) => {
    const apri = evento.target.closest("[data-apri-chiudi]");
    if (apri) {
        const id = Number(apri.dataset.apriChiudi);
        if (chiusi.has(id)) chiusi.delete(id); else chiusi.add(id);
        scrivi(CHIAVE_CHIUSI, JSON.stringify([...chiusi]));
        disegnaLElenco();
        return;
    }
    const scelta = evento.target.closest(".lu-riga");
    if (scelta) scegli(Number(scelta.dataset.id));
});

$("lu-elenco").addEventListener("keydown", (evento) => {
    if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Enter"].includes(evento.key)) return;
    const righe = [...$("lu-elenco").querySelectorAll(".lu-riga")];
    if (!righe.length) return;
    evento.preventDefault();
    const adesso = righe.findIndex((elemento) => Number(elemento.dataset.id) === scelto);
    if (evento.key === "ArrowLeft" || evento.key === "ArrowRight") {
        if (scelto === null || !perId.get(scelto).figli) return;
        if (evento.key === "ArrowLeft") chiusi.add(scelto); else chiusi.delete(scelto);
        scrivi(CHIAVE_CHIUSI, JSON.stringify([...chiusi]));
        disegnaLElenco();
        return;
    }
    if (evento.key === "Enter") {
        if (scelto !== null) window.location.href = `/?luogo=${scelto}`;
        return;
    }
    const prossimo = evento.key === "ArrowDown" ? Math.min(righe.length - 1, adesso + 1) : Math.max(0, adesso - 1);
    scegli(Number(righe[adesso < 0 ? 0 : prossimo].dataset.id), true);
});

document.addEventListener("click", (evento) => {
    const vai = evento.target.closest("[data-vai]");
    if (vai) {
        const id = Number(vai.dataset.vai);
        let padre = perId.get(id)?.genitore ?? null;
        while (padre !== null) { chiusi.delete(padre); padre = perId.get(padre)?.genitore ?? null; }
        disegnaLElenco();
        scegli(id, true);
        return;
    }
    const annullaUnione = evento.target.closest("[data-annulla-unione]");
    if (annullaUnione) {
        if (annullaUnione.dataset.sicuro !== "1") {
            annullaUnione.dataset.sicuro = "1";
            annullaUnione.textContent = "Sì, annulla l'unione";
            annullaUnione.classList.add("pericolo");
            return;
        }
        annulla(Number(annullaUnione.dataset.annullaUnione), annullaUnione);
        return;
    }
    const azione = evento.target.closest("[data-azione]");
    if (azione) {
        if (azioneAperta && azioneAperta.nome === azione.dataset.azione) chiudiLAzione();
        else apriLAzione(azione.dataset.azione);
    }
});

$("lu-pannello").addEventListener("submit", (evento) => { evento.preventDefault(); faiLAzione(); });
$("lu-pannello").querySelector("[data-chiudi]").addEventListener("click", chiudiLAzione);

$("lu-cerca").addEventListener("input", quandoSiFerma(disegnaLElenco, 80));
$("lu-cerca").addEventListener("keydown", (evento) => {
    if (evento.key === "Enter") {
        const primo = $("lu-elenco").querySelector(".lu-riga");
        if (primo) scegli(Number(primo.dataset.id));
    }
    if (evento.key === "Escape") { $("lu-cerca").value = ""; disegnaLElenco(); }
});
$("lu-ordine").value = ordine;
$("lu-ordine").addEventListener("change", () => {
    ordine = $("lu-ordine").value;
    scrivi(CHIAVE_ORDINE, ordine);
    disegnaLElenco();
});
for (const bottone of document.querySelectorAll("[data-filtro]")) {
    bottone.addEventListener("click", () => {
        filtro = bottone.dataset.filtro;
        for (const altro of document.querySelectorAll("[data-filtro]")) {
            altro.setAttribute("aria-pressed", altro === bottone ? "true" : "false");
        }
        disegnaLElenco();
    });
}

const nuovo = $("lu-nuovo");
$("lu-apri-nuovo").addEventListener("click", () => {
    nuovo.hidden = !nuovo.hidden;
    if (!nuovo.hidden) {
        mostra("lista");
        nuovo.elements.dentro.value = scelto !== null ? nomeCompleto(perId.get(scelto)) : "";
        nuovo.elements.nome.focus();
    }
});
nuovo.querySelector("[data-chiudi]").addEventListener("click", () => { nuovo.hidden = true; });
nuovo.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const dentro = nuovo.elements.dentro.value.trim() ? luogoScritto(nuovo.elements.dentro.value) : null;
    if (dentro === undefined) { avvisa("Non trovo il luogo che lo contiene: sceglilo dall'elenco che compare mentre scrivi.", true); return; }
    try {
        const fatto = await mandaModulo("/api/luoghi/crea", { nome: nuovo.elements.nome.value, genitore_id: dentro || "" });
        nuovo.elements.nome.value = "";
        nuovo.hidden = true;
        avvisa(`Aggiunto «${fatto.nome}».`);
        await ricarica(fatto.nodo_id);
    } catch (errore) {
        avvisa(errore.message, true);
    }
});

document.addEventListener("keydown", (evento) => {
    if (siStaScrivendo(evento.target) || evento.ctrlKey || evento.metaKey || evento.altKey) {
        if (evento.key === "Escape" && azioneAperta) chiudiLAzione();
        return;
    }
    if (evento.key === "/") { evento.preventDefault(); $("lu-cerca").focus(); }
    if (evento.key === "Escape" && azioneAperta) chiudiLAzione();
});

const bottoni = [...document.querySelectorAll("[data-vista]")];
const viste = [...document.querySelectorAll("[data-vista-di]")];
let alberoCambiato = false;
document.addEventListener("albero-cambiato", () => { alberoCambiato = true; });

function mostra(quale) {
    bottoni.forEach((bottone) => bottone.setAttribute("aria-pressed", bottone.dataset.vista === quale ? "true" : "false"));
    viste.forEach((vista) => { vista.hidden = vista.dataset.vistaDi !== quale; });
    document.querySelector(".lu-barra").hidden = quale === "albero";
    if (quale === "albero") $("lu-nuovo").hidden = true;
    if (quale === "albero") document.dispatchEvent(new CustomEvent("albero-aperto"));
    if (quale === "lista" && alberoCambiato) { alberoCambiato = false; ricarica(); }
}

bottoni.forEach((bottone) => bottone.addEventListener("click", () => {
    mostra(bottone.dataset.vista);
    scrivi(CHIAVE_VISTA, bottone.dataset.vista);
}));

const giornate = $("lu-giornate");
let giaGiornate = 0;

function giornata(voce) {
    const carta = crea("article", "lu-giornata");
    carta.dataset.giorno = voce.giorno || "";
    const testa = crea("div", "lu-giornata-testa");
    const titolo = crea("div", "");
    titolo.append(crea("b", "", voce.giorno ? giornoAParole(voce.giorno, true) : "Senza data"));
    const dettagli = [scattiAParole(voce.quanti)];
    if (voce.col_gps) dettagli.push(`${numeroAParole(voce.col_gps)} col GPS`);
    titolo.append(crea("span", "minuscolo tenue", dettagli.join(" · ")));
    testa.append(titolo);
    const destra = crea("div", "lu-giornata-destra");
    if (voce.giorno) {
        const apri = crea("a", "tasto-comando nudo piccolo", "Apri la giornata");
        apri.href = `/?dal=${voce.giorno}&al=${voce.giorno}`;
        destra.append(apri);
    }
    const prendi = crea("label", "lu-prendi minuscolo");
    const spunta = document.createElement("input");
    spunta.type = "checkbox";
    spunta.dataset.prendi = "1";
    spunta.setAttribute("aria-label", `Scegli ${voce.giorno ? giornoAParole(voce.giorno, true) : "gli scatti senza data"} insieme ad altre giornate`);
    prendi.append(spunta, document.createTextNode("Scegli"));
    prendi.title = "Spunta più giornate fatte nello stesso posto e dai il luogo a tutte in un colpo";
    destra.append(prendi);
    testa.append(destra);
    carta.append(testa);

    const foto = crea("div", "lu-giornata-foto");
    for (const scatto of voce.foto) {
        const bottone = crea("button", "lu-giornata-scatto");
        bottone.type = "button";
        bottone.dataset.scatto = String(scatto.scatto_id);
        bottone.setAttribute("aria-pressed", "true");
        bottone.title = "Clicca per lasciarlo fuori";
        const immagine = document.createElement("img");
        immagine.src = `/miniatura/${Number(scatto.file_id)}`;
        immagine.alt = "";
        immagine.loading = "lazy";
        bottone.append(immagine);
        foto.append(bottone);
    }
    if (voce.quanti > voce.foto.length) {
        foto.append(crea("span", "lu-giornata-altre minuscolo tenue numeri", `+${numeroAParole(voce.quanti - voce.foto.length)}`));
    }
    carta.append(foto);

    const scelte = crea("form", "lu-giornata-scelte");
    if (voce.proposta) {
        const proposta = crea("div", "lu-proposta");
        const nome = voce.proposta.percorso ? `${voce.proposta.percorso}${SEPARATORE}${voce.proposta.nome}` : voce.proposta.nome;
        const parole = crea("span", "piccolo");
        parole.append("Forse ", crea("b", "", nome));
        proposta.append(parole, crea("span", "minuscolo tenue", voce.proposta.perche));
        const si = crea("button", "tasto-comando accento piccolo", "Sì, mettili lì");
        si.type = "button";
        si.dataset.metti = String(voce.proposta.posto_id);
        proposta.append(si);
        scelte.append(proposta);
    }
    const riga = crea("div", "lu-giornata-riga");
    const campo = document.createElement("input");
    campo.className = "campo";
    campo.name = "luogo";
    campo.setAttribute("list", "lu-tutti");
    campo.placeholder = voce.proposta ? "Oppure un altro luogo" : "Scrivi il luogo";
    campo.setAttribute("aria-label", "Il luogo di questa giornata");
    const metti = crea("button", "tasto-comando piccolo", "Metti");
    metti.type = "submit";
    const nonSo = crea("button", "tasto-comando nudo piccolo", "Non so dove");
    nonSo.type = "button";
    nonSo.dataset.nonSo = "1";
    riga.append(campo, metti, nonSo);
    scelte.append(riga);
    carta.append(scelte);
    return carta;
}

function soloScelti(carta) {
    const tutte = [...carta.querySelectorAll("[data-scatto]")];
    const tolti = tutte.filter((b) => b.getAttribute("aria-pressed") === "false");
    if (!tolti.length) return "";
    if (tolti.length === tutte.length) return null;
    return tutte.filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.scatto).join(",");
}

async function sistemaLaGiornata(carta, campi) {
    const quanti = carta.querySelectorAll("[data-scatto]").length;
    const solo = soloScelti(carta);
    if (solo === null) { avvisa("Hai lasciato fuori tutti gli scatti: riaccendine almeno uno.", true); return; }
    const conteggio = Number(carta.dataset.quanti || quanti);
    for (const tasto of carta.querySelectorAll("button")) tasto.disabled = true;
    try {
        const esito = await mandaModulo("/api/luoghi/giornata", { giorno: carta.dataset.giorno, solo, ...campi });
        const resta = solo ? conteggio - esito.messi : 0;
        avvisa(campi.non_so ? `${scattiAParole(esito.messi)} segnati «Non so dove».` : `${scattiAParole(esito.messi)} messi in «${perId.get(Number(campi.posto_id))?.nome || "quel luogo"}».`, false, esito.mossa);
        if (resta > 0) await caricaLeGiornate(false);
        else {
            carta.classList.add("fatta");
            setTimeout(() => carta.remove(), 220);
            giaGiornate = Math.max(0, giaGiornate - 1);
        }
        await ricarica(scelto);
        if (!giornate.querySelector(".lu-giornata:not(.fatta)")) caricaLeGiornate(false);
    } catch (errore) {
        avvisa(errore.message, true);
        for (const tasto of carta.querySelectorAll("button")) tasto.disabled = false;
    }
}

giornate.addEventListener("click", (evento) => {
    const carta = evento.target.closest(".lu-giornata");
    if (!carta) return;
    const scatto = evento.target.closest("[data-scatto]");
    if (scatto) {
        scatto.setAttribute("aria-pressed", scatto.getAttribute("aria-pressed") === "true" ? "false" : "true");
        scatto.title = scatto.getAttribute("aria-pressed") === "true" ? "Clicca per lasciarlo fuori" : "Lasciato fuori: clicca per riprenderlo";
        aggiornaLInsieme();
        return;
    }
    const metti = evento.target.closest("[data-metti]");
    if (metti) { sistemaLaGiornata(carta, { posto_id: metti.dataset.metti }); return; }
    if (evento.target.closest("[data-non-so]")) sistemaLaGiornata(carta, { non_so: 1 });
});

giornate.addEventListener("submit", (evento) => {
    evento.preventDefault();
    const carta = evento.target.closest(".lu-giornata");
    const scritto = evento.target.elements.luogo.value;
    const posto = luogoScritto(scritto);
    if (!posto) {
        avvisa(scritto.trim() ? "Non trovo questo luogo: sceglilo dall'elenco che compare mentre scrivi." : "Scrivi il luogo, oppure premi «Non so dove».", true);
        return;
    }
    sistemaLaGiornata(carta, { posto_id: posto });
});

async function caricaLeGiornate(altre) {
    const stato = $("lu-giornate-stato");
    const da = altre ? giaGiornate : 0;
    if (!altre) stato.textContent = "Cerco gli scatti senza luogo…";
    stato.hidden = false;
    let dati;
    try {
        dati = await chiedi(`/api/luoghi/senza-luogo?da=${da}`);
    } catch (errore) {
        stato.textContent = "Non riesco a leggere gli scatti senza luogo. Riprova fra poco.";
        return;
    }
    if (!altre) { giornate.replaceChildren(); giaGiornate = 0; aggiornaLInsieme(); }
    for (const voce of dati.giornate || []) {
        const carta = giornata(voce);
        carta.dataset.quanti = String(voce.quanti);
        giornate.append(carta);
    }
    giaGiornate += (dati.giornate || []).length;
    const tutte = dati.tutte || 0;
    $("lu-senza-sotto").textContent = tutte
        ? `${numeroAParole(tutte)} ${tutte === 1 ? "giornata" : "giornate"}, dalla più recente.`
        : "Nessuno: ogni scatto ha un luogo, o un «Non so dove».";
    stato.hidden = Boolean(giornate.children.length) || !tutte;
    if (!tutte) stato.hidden = true;
    $("lu-altre-giornate").hidden = giaGiornate >= tutte;
}

$("lu-altre-giornate").addEventListener("click", () => caricaLeGiornate(true));

function carteScelte() {
    return [...giornate.querySelectorAll(".lu-giornata:not(.fatta)")]
        .filter((carta) => carta.querySelector("[data-prendi]")?.checked);
}

function quantiNellaCarta(carta) {
    const solo = soloScelti(carta);
    if (solo === null) return 0;
    if (solo === "") return Number(carta.dataset.quanti || carta.querySelectorAll("[data-scatto]").length);
    return solo.split(",").length;
}

function aggiornaLInsieme() {
    const carte = carteScelte();
    for (const carta of giornate.querySelectorAll(".lu-giornata")) {
        carta.classList.toggle("scelta", carte.includes(carta));
    }
    const barra = $("lu-insieme");
    barra.hidden = !carte.length;
    if (!carte.length) return;
    const quanti = carte.reduce((somma, carta) => somma + quantiNellaCarta(carta), 0);
    $("lu-insieme-conto").textContent = `${scattiAParole(quanti)} da ${numeroAParole(carte.length)} ${carte.length === 1 ? "giornata" : "giornate"}`;
}

function lasciaLInsieme() {
    for (const spunta of giornate.querySelectorAll("[data-prendi]")) spunta.checked = false;
    aggiornaLInsieme();
}

async function sistemaLInsieme(campi) {
    const carte = carteScelte();
    const giorni = [];
    const scatti = [];
    for (const carta of carte) {
        const solo = soloScelti(carta);
        if (solo === null) continue;
        if (solo === "") giorni.push(carta.dataset.giorno || null);
        else scatti.push(...solo.split(",").map(Number));
    }
    if (!giorni.length && !scatti.length) {
        avvisa("Nelle giornate scelte hai lasciato fuori tutti gli scatti: riaccendine almeno uno.", true);
        return;
    }
    const barra = $("lu-insieme");
    for (const tasto of barra.querySelectorAll("button")) tasto.disabled = true;
    try {
        const esito = await manda("/api/luoghi/scatti", { giorni, scatti, ...campi });
        avvisa(campi.non_so
            ? `${scattiAParole(esito.messi)} segnati «Non so dove».`
            : `${scattiAParole(esito.messi)} messi in «${esito.percorso || "quel luogo"}».`, false, esito.mossa);
        barra.elements.luogo.value = "";
        barra.hidden = true;
        await ricarica(scelto);
        await caricaLeGiornate(false);
    } catch (errore) {
        avvisa(errore.message, true);
    } finally {
        for (const tasto of barra.querySelectorAll("button")) tasto.disabled = false;
    }
}

giornate.addEventListener("change", (evento) => {
    if (evento.target.matches("[data-prendi]")) aggiornaLInsieme();
});

$("lu-insieme").addEventListener("submit", (evento) => {
    evento.preventDefault();
    const scritto = evento.target.elements.luogo.value;
    const posto = luogoScritto(scritto);
    if (!posto) {
        avvisa(scritto.trim() ? "Non trovo questo luogo: sceglilo dall'elenco che compare mentre scrivi." : "Scrivi il luogo, oppure premi «Non so dove».", true);
        return;
    }
    sistemaLInsieme({ posto_id: posto });
});
$("lu-insieme").querySelector("[data-insieme-non-so]").addEventListener("click", () => sistemaLInsieme({ non_so: 1 }));
$("lu-insieme").querySelector("[data-insieme-lascia]").addEventListener("click", lasciaLInsieme);

indicizza();
disegnaLElenco();
aggiornaIConti(iniziali.conti);

if (document.getElementById("pl-albero-tela")) {
    await import("/statici/js/albero.js?genere=luoghi&prefisso=pl-&sopra=0");
}
mostra(leggi(CHIAVE_VISTA, "lista") === "albero" ? "albero" : "lista");

const dalLink = /^#luogo-(\d+)$/.exec(window.location.hash || "");
if (dalLink && perId.has(Number(dalLink[1]))) scegli(Number(dalLink[1]), true);

caricaLeGiornate(false);
