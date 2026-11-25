import { chiedi, manda } from "/statici/js/comune.js";

const PIU_CORTO = 0.05;

function aParole(secondi) {
    const tutti = Math.max(0, secondi || 0);
    const minuti = Math.floor(tutti / 60);
    const resto = tutti - minuti * 60;
    const decimi = Math.floor((resto - Math.floor(resto)) * 10);
    return `${minuti}:${String(Math.floor(resto)).padStart(2, "0")}${decimi ? `,${decimi}` : ""}`;
}

function vicina(valore, punti) {
    let migliore = punti[0];
    for (const punto of punti) {
        if (Math.abs(punto - valore) < Math.abs(migliore - valore)) migliore = punto;
    }
    return migliore;
}

function unisci(pezzi) {
    const ordinati = [...pezzi].sort((a, b) => a[0] - b[0]);
    const fuori = [];
    for (const [da, a] of ordinati) {
        const ultimo = fuori[fuori.length - 1];
        if (ultimo && da <= ultimo[1]) ultimo[1] = Math.max(ultimo[1], a);
        else fuori.push([da, a]);
    }
    return fuori;
}

function preparaFinestra(finestra) {
    const scatto = finestra.dataset.taglia;
    const $ = (chi) => finestra.querySelector(chi);
    const video = $("[data-tg-video]");
    const stato = $("[data-tg-stato]");
    const linea = $("[data-tg-linea]");
    const testina = $("[data-tg-testina]");
    const segno = $("[data-tg-segno]");
    const elenco = $("[data-tg-elenco]");
    const vuoto = $("[data-tg-vuoto]");
    const errore = $("[data-tg-errore]");
    const aperto = $("[data-tg-aperto]");
    const crea = $("[data-tg-crea]");
    const totale = $("[data-tg-totale]");
    const gira = $("[data-tg-gira]");
    const giraScritta = $("[data-tg-gira-scritta]");
    const tempo = $("[data-tg-tempo]");
    const comandi = [gira, $("[data-tg-inizio]"), $("[data-tg-fine]")];

    let mappa = null;
    let pezzi = [];
    let inizio = null;
    let lavora = false;

    const dove = (secondi) => `${(100 * secondi) / (mappa?.durata || 1)}%`;
    const inizi = () => mappa.chiavi.filter((t) => t < mappa.durata);
    const fini = () => [...mappa.chiavi, mappa.durata];

    function dici(testo) {
        errore.textContent = testo || "";
        errore.hidden = !testo;
    }

    function disegnaTestina() {
        if (!mappa) return;
        testina.style.left = dove(video.currentTime);
        tempo.textContent = `${aParole(video.currentTime)} / ${aParole(mappa.durata)}`;
        linea.setAttribute("aria-valuenow", String(Math.round(video.currentTime)));
        giraScritta.textContent = video.paused ? "Guarda" : "Ferma";
    }

    function disegnaPezzi() {
        const sullaLinea = $("[data-tg-pezzi-linea]");
        sullaLinea.replaceChildren(...pezzi.map(([da, a]) => {
            const fascia = document.createElement("span");
            fascia.style.left = dove(da);
            fascia.style.width = `${(100 * (a - da)) / mappa.durata}%`;
            return fascia;
        }));
        elenco.replaceChildren(...pezzi.map(([da, a], numero) => {
            const voce = document.createElement("li");
            const scritta = document.createElement("span");
            scritta.className = "numeri";
            scritta.textContent = `${aParole(da)} – ${aParole(a)}`;
            const quanto = document.createElement("span");
            quanto.className = "tenue piccolo numeri";
            quanto.textContent = `${aParole(a - da)}`;
            const guarda = document.createElement("button");
            guarda.type = "button";
            guarda.className = "tasto-comando nudo piccolo";
            guarda.textContent = "Guarda";
            guarda.addEventListener("click", () => { video.currentTime = da; video.play(); });
            const togli = document.createElement("button");
            togli.type = "button";
            togli.className = "tasto-comando nudo piccolo";
            togli.textContent = "Togli";
            togli.addEventListener("click", () => {
                pezzi.splice(numero, 1);
                disegnaPezzi();
            });
            voce.append(scritta, quanto, guarda, togli);
            return voce;
        }));
        vuoto.hidden = pezzi.length > 0;
        const lunghezza = pezzi.reduce((somma, [da, a]) => somma + (a - da), 0);
        const tutto = pezzi.length === 1 && pezzi[0][0] <= 0 && pezzi[0][1] >= mappa.durata;
        totale.textContent = pezzi.length ? `Video tagliato: ${aParole(lunghezza)}` : "";
        crea.disabled = lavora || !pezzi.length || tutto;
        if (tutto) dici("I pezzi scelti sono tutto il video: togline un pezzo.");
        segno.hidden = inizio === null;
        aperto.hidden = inizio === null;
        if (inizio !== null) {
            segno.style.left = dove(inizio);
            aperto.textContent = `Il pezzo comincia a ${aParole(inizio)}: ora vai dove finisce e premi «Fine qui».`;
        }
    }

    function disegnaChiavi() {
        const chiavi = $("[data-tg-chiavi]");
        const larga = Math.max(1, linea.clientWidth || 600);
        let ultima = -Infinity;
        const tacche = [];
        for (const t of mappa.chiavi) {
            const x = (t / mappa.durata) * larga;
            if (x - ultima < 3) continue;
            ultima = x;
            const tacca = document.createElement("span");
            tacca.style.left = dove(t);
            tacche.push(tacca);
        }
        chiavi.replaceChildren(...tacche);
    }

    function segnaInizio() {
        if (!mappa) return;
        dici("");
        inizio = vicina(video.currentTime, inizi());
        video.currentTime = inizio;
        disegnaPezzi();
    }

    function segnaFine() {
        if (!mappa) return;
        if (inizio === null) {
            dici("Prima scegli dove comincia il pezzo con «Inizio qui».");
            return;
        }
        const fine = vicina(video.currentTime, fini().filter((t) => t > inizio + PIU_CORTO));
        if (fine === undefined) {
            dici("Qui il pezzo sarebbe vuoto: vai più avanti nel video.");
            return;
        }
        dici("");
        pezzi = unisci([...pezzi, [inizio, fine]]);
        inizio = null;
        disegnaPezzi();
    }

    function vaiA(evento) {
        if (!mappa) return;
        const riquadro = linea.getBoundingClientRect();
        const parte = Math.min(1, Math.max(0, (evento.clientX - riquadro.left) / riquadro.width));
        video.currentTime = parte * mappa.durata;
        disegnaTestina();
    }

    function saltaChiave(verso) {
        if (!mappa) return;
        const adesso = video.currentTime;
        const punti = fini();
        const dopo = verso > 0 ? punti.find((t) => t > adesso + 0.01)
            : [...punti].reverse().find((t) => t < adesso - 0.01);
        if (dopo !== undefined) video.currentTime = Math.min(dopo, mappa.durata);
    }

    async function prepara() {
        pezzi = [];
        inizio = null;
        dici("");
        stato.hidden = false;
        stato.textContent = "Preparo il video…";
        comandi.forEach((tasto) => { tasto.disabled = true; });
        try {
            mappa = await chiedi(`/api/taglio/${scatto}`);
        } catch (sbaglio) {
            stato.textContent = sbaglio.message;
            return;
        }
        linea.setAttribute("aria-valuemax", String(Math.round(mappa.durata)));
        video.src = `/originale/${mappa.file}`;
        disegnaChiavi();
        disegnaPezzi();
        disegnaTestina();
    }

    function esci() {
        video.pause();
        video.removeAttribute("src");
        video.load();
        mappa = null;
        finestra.close();
    }

    async function taglia() {
        if (!pezzi.length || lavora) return;
        lavora = true;
        video.pause();
        crea.disabled = true;
        finestra.querySelectorAll("button").forEach((tasto) => { tasto.disabled = true; });
        crea.textContent = "Sto tagliando…";
        dici("");
        try {
            const fatto = await manda(`/api/taglio/${scatto}`, { pezzi });
            crea.textContent = "Fatto";
            window.location.href = fatto.indirizzo;
        } catch (sbaglio) {
            lavora = false;
            crea.textContent = "Crea il video tagliato";
            finestra.querySelectorAll("button").forEach((tasto) => { tasto.disabled = false; });
            dici(sbaglio.message);
            disegnaPezzi();
        }
    }

    video.addEventListener("loadedmetadata", () => {
        if (!mappa) return;
        stato.hidden = true;
        comandi.forEach((tasto) => { tasto.disabled = false; });
        disegnaTestina();
    });
    video.addEventListener("error", () => {
        if (!mappa || !video.getAttribute("src")) return;
        stato.hidden = false;
        stato.textContent = "Questo video non si vede nella finestra: chiudi, premi «Preparane una copia che si vede» sotto il video e poi riapri Taglia.";
    });
    video.addEventListener("timeupdate", disegnaTestina);
    video.addEventListener("play", function corre() {
        disegnaTestina();
        if (!video.paused) requestAnimationFrame(corre);
    });
    video.addEventListener("pause", disegnaTestina);
    gira.addEventListener("click", () => (video.paused ? video.play() : video.pause()));
    $("[data-tg-inizio]").addEventListener("click", segnaInizio);
    $("[data-tg-fine]").addEventListener("click", segnaFine);
    $("[data-tg-esci]").addEventListener("click", () => { if (!lavora) esci(); });
    $("[data-tg-annulla]").addEventListener("click", () => { if (!lavora) esci(); });
    crea.addEventListener("click", taglia);
    finestra.addEventListener("cancel", (evento) => {
        evento.preventDefault();
        if (!lavora) esci();
    });
    linea.addEventListener("pointerdown", (evento) => {
        linea.setPointerCapture(evento.pointerId);
        vaiA(evento);
        const muovi = (altro) => vaiA(altro);
        const lascia = () => {
            linea.removeEventListener("pointermove", muovi);
            linea.removeEventListener("pointerup", lascia);
        };
        linea.addEventListener("pointermove", muovi);
        linea.addEventListener("pointerup", lascia);
    });
    finestra.addEventListener("keydown", (evento) => {
        if (lavora || evento.target.matches?.("input, textarea")) return;
        const tasto = evento.key.toLowerCase();
        if (tasto === "i") segnaInizio();
        else if (tasto === "o") segnaFine();
        else if (tasto === " " && evento.target === linea) {
            video.paused ? video.play() : video.pause();
        } else if (evento.key === "ArrowRight" && evento.target === linea) saltaChiave(1);
        else if (evento.key === "ArrowLeft" && evento.target === linea) saltaChiave(-1);
        else return;
        evento.preventDefault();
    });
    window.addEventListener("resize", () => { if (mappa) disegnaChiavi(); });

    return prepara;
}

const finestra = document.getElementById("taglia");
if (finestra) {
    const prepara = preparaFinestra(finestra);
    document.querySelectorAll("[data-apri-taglia]").forEach((tasto) => {
        tasto.addEventListener("click", () => {
            finestra.showModal();
            prepara();
        });
    });
}
