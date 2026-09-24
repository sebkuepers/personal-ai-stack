"""The finance CLI — everything that touches the file system lives here.

The same rule as ``bookcli``: a workflow may *read* local files (this domain's
worker runs on the author's machine), but nothing writes or moves a file
outside this package.

    python -m financecli.tidy          # collect everything into one place
    python -m financecli.ingest        # statements → ledger
    python -m financecli.categorise    # ledger → categories, via the agent
    python -m financecli.report        # ledger → workbook + library summaries

Output stays German: the author reads it.
"""
