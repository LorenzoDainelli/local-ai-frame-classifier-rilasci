from __future__ import annotations


class InsiemiUniti:

    __slots__ = ("_padre",)

    def __init__(self) -> None:
        self._padre: dict[int, int] = {}

    def _radice(self, quale: int) -> int:
        self._padre.setdefault(quale, quale)
        while self._padre[quale] != quale:
            self._padre[quale] = self._padre[self._padre[quale]]
            quale = self._padre[quale]
        return quale

    def unisci(self, uno: int, altro: int) -> None:
        primo, secondo = self._radice(uno), self._radice(altro)
        if primo != secondo:
            self._padre[secondo] = primo

    def aggiungi(self, quale: int) -> None:
        self._radice(quale)

    def gruppi(self, anche_i_soli: bool = False) -> list[list[int]]:
        raccolti: dict[int, list[int]] = {}
        for quale in self._padre:
            raccolti.setdefault(self._radice(quale), []).append(quale)
        fatti = [sorted(membri) for membri in raccolti.values()
                 if anche_i_soli or len(membri) > 1]
        fatti.sort(key=lambda membri: membri[0])
        return fatti
