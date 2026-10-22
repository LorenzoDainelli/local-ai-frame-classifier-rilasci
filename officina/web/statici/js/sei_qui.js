const OGNI = 10000;
let ultimo = 0;

function seiQui() {
    const adesso = Date.now();
    if (adesso - ultimo < OGNI) return;
    ultimo = adesso;
    fetch("/api/sei-qui", { method: "POST", keepalive: true }).catch(() => { });
}

["mousedown", "keydown", "wheel", "touchstart"].forEach(
    (quale) => document.addEventListener(quale, seiQui, { passive: true, capture: true }));

seiQui();
