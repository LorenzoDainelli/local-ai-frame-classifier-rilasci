from __future__ import annotations

import json
import sys
import urllib.request

CHI = "officina-collaudo/1.0"


def chiedi(indirizzo: str):
    richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": CHI})
    with urllib.request.urlopen(richiesta, timeout=60) as risposta:
        return json.loads(risposta.read())


def main() -> int:
    deposito, *parole = sys.argv[1:]
    dati = chiedi(f"https://huggingface.co/api/models/{deposito}")
    revisione = dati["sha"]
    print("DEPOSITO", deposito, "REVISIONE", revisione,
          "LICENZA", (dati.get("cardData") or {}).get("license"))
    albero = chiedi(f"https://huggingface.co/api/models/{deposito}/tree/{revisione}")
    for voce in albero:
        if not parole or any(p in voce["path"] for p in parole):
            print("FILE", voce["path"], voce.get("size"), (voce.get("lfs") or {}).get("oid"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
