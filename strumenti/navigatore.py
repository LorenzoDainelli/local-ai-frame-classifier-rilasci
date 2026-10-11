from __future__ import annotations

import os


def dove_sta() -> str | None:
    return os.environ.get("OFFICINA_CHROMIUM") or None


def apri(teatro):
    return teatro.chromium.launch(executable_path=dove_sta())
