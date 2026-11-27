from __future__ import annotations

import json
import os
import sys
import urllib.request

POSTI = 20
PER_GLI_ALTRI = 4
MENO = 2
PIU = 16


def _chiedi(via: str) -> dict:
    richiesta = urllib.request.Request(
        f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/{via}",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(richiesta, timeout=20) as risposta:
        return json.load(risposta)


def occupati() -> int:
    questo = os.environ.get("GITHUB_RUN_ID", "")
    quanti = 0
    for stato in ("in_progress", "queued"):
        for corsa in _chiedi(f"actions/runs?status={stato}&per_page=30").get(
                "workflow_runs", []):
            if str(corsa.get("id")) == questo:
                continue
            lavori = _chiedi(f"actions/runs/{corsa['id']}/jobs?filter=latest&per_page=100")
            quanti += sum(1 for lavoro in lavori.get("jobs", [])
                          if lavoro.get("status") in ("in_progress", "queued"))
    return quanti


def quanti_pezzi(liberi: int) -> int:
    return max(MENO, min(PIU, liberi - PER_GLI_ALTRI))


def main() -> int:
    try:
        liberi = POSTI - occupati()
    except Exception as guaio:
        print(f"non so quanti posti sono liberi ({guaio}): ne conto {POSTI // 2}",
              file=sys.stderr)
        liberi = POSTI // 2
    pezzi = quanti_pezzi(liberi)
    print(f"posti liberi {liberi}: {pezzi} pezzi", file=sys.stderr)
    uscita = os.environ.get("GITHUB_OUTPUT")
    righe = f"quanti={pezzi}\npezzi={json.dumps(list(range(1, pezzi + 1)))}\n"
    if uscita:
        with open(uscita, "a", encoding="utf-8") as f:
            f.write(righe)
    else:
        print(righe, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
