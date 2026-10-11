if (!location.pathname.startsWith("/schermo/")) {
    const guarda = async () => {
        try {
            const risposta = await fetch("/api/schermo", { headers: { accept: "application/json" } });
            if (risposta.ok) {
                const dati = await risposta.json();
                if (dati.collegato) { location.href = "/schermo/coperta"; return; }
                if (!dati.aperta) return;
            }
        } catch (errore) {}
        setTimeout(guarda, 1000);
    };
    setTimeout(guarda, 1000);
}
