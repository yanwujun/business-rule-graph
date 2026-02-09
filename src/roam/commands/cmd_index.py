import time

import click


@click.command()
@click.option('--force', is_flag=True, help='Force full reindex')
@click.option('--verbose', is_flag=True, help='Show detailed warnings during indexing')
def index(force, verbose):
    """Build or rebuild the codebase index."""
    from roam.index.indexer import Indexer
    t0 = time.monotonic()
    indexer = Indexer()
    indexer.run(force=force, verbose=verbose)
    elapsed = time.monotonic() - t0
    click.echo(f"Index complete. ({elapsed:.1f}s)")
