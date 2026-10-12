const TRE = "/statici/js/terzi/three.module.min.js";
const DURATA_DEL_VOLO = 850;
const VICINO = 0.05;
const LONTANO = 400;
const LATO_DEL_QUADRETTO = 0.5;
const PRESET = { intorno: [0.6, 0.62], alto: [0.0, 1.5], persona: [0.3, 0.25] };
const CAMPO_INTORNO = 46;
const CAMPO_VICINO = 40;
const SOTTO_IL_SOFFITTO = 0.35;

const morbido = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
const gettone = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const quante = (n, una, tante) => n + " " + (n === 1 ? una : tante);

const VERTICI_DELLA_PELLE = `
attribute vec2 uvFoto;
attribute float visto;
varying vec2 vUv;
varying float vVisto;
varying vec3 vNormale;
void main() {
    vUv = uvFoto;
    vVisto = visto;
    vNormale = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const COLORI_DELLA_PELLE = `
uniform sampler2D foto;
uniform vec3 argilla;
uniform float conFoto;
uniform float opacita;
varying vec2 vUv;
varying float vVisto;
varying vec3 vNormale;
void main() {
    vec3 n = normalize(vNormale);
    if (!gl_FrontFacing) n = -n;
    float luce = 0.5 + 0.5 * max(dot(n, normalize(vec3(0.35, 0.75, 0.55))), 0.0);
    vec3 creta = argilla * luce;
    vec3 colore = mix(creta, texture2D(foto, vUv).rgb, clamp(vVisto * conFoto, 0.0, 1.0));
    gl_FragColor = vec4(colore, opacita);
}`;

async function leggi(indirizzo, firma) {
    const risposta = await fetch(indirizzo);
    if (!risposta.ok) throw new Error(indirizzo + " " + risposta.status);
    const dati = await risposta.arrayBuffer();
    const testo = new TextDecoder();
    if (dati.byteLength < 8 || testo.decode(new Uint8Array(dati, 0, 4)) !== firma) throw new Error(firma);
    const lunga = new DataView(dati).getUint32(4, true);
    const testa = JSON.parse(testo.decode(new Uint8Array(dati, 8, lunga)));
    let posto = 8 + lunga;
    const prendi = (Tipo, quanti) => {
        const pezzo = new Tipo(dati, posto, quanti);
        posto += Math.ceil((quanti * Tipo.BYTES_PER_ELEMENT) / 4) * 4;
        return pezzo;
    };
    return { testa, prendi };
}

async function lePersone(scatto) {
    const { testa, prendi } = await leggi("/api/scatto/" + scatto + "/in3d/persone", "O3P1");
    if (!testa.facce || !testa.persone.length) return { facce: null, persone: [], macchina: testa.macchina };
    const facce = prendi(testa.grandi ? Uint32Array : Uint16Array, testa.facce * 3);
    const persone = testa.persone.map((p) => ({
        corpo_id: p.corpo_id,
        posti: prendi(Float32Array, p.vertici * 3),
        uv: prendi(Uint16Array, p.vertici * 2),
        visti: prendi(Uint8Array, p.vertici),
    }));
    return { facce, persone, macchina: testa.macchina };
}

async function laNuvola(posto, versione) {
    const { testa, prendi } = await leggi("/api/stanza/" + posto + "/nuvola?v=" + encodeURIComponent(versione), "O3N1");
    return { testa, posti: prendi(Int16Array, testa.punti * 3), colori: prendi(Uint8Array, testa.punti * 3) };
}

function sfera(T, centro, distanza, giro, alto) {
    return new T.Vector3(centro.x + distanza * Math.sin(giro) * Math.cos(alto),
                         centro.y + distanza * Math.sin(alto),
                         centro.z + distanza * Math.cos(giro) * Math.cos(alto));
}

function giroVerso(da, a) {
    return Math.atan2(a.x - da.x, a.z - da.z);
}

function orientamento(T, rotazione) {
    const colonna = (j, segno) => new T.Vector3(segno * rotazione[0][j], segno * rotazione[1][j], segno * rotazione[2][j]);
    const base = new T.Matrix4().makeBasis(colonna(0, 1), colonna(1, -1), colonna(2, -1));
    return new T.Quaternion().setFromRotationMatrix(base);
}

function campoSimmetrico(gradi, aspetto) {
    const meta = Math.tan((gradi * Math.PI) / 360);
    return { sinistra: -meta * aspetto, destra: meta * aspetto, sopra: meta, sotto: -meta };
}

function campoDellaFoto(foto, aspetto) {
    const fuoco = 0.5 / Math.tan(foto.campo / 2);
    const largo = fuoco * (foto.allungo || 1);
    const p = foto.proporzione;
    const sopra = foto.centro_y / fuoco, sotto = -(1 - foto.centro_y) / fuoco;
    const sinistra = (-foto.centro_x * p) / largo, destra = ((1 - foto.centro_x) * p) / largo;
    const mx = (sinistra + destra) / 2, my = (sopra + sotto) / 2;
    let mezzoX = (destra - sinistra) / 2, mezzoY = (sopra - sotto) / 2;
    if (aspetto >= p) mezzoX = mezzoY * aspetto;
    else mezzoY = mezzoX / aspetto;
    return { sinistra: mx - mezzoX, destra: mx + mezzoX, sopra: my + mezzoY, sotto: my - mezzoY };
}

function mescola(a, b, t) {
    const fuori = {};
    Object.keys(a).forEach((k) => { fuori[k] = a[k] + (b[k] - a[k]) * t; });
    return fuori;
}

function cono(T, foto, colore, grande) {
    const gruppo = new T.Group();
    const lungo = grande ? 0.42 : 0.26;
    const alto = lungo * Math.tan(foto.campo / 2);
    const largo = (alto * foto.proporzione) / (foto.allungo || 1);
    const cima = new T.Vector3(0, 0, 0);
    const angoli = [[-largo, -alto], [largo, -alto], [largo, alto], [-largo, alto]]
        .map(([x, y]) => new T.Vector3(x, y, -lungo));
    const segmenti = [];
    angoli.forEach((a, i) => { segmenti.push(cima, a, a, angoli[(i + 1) % 4]); });
    const linee = new T.LineSegments(new T.BufferGeometry().setFromPoints(segmenti),
                                     new T.LineBasicMaterial({ color: colore, transparent: true }));
    const faccia = new T.Mesh(new T.PlaneGeometry(largo * 2, alto * 2),
                              new T.MeshBasicMaterial({ color: colore, transparent: true, opacity: grande ? 0.28 : 0.18,
                                                        side: T.DoubleSide, depthWrite: false }));
    faccia.position.z = -lungo;
    const corpo = new T.Mesh(new T.BoxGeometry(grande ? 0.12 : 0.08, grande ? 0.08 : 0.055, 0.05),
                             new T.MeshBasicMaterial({ color: colore, transparent: true }));
    corpo.position.z = 0.03;
    gruppo.add(linee, faccia, corpo);
    gruppo.position.set(...foto.centro);
    gruppo.quaternion.copy(orientamento(T, foto.rotazione));
    gruppo.userData = { pezzi: [linee, faccia, corpo] };
    return gruppo;
}

function coloraCono(gruppo, colore) {
    gruppo.userData.pezzi.forEach((pezzo) => pezzo.material.color.set(colore));
}

function quadretti(T) {
    const tela = document.createElement("canvas");
    tela.width = tela.height = 2;
    const trama = new T.CanvasTexture(tela);
    trama.wrapS = trama.wrapT = T.RepeatWrapping;
    trama.magFilter = T.NearestFilter;
    trama.minFilter = T.LinearMipmapLinearFilter;
    const dipingi = () => {
        const pennello = tela.getContext("2d");
        const chiaro = gettone("--superficie-alta"), scuro = gettone("--superficie");
        [[0, 0, chiaro], [1, 1, chiaro], [1, 0, scuro], [0, 1, scuro]].forEach(([x, y, c]) => {
            pennello.fillStyle = c;
            pennello.fillRect(x, y, 1, 1);
        });
        trama.needsUpdate = true;
    };
    dipingi();
    return { trama, dipingi };
}

function costruisci(T, finestra, dati, corpi, nuvola) {
    const tela = finestra.querySelector("[data-in3d-tela]");
    const sotto = finestra.querySelector("[data-in3d-foto-sotto]");
    const nomi = finestra.querySelector("[data-in3d-nomi]");
    const didascalia = finestra.querySelector("[data-in3d-didascalia]");
    const cursore = finestra.querySelector("[data-in3d-cursore]");
    const misto = finestra.querySelector("[data-in3d-misto]");
    const apri = finestra.querySelector("[data-in3d-apri]");
    const angolo = finestra.querySelector("[data-in3d-angolo]");
    const coniAcceso = finestra.querySelector("[data-in3d-coni]");
    const elenco = finestra.querySelector("[data-in3d-elenco]");
    const fatti = finestra.querySelector("[data-in3d-fatti]");
    const conStanza = Boolean(dati.stanza && nuvola);

    T.ColorManagement.enabled = false;
    const pennello = new T.WebGLRenderer({ antialias: true, alpha: true });
    pennello.outputColorSpace = T.LinearSRGBColorSpace;
    pennello.localClippingEnabled = true;
    const soffitto = new T.Plane(new T.Vector3(0, -1, 0), 0);
    const davanti = new T.Plane(new T.Vector3(0, 0, -1), 0);
    pennello.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    pennello.setClearColor(0x000000, 0);
    tela.prepend(pennello.domElement);
    const scena = new T.Scene();
    const camera = new T.PerspectiveCamera(CAMPO_INTORNO, 1.6, VICINO, LONTANO);

    let foto = dati.foto.slice();
    if (!conStanza && corpi.macchina && dati.file_id) {
        foto = [{ ...corpi.macchina, scatto_id: dati.scatto_id, file_id: dati.file_id, questa: true, data: "",
                  descrizione: "", obiettivo: dati.obiettivo || "" }];
    }
    const questa = foto.findIndex((f) => f.questa);

    let centro = new T.Vector3(0, 1, 0);
    let raggio = 3;
    let punti = null;
    if (conStanza) {
        const forma = new T.BufferGeometry();
        forma.setAttribute("position", new T.Int16BufferAttribute(nuvola.posti, 3, true));
        forma.setAttribute("color", new T.Uint8BufferAttribute(nuvola.colori, 3, true));
        const lato = Math.max(0.012, 0.02 * Math.cbrt(Math.max(dati.stanza.larga * dati.stanza.lunga * dati.stanza.alta, 1) / 40));
        punti = new T.Points(forma, new T.PointsMaterial({ size: lato, vertexColors: true, sizeAttenuation: true,
                                                            transparent: true, clippingPlanes: [] }));
        punti.position.set(...nuvola.testa.centro);
        punti.scale.set(...nuvola.testa.mezzo);
        punti.frustumCulled = false;
        scena.add(punti);
        centro = new T.Vector3(0, dati.stanza.alta * 0.35, 0);
        raggio = Math.max(1.5, 0.5 * Math.hypot(dati.stanza.larga, dati.stanza.lunga, dati.stanza.alta));
    }

    const trama = new T.Texture();
    trama.flipY = false;
    const argilla = new T.Color(gettone("--argilla"));
    const pelle = new T.ShaderMaterial({
        uniforms: { foto: { value: trama }, argilla: { value: argilla }, conFoto: { value: 0 }, opacita: { value: 1 } },
        vertexShader: VERTICI_DELLA_PELLE, fragmentShader: COLORI_DELLA_PELLE, transparent: true, side: T.DoubleSide,
    });
    const indici = corpi.facce ? new T.BufferAttribute(corpi.facce, 1) : null;
    const persone = [];
    corpi.persone.forEach((corpo) => {
        const chi = dati.persone.find((p) => p.corpo_id === corpo.corpo_id);
        if (!chi) return;
        const forma = new T.BufferGeometry();
        forma.setAttribute("position", new T.BufferAttribute(corpo.posti, 3));
        forma.setAttribute("uvFoto", new T.Uint16BufferAttribute(corpo.uv, 2, true));
        forma.setAttribute("visto", new T.Uint8BufferAttribute(corpo.visti, 1, true));
        forma.setIndex(indici);
        forma.computeVertexNormals();
        forma.computeBoundingBox();
        const maglia = new T.Mesh(forma, pelle);
        scena.add(maglia);
        const scatola = forma.boundingBox;
        const mezzo = scatola.getCenter(new T.Vector3());
        const anello = new T.Mesh(new T.RingGeometry(0.3, 0.36, 48),
                                  new T.MeshBasicMaterial({ color: chi.colore, side: T.DoubleSide, transparent: true }));
        anello.rotation.x = -Math.PI / 2;
        anello.position.set(mezzo.x, scatola.min.y + 0.012, mezzo.z);
        scena.add(anello);
        const scritta = document.createElement("span");
        scritta.className = "in3d-chi";
        scritta.textContent = chi.nome;
        scritta.style.background = chi.colore;
        nomi.append(scritta);
        persone.push({ chi, maglia, anello, scritta, mezzo, testa: new T.Vector3(mezzo.x, scatola.max.y + 0.08, mezzo.z),
                       alta: Math.max(0.5, scatola.max.y - scatola.min.y) });
    });

    let pavimento = null;
    let dipingiPavimento = null;
    if (!conStanza) {
        const insieme = new T.Box3();
        persone.forEach((p) => insieme.union(p.maglia.geometry.boundingBox));
        if (!insieme.isEmpty()) {
            const mezzo = insieme.getCenter(new T.Vector3());
            const misura = insieme.getSize(new T.Vector3());
            centro = new T.Vector3(mezzo.x, Math.max(0.6, misura.y * 0.5), mezzo.z);
            raggio = Math.max(1.6, 0.6 * Math.hypot(misura.x, misura.y, misura.z));
        }
        const lato = Math.max(8, Math.ceil(raggio * 4));
        const fatto = quadretti(T);
        fatto.trama.repeat.set(lato / (2 * LATO_DEL_QUADRETTO), lato / (2 * LATO_DEL_QUADRETTO));
        dipingiPavimento = fatto.dipingi;
        pavimento = new T.Mesh(new T.PlaneGeometry(lato, lato),
                               new T.MeshBasicMaterial({ map: fatto.trama, transparent: true, side: T.DoubleSide }));
        pavimento.rotation.x = -Math.PI / 2;
        pavimento.position.set(Math.round(centro.x), 0, Math.round(centro.z));
        scena.add(pavimento);
    }

    const coni = foto.map((f, i) => {
        const c = cono(T, f, gettone(i === questa ? "--accento" : "--altre"), i === questa);
        scena.add(c);
        return c;
    });
    const daQui = document.createElement("span");
    daQui.className = "in3d-chi fotografo";
    daQui.textContent = "Da qui è stata fatta la foto";
    nomi.append(daQui);

    const scelta = { dove: { tipo: "intorno" }, chi: null, coni: true, quanto: Number(misto.value) / 100 };
    const stato = { giro: PRESET.intorno[0], alto: PRESET.intorno[1], vicino: 1 };
    if (questa >= 0) stato.giro = giroVerso(centro, new T.Vector3(...foto[questa].centro)) + PRESET.intorno[0];
    let volo = null;
    let aperta = false;
    const misura = { larga: 0, alta: 0 };
    let fotoCaricata = false;

    const aspetto = () => Math.max(tela.clientWidth, 1) / Math.max(tela.clientHeight, 1);

    function posa(dove) {
        if (dove.tipo === "foto") {
            const f = foto[dove.i];
            return { da: new T.Vector3(...f.centro), giro: orientamento(T, f.rotazione), campo: campoDellaFoto(f, aspetto()) };
        }
        let mira = centro, distanza = raggio * 2.2 * stato.vicino, alto = stato.alto, gradi = CAMPO_INTORNO;
        if (dove.tipo === "persona" && persone.length) {
            const p = persone[scelta.chi === null ? 0 : scelta.chi];
            mira = p.mezzo;
            distanza = Math.max(1.6, p.alta * 1.9) * stato.vicino;
            alto = Math.min(stato.alto, 0.5);
            gradi = CAMPO_VICINO;
        }
        const da = sfera(T, mira, Math.max(distanza, 0.4), stato.giro, alto);
        const guarda = new T.Matrix4().lookAt(da, mira, new T.Vector3(0, 1, 0));
        return { da, giro: new T.Quaternion().setFromRotationMatrix(guarda), campo: campoSimmetrico(gradi, aspetto()) };
    }

    function proietta(campo) {
        camera.projectionMatrix.makePerspective(campo.sinistra * VICINO, campo.destra * VICINO, campo.sopra * VICINO,
                                                campo.sotto * VICINO, VICINO, LONTANO);
        camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
    }

    function metti(scritta, punto) {
        const p = punto.clone().project(camera);
        scritta.style.left = ((p.x + 1) / 2) * tela.clientWidth + "px";
        scritta.style.top = ((1 - p.y) / 2) * tela.clientHeight + "px";
        return p.z < 1 && Math.abs(p.x) < 1.05 && Math.abs(p.y) < 1.05;
    }

    function ridisegna() {
        const larga = tela.clientWidth, alta = tela.clientHeight;
        if (!aperta || !larga || !alta) return;
        if (larga !== misura.larga || alta !== misura.alta) {
            pennello.setSize(larga, alta, false);
            misura.larga = larga;
            misura.alta = alta;
        }
        const meta = posa(scelta.dove);
        let da = meta.da, giro = meta.giro, campo = meta.campo;
        if (volo) {
            da = volo.da.clone().lerp(meta.da, volo.t);
            giro = volo.giro.clone().slerp(meta.giro, volo.t);
            campo = mescola(volo.campo, meta.campo, volo.t);
        }
        camera.position.copy(da);
        camera.quaternion.copy(giro);
        camera.updateMatrixWorld(true);
        proietta(campo);
        const inFoto = scelta.dove.tipo === "foto";
        const fermo = inFoto && !volo;
        const altra = inFoto && scelta.dove.i !== questa;
        const q = fermo ? scelta.quanto : 1;
        pennello.setClearColor(new T.Color(gettone("--pozzo")), fermo ? q * 0.85 : 0);
        if (punti) {
            punti.material.opacity = q;
            punti.material.clippingPlanes = inFoto ? [] : taglia(camera.position);
        }
        if (pavimento) pavimento.material.opacity = q;
        pelle.uniforms.opacita.value = q;
        const conPersone = !altra && q > 0.02;
        persone.forEach((p, i) => {
            p.maglia.visible = conPersone;
            p.anello.visible = conPersone;
            p.anello.material.opacity = q;
            p.anello.scale.setScalar(scelta.chi === i ? 1.35 : 1);
        });
        coni.forEach((c, i) => {
            const qui = inFoto && scelta.dove.i === i && (!volo || volo.t > 0.8);
            c.visible = !qui && (i === questa || (scelta.coni && !fermo));
        });
        pennello.render(scena, camera);
        const via = altra || (fermo && scelta.quanto < 0.35);
        persone.forEach((p) => { p.scritta.hidden = !metti(p.scritta, p.testa) || via; });
        if (questa >= 0) {
            const sopra = new T.Vector3(...foto[questa].centro).add(new T.Vector3(0, 0.16, 0));
            daQui.hidden = !metti(daQui, sopra) || inFoto || Boolean(volo);
        } else {
            daQui.hidden = true;
        }
    }

    function taglia(da) {
        const piani = [];
        const alta = dati.stanza.alta;
        if (da.y > alta - SOTTO_IL_SOFFITTO) {
            soffitto.constant = alta - SOTTO_IL_SOFFITTO;
            piani.push(soffitto);
        }
        const verso = new T.Vector3(da.x - centro.x, 0, da.z - centro.z);
        const lontano = verso.length();
        const mezzo = 0.5 * Math.min(dati.stanza.larga, dati.stanza.lunga);
        if (lontano > mezzo + 0.3) {
            verso.normalize();
            davanti.normal.set(-verso.x, 0, -verso.z);
            davanti.constant = mezzo * 0.8 + verso.x * centro.x + verso.z * centro.z;
            piani.push(davanti);
        }
        return piani;
    }

    function vai(dove, conPreset) {
        const mio = { da: camera.position.clone(), giro: camera.quaternion.clone(), campo: posaAttuale(), t: 0,
                      partito: performance.now() };
        if (dove.tipo === "persona" && scelta.chi === null) scelta.chi = 0;
        if (conPreset && PRESET[dove.tipo]) {
            stato.alto = PRESET[dove.tipo][1];
            stato.vicino = 1;
            if (dove.tipo === "persona" && persone.length) {
                const p = persone[scelta.chi];
                const verso = questa >= 0 ? new T.Vector3(...foto[questa].centro) : centro;
                stato.giro = giroVerso(p.mezzo, verso) + PRESET.persona[0];
            } else if (dove.tipo === "intorno" && questa >= 0) {
                stato.giro = giroVerso(centro, new T.Vector3(...foto[questa].centro)) + PRESET.intorno[0];
            } else {
                stato.giro = PRESET[dove.tipo][0];
            }
        }
        scelta.dove = dove;
        volo = mio;
        aggiorna();
        const passo = (ora) => {
            if (volo !== mio) return;
            const t = Math.min(1, (ora - mio.partito) / DURATA_DEL_VOLO);
            mio.t = morbido(t);
            if (t >= 1) {
                volo = null;
                aggiorna();
            }
            ridisegna();
            if (volo === mio) requestAnimationFrame(passo);
        };
        requestAnimationFrame(passo);
    }

    let ultimoCampo = campoSimmetrico(CAMPO_INTORNO, 1.6);
    function posaAttuale() {
        const e = camera.projectionMatrix.elements;
        const sinistra = (e[8] - 1) / e[0], destra = (e[8] + 1) / e[0];
        const sotto = (e[9] - 1) / e[5], sopra = (e[9] + 1) / e[5];
        if ([sinistra, destra, sotto, sopra].every(Number.isFinite)) ultimoCampo = { sinistra, destra, sopra, sotto };
        return ultimoCampo;
    }

    function indirizzoDellaFoto(f, grande) {
        if (f.questa) return "/in3d/foto/" + f.file_id + "?lato=" + grande;
        return "/immagine/" + f.file_id;
    }

    const LATO_GRANDE = Math.min(pennello.capabilities.maxTextureSize || 4096, 16384);

    function aggiorna() {
        const inFoto = scelta.dove.tipo === "foto";
        const fermo = inFoto && !volo;
        const chiave = inFoto ? "foto:" + scelta.dove.i : scelta.dove.tipo;
        finestra.querySelectorAll("[data-in3d-dove]").forEach((b) => {
            b.setAttribute("aria-pressed", b.dataset.in3dDove === chiave ? "true" : "false");
        });
        finestra.querySelectorAll("[data-in3d-chi]").forEach((b) => {
            b.setAttribute("aria-pressed", Number(b.dataset.in3dChi) === scelta.chi ? "true" : "false");
        });
        const f = inFoto ? foto[scelta.dove.i] : foto[questa];
        const altra = inFoto && scelta.dove.i !== questa;
        cursore.hidden = !fermo;
        apri.hidden = !(fermo && altra);
        if (fermo && altra) apri.href = "/scatto/" + f.scatto_id + location.search;
        if (fermo) {
            const voluta = indirizzoDellaFoto(f, LATO_GRANDE);
            if (sotto.getAttribute("src") !== voluta) {
                sotto.classList.remove("si");
                sotto.src = voluta;
                sotto.decode().then(() => {
                    if (sotto.getAttribute("src") === voluta && scelta.dove.tipo === "foto" && !volo) sotto.classList.add("si");
                }, () => {});
            } else {
                sotto.classList.add("si");
            }
        } else {
            sotto.classList.remove("si");
        }
        angolo.hidden = inFoto || questa < 0;
        didascalia.hidden = !inFoto;
        if (inFoto) {
            didascalia.textContent = altra ? [f.data, f.descrizione].filter(Boolean).join(" · ")
                : "Sei dove stava la macchina fotografica";
        }
        scriviIFatti(f, altra);
    }

    function riga(nome, valore) {
        if (!valore) return [];
        const dt = document.createElement("dt");
        dt.textContent = nome;
        const dd = document.createElement("dd");
        dd.textContent = valore;
        return [dt, dd];
    }

    function scriviIFatti(f, altra) {
        const righe = [];
        if (conStanza) {
            righe.push(...riga("Costruita da", dati.stanza.costruita_da), ...riga("Misure", dati.stanza.misure));
            if (f) {
                righe.push(...riga(altra ? "Foto scelta" : "Questa foto",
                                   (altra && f.data ? f.data + ", " : "") + f.descrizione));
                righe.push(...riga("Obiettivo", f.obiettivo));
            } else {
                righe.push(...riga("Questa foto", "non si è riusciti a metterla nella stanza"));
                righe.push(...riga("Obiettivo", dati.obiettivo));
            }
        } else {
            righe.push(...riga("Il luogo", "senza stanza in 3D: servono almeno 5 foto dello stesso luogo"));
            righe.push(...riga("Obiettivo", dati.obiettivo || (f && f.obiettivo)));
        }
        fatti.replaceChildren(...righe);
    }

    const morso = { tieni: null, mosso: false };
    tela.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 || e.target.closest("button, input, label, a, [data-in3d-cursore]")) return;
        morso.tieni = { x: e.clientX, y: e.clientY };
        morso.mosso = false;
        tela.setPointerCapture(e.pointerId);
    });
    tela.addEventListener("pointermove", (e) => {
        const tieni = morso.tieni;
        if (!tieni) return;
        if (!morso.mosso) {
            if (Math.abs(e.clientX - tieni.x) + Math.abs(e.clientY - tieni.y) <= 3) return;
            morso.mosso = true;
            tela.classList.add("trascina");
            if (scelta.dove.tipo === "foto" || scelta.dove.tipo === "alto") {
                const v = camera.position.clone().sub(centro);
                stato.giro = Math.atan2(v.x, v.z);
                stato.alto = Math.max(0.02, Math.min(1.5, Math.asin(Math.max(-1, Math.min(1, v.y / Math.max(v.length(), 1e-6))))));
                stato.vicino = Math.max(0.3, Math.min(3, v.length() / (raggio * 2.2)));
                vai({ tipo: "intorno" });
            }
            morso.tieni = { x: e.clientX, y: e.clientY, giro: stato.giro, alto: stato.alto };
            return;
        }
        stato.giro = tieni.giro - (e.clientX - tieni.x) * 0.01;
        stato.alto = Math.max(0.02, Math.min(1.5, tieni.alto + (e.clientY - tieni.y) * 0.007));
        if (!volo) ridisegna();
    });
    const lascia = (e) => {
        if (morso.tieni && !morso.mosso) {
            const i = cercaCono(e);
            if (i !== null) vai({ tipo: "foto", i });
        }
        morso.tieni = null;
        tela.classList.remove("trascina");
    };
    tela.addEventListener("pointerup", lascia);
    tela.addEventListener("pointercancel", () => { morso.tieni = null; tela.classList.remove("trascina"); });
    tela.addEventListener("wheel", (e) => {
        if (scelta.dove.tipo === "foto") return;
        e.preventDefault();
        stato.vicino = Math.max(0.3, Math.min(3, stato.vicino * Math.exp(e.deltaY * 0.001)));
        if (!volo) ridisegna();
    }, { passive: false });

    function cercaCono(e) {
        const riquadro = tela.getBoundingClientRect();
        const x = ((e.clientX - riquadro.left) / riquadro.width) * 2 - 1;
        const y = -((e.clientY - riquadro.top) / riquadro.height) * 2 + 1;
        let migliore = null, vicino = 0.07;
        coni.forEach((c, i) => {
            if (!c.visible) return;
            const p = c.position.clone().project(camera);
            if (p.z > 1) return;
            const d = Math.hypot(p.x - x, p.y - y);
            if (d < vicino) { vicino = d; migliore = i; }
        });
        return migliore;
    }

    finestra.addEventListener("click", (e) => {
        const dove = e.target.closest("[data-in3d-dove]");
        if (dove) {
            const v = dove.dataset.in3dDove;
            if (v.startsWith("foto:")) vai({ tipo: "foto", i: Number(v.slice(5)) });
            else vai({ tipo: v }, true);
            return;
        }
        if (e.target.closest("[data-in3d-angolo]")) {
            if (questa >= 0) vai({ tipo: "foto", i: questa });
            return;
        }
        const chi = e.target.closest("[data-in3d-chi]");
        if (chi) {
            const i = Number(chi.dataset.in3dChi);
            scelta.chi = scelta.chi === i ? null : i;
            vai({ tipo: scelta.chi === null ? "intorno" : "persona" }, true);
        }
    });
    misto.addEventListener("input", () => {
        scelta.quanto = Number(misto.value) / 100;
        ridisegna();
    });
    coniAcceso.addEventListener("change", () => {
        scelta.coni = coniAcceso.checked;
        ridisegna();
    });

    const scheda = finestra.querySelector("[data-in3d-persone]");
    scheda.replaceChildren(...persone.map((p, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "in3d-pillola";
        b.dataset.in3dChi = String(i);
        b.setAttribute("aria-pressed", "false");
        const pallino = document.createElement("i");
        pallino.style.background = p.chi.colore;
        b.append(pallino, p.chi.nome);
        return b;
    }));
    finestra.querySelector("[data-in3d-blocco-persone]").hidden = !persone.length;
    finestra.querySelector("[data-in3d-vicino]").hidden = !persone.length;
    finestra.querySelector("[data-in3d-intorno]").textContent = conStanza ? "Tutta la stanza" : "Tutte le persone";
    finestra.querySelector("[data-in3d-misto-nome]").textContent = conStanza ? "Stanza 3D" : "Persone in 3D";
    misto.setAttribute("aria-label", conStanza ? "Quanto si vede la stanza 3D sopra la foto"
        : "Quanto si vedono le persone in 3D sopra la foto");
    finestra.querySelector("[data-in3d-aiuto]").textContent = conStanza
        ? "Trascina per girarla · clic su un cono per andarci" : "Trascina per girare intorno";
    finestra.querySelector("[data-in3d-titolo]").textContent = conStanza
        ? dati.stanza.nome + " in 3D · " + quante(persone.length, "persona", "persone") + " · " + quante(foto.length, "foto", "foto")
        : "Le persone in 3D · " + quante(persone.length, "persona", "persone");
    finestra.querySelector("[data-in3d-fatti-titolo]").textContent = conStanza ? "La stanza" : "La foto";
    finestra.querySelector("[data-in3d-blocco-fatti]").hidden = false;
    finestra.querySelector("[data-in3d-blocco-coni]").hidden = !conStanza || foto.length < 2;
    finestra.querySelector("[data-in3d-blocco-foto]").hidden = !conStanza || !foto.length;
    elenco.replaceChildren(...(conStanza ? foto : []).map((f, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "in3d-miniatura" + (f.questa ? " questa" : "");
        b.dataset.in3dDove = "foto:" + i;
        b.setAttribute("aria-pressed", "false");
        b.title = [f.data, f.descrizione].filter(Boolean).join(" · ");
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = "";
        img.src = "/miniatura/" + f.file_id;
        const scritta = document.createElement("span");
        scritta.textContent = f.questa ? "Questa foto" : f.data;
        b.append(img, scritta);
        return b;
    }));
    if (questa >= 0) finestra.querySelector("[data-in3d-angolo-foto]").src = "/miniatura/" + foto[questa].file_id;

    function caricaLaFoto() {
        if (fotoCaricata || !persone.length || !dati.file_id) return;
        fotoCaricata = true;
        const immagine = new Image();
        immagine.decoding = "async";
        immagine.onload = () => {
            trama.image = immagine;
            trama.anisotropy = pennello.capabilities.getMaxAnisotropy();
            trama.needsUpdate = true;
            pelle.uniforms.conFoto.value = 1;
            ridisegna();
        };
        immagine.src = "/in3d/foto/" + dati.file_id + "?lato=" + LATO_GRANDE;
    }

    function ricolora() {
        argilla.set(gettone("--argilla"));
        coni.forEach((c, i) => coloraCono(c, gettone(i === questa ? "--accento" : "--altre")));
        if (dipingiPavimento) dipingiPavimento();
        ridisegna();
    }
    const scuro = window.matchMedia("(prefers-color-scheme: dark)");
    if (scuro.addEventListener) scuro.addEventListener("change", ricolora);
    new MutationObserver(ricolora).observe(document.documentElement, { attributes: true,
                                                                       attributeFilter: ["data-theme", "data-accento"] });
    if (window.ResizeObserver) new ResizeObserver(() => { if (!volo) ridisegna(); }).observe(tela);
    pennello.domElement.addEventListener("webglcontextlost", (e) => {
        e.preventDefault();
        const scritta = finestra.querySelector("[data-in3d-stato]");
        scritta.hidden = false;
        scritta.textContent = "La scheda video ha dovuto lasciare il 3D. Chiudi e riapri la finestra.";
    });
    pennello.domElement.addEventListener("webglcontextrestored", () => {
        finestra.querySelector("[data-in3d-stato]").hidden = true;
        trama.needsUpdate = true;
        ridisegna();
    });

    aggiorna();
    return {
        apri() {
            aperta = true;
            caricaLaFoto();
            ridisegna();
        },
        chiudi() {
            aperta = false;
            if (volo) {
                volo = null;
                aggiorna();
            }
        },
    };
}

export function preparaIn3d() {
    const tasto = document.querySelector("[data-apri-3d]");
    const finestra = document.getElementById("in3d");
    if (!tasto || !finestra) return;
    const scritta = finestra.querySelector("[data-in3d-stato]");
    let pronta = null;

    async function prepara() {
        const scatto = finestra.dataset.scatto;
        const [T, risposta] = await Promise.all([import(TRE), fetch("/api/scatto/" + scatto + "/in3d")]);
        if (!risposta.ok) {
            const corpo = await risposta.json().catch(() => ({}));
            throw new Error(corpo.messaggio || "Questa foto non ha ancora niente in 3D.");
        }
        const dati = await risposta.json();
        const [corpi, nuvola] = await Promise.all([
            lePersone(scatto).catch(() => ({ facce: null, persone: [], macchina: null })),
            dati.stanza ? laNuvola(dati.stanza.posto_id, dati.stanza.versione).catch(() => null) : Promise.resolve(null),
        ]);
        return costruisci(T, finestra, dati, corpi, nuvola);
    }

    tasto.addEventListener("click", () => {
        if (!finestra.open) finestra.showModal();
        if (!pronta) {
            scritta.hidden = false;
            scritta.textContent = "Sto preparando il 3D…";
            pronta = prepara().then((vista) => {
                scritta.hidden = true;
                return vista;
            }, (guasto) => {
                pronta = null;
                scritta.textContent = guasto instanceof Error && guasto.message.startsWith("Questa")
                    ? guasto.message : "Il 3D non si è caricato. Chiudi e riprova.";
                return null;
            });
        }
        pronta.then((vista) => { if (vista && finestra.open) vista.apri(); });
    });
    finestra.querySelector("[data-in3d-chiudi]").addEventListener("click", () => finestra.close());
    finestra.addEventListener("close", () => { if (pronta) pronta.then((vista) => vista && vista.chiudi()); });
    finestra.addEventListener("click", (e) => { if (e.target === finestra) finestra.close(); });
}
