from __future__ import annotations

import sys

FINTI = {"lucidflux": "prove.test_miglioria_giro_lucidflux:FintoLucid",
         "seedvr2": "prove.test_miglioria_giro_lucidflux:FintoSeed"}


def main() -> int:
    from officina.miglioria import motori

    motori.FOTO.update(FINTI)
    from officina.miglioria import stanza

    return stanza.main()


if __name__ == "__main__":
    sys.exit(main())
