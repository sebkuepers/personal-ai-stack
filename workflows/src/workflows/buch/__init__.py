"""Bausteine der Schreib-/Lektoratsdomäne.

Grundsatz dieser Domäne: **die Domäne ist die Fähigkeit, das Werk ist der
Gegenstand.** Agents, Workflows und Skills heißen ``buch-*`` und gelten für jedes
Buch; welches gemeint ist, sagt der Parameter ``werk=<slug>``. So kostet das
zweite Buch keine einzige neue Definition.

Zweite Grundregel, die aus dem Deployment folgt: **kein Workflow fasst das
``.scriv`` an.** Der produktive Worker läuft im Cloudflare-Container und hat
keinen Zugriff auf das lokale Dateisystem. Workflows sind Text rein / Text raus;
Export, PDF-Satz und Write-back sind lokale CLI-Werkzeuge (``buchcli``).

Aufbau:
  config.py       — Domänen- und Werk-Konfiguration aus ``shared/``
  models.py       — Pydantic: Spiegel der Agent-Schemata + Lektorats-Objekte
  scrivener.py    — Binder lesen, RTF dekodieren/kodieren, abgesicherter Write-back
  notizen.py      — die VORHER/NACHHER/WARUM-Blöcke aus notes.rtf auswerten (rein)
  stilmetrik.py   — deterministische Stilkennzahlen (rein, ohne Modell)
  analyse.py      — Aktivitäten: die Lektorats-Agents auslösen
  stimme.py       — Stimmprofil bauen, prüfen, rendern
  pruefungen.py   — Invarianten ohne Ermessen, plus der Werkkontext fürs Gegenlesen
  entscheidungen.py — Entscheidungslog schreiben und auswerten
"""
