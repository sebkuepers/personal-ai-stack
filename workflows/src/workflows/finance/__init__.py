"""The finance domain — private finances, on this machine.

Unlike ``crm`` and ``inbox``, this domain has **no Cloudflare deployment**. Its
worker runs on the author's MacBook, which changes two things and only two:
an activity here may read the file system (the exception ``docs/BOOK.md``
argues for the book domain), and there is no schedule — things run when he runs
them. Writing still happens only in ``financecli``, never in a workflow.

Module map:

* ``config``      — loads ``shared/finance.json`` and the gitignored
                    ``shared/finance/paths.json``. Pure; import it normally.
* ``statements``  — pure parser for the three bank dialects → ``Transaction``.
* ``project55``   — reads the author's planning workbook. **Read only.**
* ``ledger``      — the JSONL ledger: append, deduplicate, read back.
* ``models``      — Pydantic: transactions, agent mirror, report.

Everything under ``shared/finance/`` and ``workflows/data/finance/`` is
gitignored. This repo is public; the bookkeeping is not.
"""
