from __future__ import annotations

import sys

from prove.stanza_coi_finti import FINTI


def main() -> int:
    from officina.miglioria import motori

    motori.FOTO.update(FINTI)
    from officina.miglioria import giro_lucidflux_stanza

    return giro_lucidflux_stanza.main()


if __name__ == "__main__":
    sys.exit(main())
