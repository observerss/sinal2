#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .runner import Watcher, Transer
from .sinal2 import L2Client

import click
import logging

@click.group()
def cli():
    FORMAT = '%(asctime)-15s %(message)s'
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)
    logging.basicConfig(level=logging.INFO, format=FORMAT)


@cli.command()
@click.option('--symbol', '-s', 'symbols', multiple=True, help='symbols to watch')
@click.option('--raw/--no-raw', default=False, is_flag=True, help='dump raw data')
@click.option('--out', '-o', default=None, help='output file if needed')
@click.argument('username', envvar='SINA_USERNAME')
@click.argument('password', envvar='SINA_PASSWORD')
def watch(username, password, symbols, raw, out):
    """ watch symbols """
    w = Watcher(username, password, symbols, raw, out)
    w.run()


@cli.command()
@click.option('--symbol', '-s', 'symbols', multiple=True, help='symbol to download')
@click.option('--out', '-o', default=None, help='output file if needed')
@click.argument('username', envvar='SINA_USERNAME')
@click.argument('password', envvar='SINA_PASSWORD')
def trans(username, password, symbols, out):
    """ download trans """
    t = Transer(username, password, symbols, out)
    t.run()


if __name__ == '__main__':
    cli()
