"""Bewertungskriterien — domänenunabhängig.

Ein Judge ist in jedem Use-Case dasselbe: ein Agent, der eine Ausgabe nach
**einem** Kriterium bepunktet, und eine Schwelle, ab der etwas durchfällt. Was
sich unterscheidet, sind die Fragen und das Wissen, das zu ihrer Beantwortung
nötig ist.

**Die Lehre, die dieses Modul kodiert:** Manche Kriterien sind ohne Domänenwissen
schlicht unbeantwortbar. „Ist das überhaupt ein Fehler?" hängt davon ab, was in
diesem Werk, dieser Firma, diesem Datensatz als richtig gilt. Gemessen am
Buch-Lektorat: Ohne Kontext lag der Judge bei 10/12, mit Kontext bei 12/12 — der
Unterschied waren ausschließlich Fälle, in denen er allgemeines Schriftdeutsch
gegen die Eigenheiten des Werks ausspielte.

Deshalb deklariert ein Kriterium, **ob** es Kontext braucht, und die Domäne
liefert ihn über einen Callback. Fehlt er, warnt der Katalog — statt still
schlechter zu urteilen.

    katalog = Kriterienkatalog.aus_config(
        cfg["judges"]["kriterien"],
        kontext=meine_kontext_funktion,   # (kriterium) -> str
    )
    for name in katalog.aktive:
        ...  # frage(name), kontext(name), sperrt(name, score)

Rein: keine I/O, kein Modell. Der Agent-Aufruf bleibt Sache der Domäne, weil
Workflows ihre Aktivitäten selbst deklarieren müssen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Kriterium:
    """Eine Bewertungsdimension.

    ``braucht_kontext`` ist der Hebel, um den es hier geht: Ein Kriterium, das
    Domänenwissen voraussetzt, sagt das selbst — und wer es benutzt, kann prüfen,
    ob das Wissen auch ankommt.
    """

    name: str
    frage: str
    sperrt_unter: int | None = None
    aktiv: bool = False
    braucht_kontext: bool = False
    skala: str = "1-5"

    @classmethod
    def aus_dict(cls, name: str, d: dict[str, Any]) -> Kriterium:
        return cls(
            name=name,
            frage=d.get("frage", name),
            sperrt_unter=d.get("sperrt_unter"),
            aktiv=bool(d.get("aktiv")),
            braucht_kontext=bool(d.get("braucht_kontext")),
            skala=d.get("skala", "1-5"),
        )

    def sperrt(self, score: int | float | None) -> bool:
        """Ob dieser Score den bewerteten Gegenstand zurückhält."""
        if self.sperrt_unter is None or score is None:
            return False
        return float(score) < float(self.sperrt_unter)


@dataclass
class Kriterienkatalog:
    """Die Kriterien einer Domäne samt ihrer Kontextversorgung."""

    kriterien: dict[str, Kriterium] = field(default_factory=dict)
    kontext_fn: Callable[[str], str] | None = None

    @classmethod
    def aus_config(
        cls,
        roh: dict[str, Any],
        *,
        kontext: Callable[[str], str] | None = None,
    ) -> Kriterienkatalog:
        """Baut den Katalog aus dem ``judges.kriterien``-Block einer Domänen-Config."""
        return cls(
            kriterien={
                name: Kriterium.aus_dict(name, d)
                for name, d in roh.items()
                if not name.startswith("_") and isinstance(d, dict)
            },
            kontext_fn=kontext,
        )

    @property
    def aktive(self) -> list[str]:
        return [n for n, k in self.kriterien.items() if k.aktiv]

    @property
    def sperrende(self) -> list[str]:
        """Kriterien, die etwas zurückhalten dürfen.

        Sollten wenige sein — am besten genau eines je Risikoart. Ein Katalog, in
        dem alles sperrt, lässt nichts mehr durch.
        """
        return [n for n, k in self.kriterien.items() if k.aktiv and k.sperrt_unter is not None]

    def frage(self, name: str) -> str:
        k = self.kriterien.get(name)
        return k.frage if k else name

    def kontext(self, name: str) -> str:
        """Das Domänenwissen für dieses Kriterium — leer, wenn keins nötig ist."""
        k = self.kriterien.get(name)
        if k is None or not self.kontext_fn:
            return ""
        return self.kontext_fn(name) or ""

    def sperrt(self, name: str, score: int | float | None) -> bool:
        k = self.kriterien.get(name)
        return bool(k and k.sperrt(score))

    def fehlender_kontext(self) -> list[str]:
        """Aktive Kriterien, die Kontext brauchen, aber keinen bekommen.

        Der wichtigste Aufruf dieses Moduls: Ein Kriterium, das ohne sein
        Domänenwissen läuft, urteilt nicht etwa gar nicht — es urteilt still
        falsch, nach allgemeinen Maßstäben statt nach denen der Domäne.
        """
        return [
            n
            for n in self.aktive
            if self.kriterien[n].braucht_kontext and not self.kontext(n).strip()
        ]

    def auftrag(self, name: str, **felder: Any) -> dict[str, Any]:
        """Baut den Auftrag für einen Judge-Aufruf.

        Einheitliche Form über alle Domänen: ``kriterium``, ``frage``, ``kontext``
        plus was der Aufrufer an Nutzdaten mitgibt.
        """
        return {
            "kriterium": name,
            "frage": self.frage(name),
            "kontext": self.kontext(name),
            **felder,
        }
