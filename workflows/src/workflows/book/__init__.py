"""Building blocks of the writing / editing domain.

Principle of this domain: **the domain is the capability, the work is the
subject.** Agents, workflows and skills are called ``book-*`` and apply to every
book; which one is meant is said by the parameter ``work=<slug>``. That way the
second book costs not a single new definition.

Second ground rule, following from the deployment: **no workflow touches the
``.scriv``.** The production worker runs in the Cloudflare container and has no
access to the local file system. Workflows are text in / text out; export, PDF
typesetting and write-back are local CLI tools (``bookcli``).

Layout:
  config.py        — domain and work configuration from ``shared/``
  models.py        — Pydantic: mirrors of the agent schemas + editing objects
  scrivener.py     — read the binder, decode/encode RTF, guarded write-back
  notes.py         — parse the VORHER/NACHHER/WARUM blocks from notes.rtf (pure)
  stylemetrics.py  — deterministic style metrics (pure, no model)
  agents.py        — activities: trigger the editing agents
  voice.py         — build, check and render the voice profile
  checks.py        — invariants without discretion, plus the work context
  decisions.py     — write and analyse the decision log
  copyedit.py · style.py · voiceprofile.py — the headless workflows
"""
