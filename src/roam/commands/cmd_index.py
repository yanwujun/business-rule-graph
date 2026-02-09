import click


@click.command()
@click.option('--force', is_flag=True, help='Force full reindex')
def index(force):
    """Build or rebuild the codebase index."""
    from roam.index.indexer import Indexer
    indexer = Indexer()
    indexer.run(force=force)
    click.echo("Index complete.")
