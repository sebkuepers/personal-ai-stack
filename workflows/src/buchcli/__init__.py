"""Lokale Kommandozeilen-Werkzeuge der Buch-Domäne.

Hier liegt alles, was **das Dateisystem des Autors berührt** — und nur hier. Der
produktive Workflow-Worker läuft im Cloudflare-Container und kommt an
``~/Werk/…`` nicht heran; Export, PDF-Satz und Write-back können deshalb keine
Workflows sein.

  sync      Scrivener → manuskript.json + Markdown (+ Mistral Library)
  anwenden  eine Lektoratssitzung abgesichert ins Scrivener-Projekt schreiben
  pdf       das Manuskript setzen

Aufruf über die Makefile-Ziele in ``workflows/Makefile`` (``make buch-sync`` …).
"""
