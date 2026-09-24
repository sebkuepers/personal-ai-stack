"""Local command-line tools of the book domain.

Everything that **touches the author's file system** lives here — and only here.
The production workflow worker runs in the Cloudflare container and cannot reach
``~/Werk/…``; export, PDF typesetting and write-back therefore cannot be
workflows.

  sync     Scrivener → manuskript.json + Markdown (+ Mistral Library)
  apply    write an editing session into the Scrivener project, guarded
  pdf      typeset the manuscript

Invoked through the Makefile targets in ``workflows/Makefile`` (``make book-sync`` …).

Output and error messages stay German: the author reads them.
"""
