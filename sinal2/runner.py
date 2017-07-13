#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" sina l2 runner that runs sinal2 in high concurrency mode """
from gevent import monkey
monkey.patch_all()

import re
import json
import logging

import tqdm
import gevent
import requests
from .sinal2 import L2Client


log = logging.getLogger('sinal2')


def get_all_symbols():
    log.info('fetch all symbols from sina')
    url = ('http://vip.stock.finance.sina.com.cn/quotes_service/api/'
        'json_v2.php/Market_Center.getNameList?page=1&'
        'num=10000&sort=symbol&asc=1&node=')
    headers = {'User-Agent': 'Mozilla/5.0'}
    pat = re.compile(r'symbol:"([^"]+)"')
    symbols = []
    symbols.extend(pat.findall(requests.get(url + 'hs_a').text))
    symbols.extend(pat.findall(requests.get(url + 'hs_b').text))
    symbols = sorted(set(symbols))
    log.info('got {}'.format(len(symbols)))
    return symbols


class Transer(object):

    def __init__(self, username, password, symbols, out):
        self.client = L2Client(username, password)
        self.symbols = symbols or get_all_symbols()
        self.out = open(out, 'w')

    def update_symbol(self, symbol, bar=None):
        try:
            r = self.client.get_trans(symbol, concurrency=10)
            if r:
                if self.out is None:
                    print(r)
                else:
                    self.out.write(r)
        except Exception as e:
            log.exception(str(e))
        finally:
            if bar:
                bar.update(1)

    def run(self):
        if self.client.login():
            # tqdm has bug here, let it be None at now
            bar = None
            p = gevent.pool.Pool(5)
            for symbol in self.symbols:
                p.spawn(self.update_symbol, symbol, bar)
            p.join()
            bar.close()
            self.out.close()
        else:
            log.error('login error')


class Watcher(object):

    def __init__(self, username, password, symbols, raw, out, size=50):
        self.client = L2Client(username, password)
        self.symbols = symbols or get_all_symbols()
        self.raw = raw
        self.size = size
        self.out = self.ensure_file(out) if out else None
        
    def ensure_file(self, out):
        return open(out, 'ab')

    def split_symbols(self):
        size = self.size
        symbols_list = []
        for i in range(len(self.symbols) // size + 1):
            symbols = self.symbols[i*size:i*size+size]
            if symbols:
                symbols_list.append(symbols)
        return symbols_list

    def on_data(self, data):
        if self.out:
            if isinstance(data, str):
                data = data.encode('utf-8')
            elif isinstance(data, dict) or isinstance(data, list):
                data = json.dumps(data).encode('utf-8')
            self.out.write(data)
            if time.time() % 86400 > 7 * 3600 + 60:
                self.client.market_closed = True

    def run(self):
        c = self.client
        if not c.login():
            log.error('login failed')
            return

        on_data = self.on_data if self.out else None
        parse = False if self.raw else True

        g = gevent.pool.Group()
        for symbols in self.split_symbols():
            g.spawn(self.client.watch, symbols, on_data, parse)
        g.join()
        self.out.close()
