import { chiedi } from "/statici/js/comune.js";

const LATO_DI_LAVORO = 2048;
const COLORE = "rgba(255, 64, 160, 0.42)";
const BORDO = "rgba(255, 64, 160, 0.95)";
const STRUMENTI = [
    ["clic", "Clic", "C", "Clic sinistro sulla cosa: SAM fa la sagoma. Altri clic la allargano; clic destro (o Alt+clic) toglie un pezzo"],
    ["pennello", "Pennello", "B", "Disegna a mano: aggiunge alla sagoma. Alt mentre disegni per togliere"],
    ["gomma", "Gomma", "E", "Toglie dalla sagoma quello che ci passi sopra"],
    ["contorno", "Contorno", "L", "Gira intorno alla cosa: si riempie quando lasci. Alt mentre giri per togliere"],
];

const STATI_IN_CORSO = ["in_coda", "in_lavoro"];
const OGNI_QUANTO = 700;

const json = (corpo) => ({
    method: "POST", body: JSON.stringify(corpo), headers: { "Content-Type": "application/json" },
});

function scampa(testo) {
    return String(testo ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function carica(indirizzo) {
    return new Promise((fatto, sbagliato) => {
        const immagine = new Image();
        immagine.onload = () => fatto(immagine);
        immagine.onerror = () => sbagliato(new Error("immagine"));
        immagine.src = indirizzo;
    });
}

function tela(larga, alta) {
    const c = document.createElement("canvas");
    c.width = larga;
    c.height = alta;
    return c;
}

export function apriSagoma({ scatto, nodo, nome, sagoma, foto, quandoCambia, video = false, istante = 0 }) {
    const velo = document.createElement("div");
    velo.className = "et-finestrina sg-velo";
    velo.tabIndex = -1;
    velo.innerHTML = `
        <div class="sg-scheda" role="dialog" aria-modal="true" aria-label="Sagoma di ${scampa(nome)}">
            <div class="sg-testa">
                <div class="sg-titolo"><span class="tenue">Sagoma di</span> <b>${scampa(nome)}</b> <span class="tenue sg-facoltativa">· facoltativa: aiuta l'IA a capire dov'è</span></div>
                <button type="button" class="sg-chiudi" data-sg="chiudi" title="Chiudi senza salvare (Esc)">×</button>
            </div>
            <div class="sg-corpo">
                <div class="sg-sinistra">
                    <div class="sg-palco" id="sg-palco">
                        <div class="sg-quadro" id="sg-quadro">
                            <img id="sg-foto" alt="" draggable="false">
                            <canvas id="sg-vista"></canvas>
                        </div>
                    </div>
                    ${video ? `<div class="sg-video" id="sg-video" hidden>
                        <div class="sg-video-riga">
                            <button type="button" data-sg="prima" title="Fotogramma prima (←)">◀</button>
                            <span class="sg-qui" id="sg-qui"></span>
                            <button type="button" data-sg="dopo" title="Fotogramma dopo (→)">▶</button>
                            <span class="sg-seguita tenue" id="sg-seguita"></span>
                            <span class="sg-spazio"></span>
                            <button type="button" data-sg="buona" id="sg-buona" title="Qui l'IA l'ha seguita bene: vale come esempio">Buona</button>
                            <button type="button" data-sg="non-buona" id="sg-non-buona" title="Qui l'IA ha sbagliato: non vale come esempio. Per correggerla, disegnala e salva">Non buona</button>
                            <button type="button" data-sg="segui" id="sg-segui" title="Fai seguire di nuovo la sagoma in tutto il video">Segui di nuovo</button>
                        </div>
                        <div class="sg-striscia" id="sg-striscia" role="listbox" aria-label="Fotogrammi del video"></div>
                        <div class="sg-legenda tenue"><span class="utente"></span> tua <span class="sicura"></span> seguita <span class="dubbia"></span> da controllare <span class="nonbuona"></span> non buona <span class="persa"></span> persa</div>
                    </div>` : ""}
                </div>
                <aside class="sg-lato">
                    <div class="sg-gruppo">
                        <div class="sg-etichetta">Strumento</div>
                        <div class="sg-strumenti">
                            ${STRUMENTI.map(([chi, testo, tasto, aiuto]) => `<button type="button" data-strumento="${chi}" title="${scampa(aiuto)} (${tasto})">${testo}<kbd>${tasto}</kbd></button>`).join("")}
                        </div>
                        <label class="sg-misura">Grandezza <input type="range" id="sg-raggio" min="2" max="120" value="18"> <span id="sg-raggio-n">18</span></label>
                        <p class="sg-aiuto tenue" id="sg-aiuto"></p>
                    </div>
                    <div class="sg-gruppo">
                        <div class="sg-fila">
                            <button type="button" data-sg="annulla" title="Annulla l'ultimo gesto (Ctrl+Z)">Annulla</button>
                            <button type="button" data-sg="pulisci" title="Ricomincia da zero">Pulisci</button>
                        </div>
                        <label class="sg-spunta"><input type="checkbox" id="sg-bordo" checked> mostra il bordo</label>
                    </div>
                    <p class="sg-stato" id="sg-stato" role="status" aria-live="polite"></p>
                    <div class="sg-piede">
                        <button type="button" class="primario" data-sg="salva" title="Salva la sagoma (Invio)">Salva sagoma</button>
                        <button type="button" class="sg-togli" data-sg="togli" id="sg-togli" title="Togli la sagoma salvata (l'etichetta resta)"${sagoma && !video ? "" : " hidden"}>Togli sagoma</button>
                    </div>
                </aside>
            </div>
        </div>`;
    document.body.appendChild(velo);
    const $ = (id) => velo.querySelector(`#${id}`);
    const immagine = $("sg-foto");
    const vista = $("sg-vista");
    const stato = $("sg-stato");

    const s = {
        strumento: "clic", raggio: 18, griglia: null, punti: [], sam: null, base: null,
        gesti: [], inCorso: null, samUsato: false, manoUsata: false, guardata: null,
        chiedendo: 0, vivo: true, cambiata: false, mostraBordo: true,
        video: null, fotogramma: -1, righe: [], seguita: null, giro: null, caricando: 0,
    };

    const scrivi = (testo, male = false) => {
        stato.textContent = testo || "";
        stato.classList.toggle("male", !!male);
    };

    function chiudi() {
        if (!s.vivo) return;
        s.vivo = false;
        clearTimeout(s.giro);
        window.removeEventListener("resize", ridisegna);
        document.removeEventListener("keydown", tasti, true);
        velo.remove();
    }

    function scegliStrumento(chi) {
        s.strumento = chi;
        velo.querySelectorAll("[data-strumento]").forEach((b) => b.classList.toggle("acceso", b.dataset.strumento === chi));
        vista.dataset.strumento = chi;
        $("sg-aiuto").textContent = (STRUMENTI.find((x) => x[0] === chi) || [])[3] || "";
    }

    function maschera() {
        const [larga, alta] = s.griglia;
        const c = tela(larga, alta);
        const g = c.getContext("2d");
        g.imageSmoothingEnabled = false;
        if (s.base) g.drawImage(s.base.img, s.base.x, s.base.y, s.base.w, s.base.h);
        if (s.sam) g.drawImage(s.sam.img, s.sam.x, s.sam.y, s.sam.w, s.sam.h);
        const tutti = s.inCorso ? [...s.gesti, s.inCorso] : s.gesti;
        tutti.forEach((gesto) => disegnaGesto(g, gesto, larga, alta));
        return c;
    }

    function disegnaGesto(g, gesto, larga, alta) {
        if (gesto.tipo === "punto") return;
        g.save();
        g.globalCompositeOperation = gesto.togli ? "destination-out" : "source-over";
        g.fillStyle = g.strokeStyle = "#fff";
        const p = gesto.punti.map(([x, y]) => [x * larga, y * alta]);
        if (gesto.tipo === "contorno") {
            if (p.length < 3) { g.restore(); return; }
            g.beginPath();
            g.moveTo(p[0][0], p[0][1]);
            p.slice(1).forEach(([x, y]) => g.lineTo(x, y));
            g.closePath();
            g.fill();
            g.restore();
            return;
        }
        const r = gesto.raggio * larga;
        g.lineCap = g.lineJoin = "round";
        g.lineWidth = r * 2;
        g.beginPath();
        g.moveTo(p[0][0], p[0][1]);
        if (p.length === 1) g.lineTo(p[0][0] + 0.01, p[0][1]);
        p.slice(1).forEach(([x, y]) => g.lineTo(x, y));
        g.stroke();
        g.restore();
    }

    function ridisegna() {
        if (!s.vivo || !s.griglia) return;
        const quadro = $("sg-quadro");
        const palco = $("sg-palco");
        const spazio = [palco.clientWidth - 24, palco.clientHeight - 24];
        const naturale = [immagine.naturalWidth || 1, immagine.naturalHeight || 1];
        const adatta = Math.max(0.01, Math.min(spazio[0] / naturale[0], spazio[1] / naturale[1]));
        immagine.style.width = `${Math.floor(naturale[0] * adatta)}px`;
        immagine.style.height = `${Math.floor(naturale[1] * adatta)}px`;
        const larga = immagine.clientWidth;
        const alta = immagine.clientHeight;
        if (!larga || !alta) return;
        const scala = window.devicePixelRatio || 1;
        vista.width = Math.round(larga * scala);
        vista.height = Math.round(alta * scala);
        vista.style.width = `${larga}px`;
        vista.style.height = `${alta}px`;
        quadro.style.setProperty("--sg-larga", `${larga}px`);
        const g = vista.getContext("2d");
        g.clearRect(0, 0, vista.width, vista.height);
        const m = maschera();
        const tinta = tela(vista.width, vista.height);
        const t = tinta.getContext("2d");
        t.imageSmoothingEnabled = true;
        t.drawImage(m, 0, 0, vista.width, vista.height);
        t.globalCompositeOperation = "source-in";
        t.fillStyle = COLORE;
        t.fillRect(0, 0, tinta.width, tinta.height);
        if (s.mostraBordo) {
            const bordo = tela(vista.width, vista.height);
            const b = bordo.getContext("2d");
            const passo = Math.max(1, Math.round(1.5 * scala));
            [[passo, 0], [-passo, 0], [0, passo], [0, -passo]].forEach(([dx, dy]) => b.drawImage(m, dx, dy, vista.width, vista.height));
            b.globalCompositeOperation = "destination-out";
            b.drawImage(m, 0, 0, vista.width, vista.height);
            b.globalCompositeOperation = "source-in";
            b.fillStyle = BORDO;
            b.fillRect(0, 0, bordo.width, bordo.height);
            g.drawImage(bordo, 0, 0);
        }
        g.drawImage(tinta, 0, 0);
        s.punti.forEach((punto) => {
            g.beginPath();
            g.arc(punto.x * vista.width, punto.y * vista.height, 6 * scala, 0, Math.PI * 2);
            g.fillStyle = punto.dentro ? "#2ecc71" : "#e74c3c";
            g.fill();
            g.lineWidth = 2 * scala;
            g.strokeStyle = "#fff";
            g.stroke();
        });
        if (s.inCorso && s.inCorso.tipo === "contorno") {
            g.beginPath();
            s.inCorso.punti.forEach(([x, y], i) => (i ? g.lineTo : g.moveTo).call(g, x * vista.width, y * vista.height));
            g.setLineDash([6 * scala, 4 * scala]);
            g.lineWidth = 1.5 * scala;
            g.strokeStyle = "#fff";
            g.stroke();
        }
    }

    function dove(evento) {
        const r = vista.getBoundingClientRect();
        return [Math.min(1, Math.max(0, (evento.clientX - r.left) / r.width)),
                Math.min(1, Math.max(0, (evento.clientY - r.top) / r.height))];
    }

    async function chiediASam() {
        const numero = ++s.chiedendo;
        if (!s.punti.length) { s.sam = null; ridisegna(); return; }
        scrivi("SAM sta guardando…");
        try {
            const dati = s.video
                ? await chiedi(`/api/sagome/video/${foto}/scegli`, json({ punti: s.punti, fotogramma: s.fotogramma }))
                : await chiedi(`/api/sagome/${foto}/scegli`, json({ punti: s.punti }));
            if (numero !== s.chiedendo || !s.vivo) return;
            if (dati.vuota) {
                s.sam = null;
                scrivi(dati.messaggio, true);
            } else {
                const img = await carica(`data:image/png;base64,${dati.png}`);
                if (numero !== s.chiedendo || !s.vivo) return;
                const [larga, alta] = s.griglia;
                const kx = larga / dati.larghezza;
                const ky = alta / dati.altezza;
                s.sam = { img, x: dati.x * kx, y: dati.y * ky, w: dati.larga * kx, h: dati.alta * ky };
                s.samUsato = true;
                scrivi(dati.dove === "processore" ? "Fatto (col processore: la scheda era occupata)." : "Fatto. Correggi con altri clic, col pennello o col contorno.");
            }
            s.cambiata = true;
            ridisegna();
        } catch (errore) {
            if (numero !== s.chiedendo || !s.vivo) return;
            s.punti.pop();
            s.gesti = s.gesti.filter((gesto, i) => !(gesto.tipo === "punto" && i === s.gesti.length - 1));
            scrivi(`${errore.message} Puoi sempre disegnarla a mano col pennello o col contorno.`, true);
            ridisegna();
        }
    }

    async function guarda() {
        if (s.guardata) return s.guardata;
        s.guardata = chiedi(`/api/sagome/${foto}/guarda`, { method: "POST" }).catch((errore) => {
            s.guardata = null;
            throw errore;
        });
        return s.guardata;
    }

    vista.addEventListener("contextmenu", (evento) => evento.preventDefault());
    vista.addEventListener("pointerdown", (evento) => {
        if (!s.griglia || (evento.button !== 0 && evento.button !== 2)) return;
        evento.preventDefault();
        const [x, y] = dove(evento);
        const togli = evento.altKey || evento.button === 2;
        if (s.strumento === "clic") {
            s.punti.push({ x, y, dentro: !togli });
            s.gesti.push({ tipo: "punto" });
            (s.video ? Promise.resolve() : guarda()).then(chiediASam, (errore) => {
                s.punti.pop();
                s.gesti.pop();
                scrivi(`${errore.message} Intanto puoi disegnarla a mano col pennello o col contorno.`, true);
                ridisegna();
            });
            ridisegna();
            return;
        }
        vista.setPointerCapture(evento.pointerId);
        const larga = vista.getBoundingClientRect().width;
        s.inCorso = {
            tipo: s.strumento === "contorno" ? "contorno" : "pennello",
            togli: s.strumento === "gomma" || togli,
            raggio: s.raggio / larga,
            punti: [[x, y]],
        };
        ridisegna();
    });
    vista.addEventListener("pointermove", (evento) => {
        if (!s.inCorso) return;
        s.inCorso.punti.push(dove(evento));
        ridisegna();
    });
    const finisci = () => {
        if (!s.inCorso) return;
        s.gesti.push(s.inCorso);
        s.inCorso = null;
        s.manoUsata = true;
        s.cambiata = true;
        ridisegna();
    };
    vista.addEventListener("pointerup", finisci);
    vista.addEventListener("pointercancel", finisci);

    function annulla() {
        const ultimo = s.gesti.pop();
        if (!ultimo) return;
        if (ultimo.tipo === "punto") {
            s.punti.pop();
            chiediASam();
        }
        s.cambiata = true;
        ridisegna();
    }

    function pulisci() {
        s.punti = [];
        s.gesti = [];
        s.sam = null;
        s.base = null;
        s.chiedendo += 1;
        s.cambiata = true;
        scrivi("");
        ridisegna();
    }

    function come() {
        const daSam = !!s.sam || (s.base && s.base.come !== "mano");
        const aMano = s.gesti.some((gesto) => gesto.tipo !== "punto") || (s.base && s.base.come !== "clic");
        if (daSam && aMano) return "misto";
        return daSam ? "clic" : "mano";
    }

    function ritaglio() {
        const m = maschera();
        const [larga, alta] = s.griglia;
        const pixel = m.getContext("2d").getImageData(0, 0, larga, alta).data;
        let x0 = larga, y0 = alta, x1 = -1, y1 = -1;
        for (let y = 0; y < alta; y += 1) {
            const riga = y * larga * 4;
            for (let x = 0; x < larga; x += 1) {
                if (pixel[riga + x * 4 + 3] > 127) {
                    if (x < x0) x0 = x;
                    if (x > x1) x1 = x;
                    if (y < y0) y0 = y;
                    if (y > y1) y1 = y;
                }
            }
        }
        if (x1 < 0) return null;
        const w = x1 - x0 + 1;
        const h = y1 - y0 + 1;
        const pezzo = tela(w, h);
        const g = pezzo.getContext("2d");
        const dentro = g.createImageData(w, h);
        for (let y = 0; y < h; y += 1) {
            for (let x = 0; x < w; x += 1) {
                const pieno = pixel[((y + y0) * larga + x + x0) * 4 + 3] > 127 ? 255 : 0;
                const i = (y * w + x) * 4;
                dentro.data[i] = dentro.data[i + 1] = dentro.data[i + 2] = pieno;
                dentro.data[i + 3] = 255;
            }
        }
        g.putImageData(dentro, 0, 0);
        return { x: x0, y: y0, larga: w, alta: h, png: pezzo.toDataURL("image/png").split(",")[1] };
    }

    async function salva() {
        const pezzo = ritaglio();
        if (!pezzo) { scrivi("La sagoma è vuota: clicca sulla cosa o disegnala, poi salva.", true); return; }
        const [larghezza, altezza] = s.griglia;
        scrivi("Salvo…");
        try {
            const dati = await chiedi("/api/sagome/salva", json({
                scatto_id: scatto, file_id: foto, nodo_id: nodo, come: come(),
                larghezza, altezza, ...pezzo, ...(s.video ? { fotogramma: s.fotogramma } : {}),
            }));
            if (quandoCambia) quandoCambia(dati.sagome);
            if (!s.video) { chiudi(); return; }
            scrivi("Salvata. L'IA la segue nel resto del video: guarda la striscia sotto.");
            if (dati.seguita) s.seguita = dati.seguita;
            await aggiorna();
            vaiA(s.fotogramma);
        } catch (errore) {
            scrivi(errore.message, true);
        }
    }

    async function togliLaSagoma() {
        const quale = s.video ? rigaQui() : sagoma;
        if (!quale) return;
        try {
            const dati = await chiedi(`/api/sagome/${quale.id}/togli`, { method: "POST" });
            if (quandoCambia) quandoCambia(dati.sagome);
            if (!s.video) { chiudi(); return; }
            scrivi("Tolta. Le altre sagome di questo video restano.");
            await aggiorna();
            vaiA(s.fotogramma);
        } catch (errore) {
            scrivi(errore.message, true);
        }
    }

    velo.addEventListener("click", (evento) => {
        const b = evento.target.closest("[data-sg],[data-strumento],[data-fg]");
        if (!b) { if (evento.target === velo) chiudi(); return; }
        if (b.dataset.strumento) scegliStrumento(b.dataset.strumento);
        else if (b.dataset.sg === "chiudi") chiudi();
        else if (b.dataset.sg === "annulla") annulla();
        else if (b.dataset.sg === "pulisci") pulisci();
        else if (b.dataset.sg === "salva") salva();
        else if (b.dataset.sg === "togli") togliLaSagoma();
        else if (b.dataset.sg === "prima") vaiA(s.fotogramma - 1);
        else if (b.dataset.sg === "dopo") vaiA(s.fotogramma + 1);
        else if (b.dataset.sg === "buona") segnaBuona(true);
        else if (b.dataset.sg === "non-buona") segnaBuona(false);
        else if (b.dataset.sg === "segui") seguiDiNuovo();
        else if (b.dataset.fg !== undefined) vaiA(Number(b.dataset.fg));
    });
    const tasti = (evento) => {
        if (!s.vivo) return;
        evento.stopPropagation();
        const tasto = evento.key.toLowerCase();
        if (evento.key === "Escape") { evento.preventDefault(); chiudi(); return; }
        if ((evento.ctrlKey || evento.metaKey) && tasto === "z") { evento.preventDefault(); annulla(); return; }
        if (evento.target.tagName === "INPUT" && evento.target.type !== "range") return;
        if (evento.key === "Enter") { evento.preventDefault(); salva(); return; }
        if (s.video && (evento.key === "ArrowLeft" || evento.key === "ArrowRight")) {
            evento.preventDefault();
            vaiA(s.fotogramma + (evento.key === "ArrowRight" ? 1 : -1));
            return;
        }
        if (evento.key === "[" || evento.key === "]") {
            evento.preventDefault();
            s.raggio = Math.max(2, Math.min(120, s.raggio + (evento.key === "]" ? 4 : -4)));
            $("sg-raggio").value = s.raggio;
            $("sg-raggio-n").textContent = s.raggio;
            return;
        }
        const scelto = STRUMENTI.find((x) => x[2].toLowerCase() === tasto);
        if (scelto && !evento.ctrlKey && !evento.metaKey && !evento.altKey) { evento.preventDefault(); scegliStrumento(scelto[0]); }
    };
    document.addEventListener("keydown", tasti, true);
    $("sg-raggio").addEventListener("input", (evento) => {
        s.raggio = Number(evento.target.value);
        $("sg-raggio-n").textContent = s.raggio;
    });
    $("sg-bordo").addEventListener("change", (evento) => { s.mostraBordo = evento.target.checked; ridisegna(); });
    window.addEventListener("resize", ridisegna);

    scegliStrumento("clic");
    velo.focus();
    function rigaQui() {
        return s.righe.find((riga) => riga.fotogramma === s.fotogramma) || null;
    }

    function inCorso() {
        return !!(s.seguita && STATI_IN_CORSO.includes(s.seguita.stato));
    }

    function statoDi(riga) {
        if (!riga) return s.seguita && s.seguita.stato === "seguita" ? "persa" : "vuota";
        if (riga.come !== "seguita") return "utente";
        if (!riga.buona) return "nonbuona";
        return riga.da_controllare ? "dubbia" : "sicura";
    }

    const NOMI = { utente: "tua", sicura: "seguita", dubbia: "da controllare", nonbuona: "non buona", persa: "persa", vuota: "" };

    function disegnaStriscia() {
        if (!s.video) return;
        const per = new Map(s.righe.map((riga) => [riga.fotogramma, riga]));
        $("sg-striscia").innerHTML = Array.from({ length: s.video.quanti }, (_, i) => {
            const quale = statoDi(per.get(i));
            return `<button type="button" role="option" class="sg-fg ${quale}${i === s.fotogramma ? " qui" : ""}" data-fg="${i}" aria-selected="${i === s.fotogramma}" title="Fotogramma ${i + 1}${NOMI[quale] ? ": " + NOMI[quale] : ""}"></button>`;
        }).join("");
        const riga = rigaQui();
        const quale = statoDi(riga);
        const secondi = ((s.video.inizio || 0) + (s.video.istanti[s.fotogramma] || 0)) / 1000;
        $("sg-qui").textContent = `${s.fotogramma + 1} di ${s.video.quanti} · ${secondi.toFixed(2)} s${NOMI[quale] ? " · " + NOMI[quale] : ""}`;
        const seguita = s.seguita || {};
        $("sg-seguita").textContent = seguita.stato === "in_lavoro" ? `L'IA la sta seguendo… ${seguita.fatti || 0} di ${seguita.quanti || s.video.quanti}`
            : seguita.stato === "in_coda" ? "In fila per la scheda video…"
            : seguita.stato === "guasta" ? (seguita.guasto || "Il seguito non è riuscito.")
            : seguita.stato === "fermata" ? "Seguito fermato." : "";
        const seguitaQui = !!(riga && riga.come === "seguita");
        $("sg-buona").hidden = !seguitaQui;
        $("sg-non-buona").hidden = !seguitaQui;
        if (seguitaQui) {
            $("sg-buona").classList.toggle("acceso", riga.buona && !riga.da_controllare);
            $("sg-non-buona").classList.toggle("acceso", !riga.buona);
        }
        $("sg-segui").disabled = inCorso() || !s.righe.some((x) => x.come !== "seguita");
        $("sg-togli").hidden = !(riga && riga.come !== "seguita");
        $("sg-striscia").querySelector(".qui")?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    async function aggiorna() {
        clearTimeout(s.giro);
        try {
            const dati = await chiedi(`/api/sagome/video/${foto}/${nodo}`);
            if (!s.vivo) return;
            s.righe = dati.fotogrammi;
            s.seguita = dati.seguita;
        } catch (errore) {
            if (!s.vivo) return;
            scrivi(errore.message, true);
        }
        disegnaStriscia();
        if (inCorso()) {
            s.giro = setTimeout(async () => {
                const prima = rigaQui();
                await aggiorna();
                const dopo = rigaQui();
                if (!s.gesti.length && !s.punti.length && (prima && prima.id) !== (dopo && dopo.id)) vaiA(s.fotogramma);
            }, OGNI_QUANTO);
        }
    }

    async function segnaBuona(buona) {
        const riga = rigaQui();
        if (!riga) return;
        try {
            await chiedi(`/api/sagome/${riga.id}/buona`, json({ buona }));
            await aggiorna();
        } catch (errore) {
            scrivi(errore.message, true);
        }
    }

    async function seguiDiNuovo() {
        try {
            await chiedi(`/api/sagome/video/${foto}/${nodo}/segui`, { method: "POST" });
            await aggiorna();
        } catch (errore) {
            scrivi(errore.message, true);
        }
    }

    async function caricaLaBase(riga) {
        const numero = ++s.caricando;
        s.base = null;
        if (!riga) return;
        try {
            const img = await carica(`/api/sagome/${riga.id}/maschera?v=${encodeURIComponent(riga.id + "-" + riga.area)}`);
            if (numero !== s.caricando || !s.vivo) return;
            const [gl, ga] = s.griglia;
            s.base = { img, come: riga.come === "seguita" ? "clic" : riga.come, x: riga.x * gl, y: riga.y * ga, w: riga.w * gl, h: riga.h * ga };
        } catch (errore) {
            scrivi("Non riesco a leggere la sagoma salvata.", true);
        }
    }

    function vaiA(f) {
        if (!s.video) return;
        const nuovo = Math.max(0, Math.min(s.video.quanti - 1, f));
        s.fotogramma = nuovo;
        s.punti = [];
        s.gesti = [];
        s.sam = null;
        s.inCorso = null;
        s.chiedendo += 1;
        const istanteQui = (s.video.inizio || 0) + (s.video.istanti[nuovo] || 0);
        const indirizzo = `/fotogramma/${foto}?sotto=1&numero=${nuovo}&istante=${istanteQui}&lato=1600`;
        const riga = rigaQui();
        disegnaStriscia();
        const dopo = () => caricaLaBase(riga).then(() => { if (nuovo === s.fotogramma) ridisegna(); });
        if (immagine.getAttribute("src") === indirizzo && immagine.complete) dopo();
        else {
            immagine.onload = dopo;
            immagine.src = indirizzo;
        }
    }

    async function preparaIlVideo() {
        scrivi("Preparo il video per seguire la sagoma…");
        let dati;
        try {
            dati = await chiedi(`/api/sagome/video/${foto}/prepara`, { method: "POST" });
            while (s.vivo && dati.stato === "in_preparazione") {
                scrivi(dati.attesi ? `Preparo il video… ${dati.preparati} di ${dati.attesi} fotogrammi` : "Preparo il video…");
                await new Promise((fatto) => setTimeout(fatto, OGNI_QUANTO));
                dati = await chiedi(`/api/sagome/video/${foto}/pronto`);
            }
        } catch (errore) {
            if (s.vivo) scrivi(errore.message, true);
            return;
        }
        if (!s.vivo) return;
        if (dati.stato !== "pronto") { scrivi(dati.guasto || "Il video non si è preparato.", true); return; }
        s.video = { quanti: dati.quanti, istanti: dati.istanti || [], inizio: dati.inizio || 0, larghezza: dati.larghezza, altezza: dati.altezza };
        s.griglia = [dati.larghezza, dati.altezza];
        const distanza = (i) => Math.abs(s.video.inizio + s.video.istanti[i] - istante);
        const vicino = s.video.istanti.reduce((meglio, _, i) => (distanza(i) < distanza(meglio) ? i : meglio), 0);
        $("sg-video").hidden = false;
        await aggiorna();
        scrivi("Clicca sulla cosa in questo fotogramma: SAM la contorna e poi l'IA la segue nel video. Se sbaglia, correggi col pennello o col contorno.");
        vaiA(vicino);
    }

    if (video) {
        immagine.addEventListener("error", () => scrivi("Questo fotogramma non si legge.", true));
        preparaIlVideo();
        return { chiudi };
    }

    immagine.addEventListener("load", async () => {
        const naturale = [immagine.naturalWidth, immagine.naturalHeight];
        let [larga, alta] = naturale;
        try {
            const vera = await guarda();
            if (!s.vivo) return;
            [larga, alta] = [vera.larghezza, vera.altezza];
        } catch (errore) {
            if (!s.vivo) return;
            scrivi(`${errore.message} Il pennello e il contorno funzionano lo stesso.`, true);
        }
        const k = Math.min(1, LATO_DI_LAVORO / Math.max(larga, alta));
        s.griglia = [Math.max(1, Math.round(larga * k)), Math.max(1, Math.round(alta * k))];
        if (sagoma) {
            try {
                const img = await carica(`/api/sagome/${sagoma.id}/maschera?v=${encodeURIComponent(sagoma.cambiata_il || sagoma.id)}`);
                if (!s.vivo) return;
                const [gl, ga] = s.griglia;
                s.base = { img, come: sagoma.come, x: sagoma.x * gl, y: sagoma.y * ga, w: sagoma.w * gl, h: sagoma.h * ga };
                if (!stato.textContent) scrivi("Questa è la sagoma salvata: correggila o togli.");
            } catch (errore) {
                scrivi("Non riesco a leggere la sagoma salvata.", true);
            }
        } else if (!stato.textContent) {
            scrivi("Clicca sulla cosa: SAM la contorna. Se sbaglia, usa il pennello o il contorno.");
        }
        ridisegna();
    }, { once: true });
    immagine.addEventListener("error", () => scrivi("La foto non si legge.", true), { once: true });
    immagine.src = `/immagine/${foto}?lato=1600`;
    return { chiudi };
}
