# -*- coding: utf-8 -*-

import click


@click.group()
def search_suggestions():
    pass


@search_suggestions.command()
def init():
    from .model import create_tables

    click.echo("Creating database tables...")
    create_tables()
    click.secho("Done.", fg="green")


@search_suggestions.command()
def reprocess():
    from . import reprocess

    click.echo("Re-processing stored search terms...")
    reprocess()
    click.secho("Done.", fg="green")


@search_suggestions.command()
def list():
    from ckan.model.meta import Session
    from .model import SearchTerm

    for term in Session.query(SearchTerm).yield_per(100):
        click.echo(term.term)
