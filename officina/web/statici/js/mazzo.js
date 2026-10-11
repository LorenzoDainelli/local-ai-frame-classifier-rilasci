import { mandaModulo } from "/statici/js/comune.js";

const $ = (nome) => document.getElementById(nome);
const gruppo = document.querySelector("[data-persona]").dataset.persona;

function volti_scelti() {
    return Array.from(document.querySelectorAll("[data-volto]:checked"))
        .map((casella) => casella.value);
}

document.querySelectorAll("[data-volto]").forEach((casella) => {
    casella.addEventListener("change", () => {
        const quanti = volti_scelti().length;
        $("non-e-lui").disabled = quanti === 0;
        const conto = $("non-e-lui").querySelector("[data-quanti]");
        if (conto) conto.textContent = quanti ? ` · ${quanti}` : "";
    });
});

$("non-e-lui").addEventListener("click", async () => {
    const scelti = volti_scelti();
    if (!scelti.length) return;
    await mandaModulo("/api/persone/non-e-lui", { volti: scelti.join(",") });
    const facce = [...document.querySelectorAll("[data-volto]:checked")].map((c) => c.closest("label")).filter(Boolean);
    if (window.movimenti?.nonELui) await window.movimenti.nonELui(facce);
    window.location.reload();
});

$("salta").addEventListener("click", async () => {
    await mandaModulo(`/api/persone/${gruppo}/rimanda`, {});
    if (window.movimenti?.saltato) await window.movimenti.saltato();
    window.location.reload();
});

$("ignora").addEventListener("click", async () => {
    await mandaModulo(`/api/persone/${gruppo}/ignora`, {});
    window.location.reload();
});

async function daiIlNome(unisciA = "") {
    const nome = $("nome").value.trim();
    if (!nome) return;
    const risposta = await mandaModulo(`/api/persone/${gruppo}/nome`,
                                       { nome, unisci_a: unisciA });
    if (risposta.chiede && risposta.chiede.length) {
        chiedi(nome, risposta.chiede);
        return;
    }
    if (window.movimenti?.nomeDato) await window.movimenti.nomeDato();
    window.location.reload();
}

const FOTINA = '<span class="fotina piccola" aria-hidden="true"><span class="cornice">' +
    '<span class="monte"></span><span class="monte due"></span><span class="sole"></span>' +
    '<span class="occhi"><span></span><span></span></span></span></span>';

const pulito = (testo) => String(testo).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function chiedi(nome, gia) {

    const dove = $("domanda-omonimo");
    dove.hidden = false;
    dove.innerHTML =
        `<div class="mz-omonimo">${FOTINA}<div class="nuvola"><p>` +
        gia.map((voce) =>
            `C'è già <b>${pulito(voce.nome)}</b>, in ${pulito(voce.scatti)} scatti.`).join(" ") +
        ` È lui?</p><div class="in-fila">` +
        gia.map((voce) =>
            `<button class="tasto-comando principale piccolo" data-unisci="${pulito(voce.persona_id)}">` +
            `Sì, è lo stesso</button>`).join("") +
        `<button class="tasto-comando piccolo" data-separati>No, è un'altra persona ` +
        `con lo stesso nome</button></div></div></div>`;

    dove.querySelectorAll("[data-unisci]").forEach((tasto) => {
        tasto.addEventListener("click", () => daiIlNome(tasto.dataset.unisci));
    });
    dove.querySelector("[data-separati]").addEventListener("click", async () => {

        await mandaModulo(`/api/persone/${gruppo}/nome`,
                          { nome, unisci_a: "", accetta_omonimo: "1" });
        window.location.reload();
    });
}

$("dai-il-nome").addEventListener("click", () => daiIlNome());
$("nome").addEventListener("keydown", (evento) => {
    if (evento.key === "Enter") { evento.preventDefault(); daiIlNome(); }
});
if (!document.querySelector("[data-senza-fuoco]")) $("nome").focus();
