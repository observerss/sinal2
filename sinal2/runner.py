#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" sina l2 runner that runs sinal2 in high concurrency mode """
from gevent import monkey
monkey.patch_all()

import re
import time
import math
import json
import logging
import functools

import tqdm
import gipc
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
            bar = tqdm.tqdm(total=len(self.symbols), desc='overall')
            p = gevent.pool.Pool(5)
            for symbol in self.symbols:
                p.spawn(self.update_symbol, symbol, bar)
            p.join()
            if bar:
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

    def split(self, values, size):
        result_list = []
        for i in range(len(values) // size + 1):
            vs = values[i*size:i*size+size]
            if vs:
                result_list.append(vs)
        return result_list

    def on_data(self, data):
        if self.out:
            if isinstance(data, str):
                data = data.encode('utf-8')
            elif isinstance(data, dict) or isinstance(data, list):
                data = json.dumps(data).encode('utf-8') + b'\n'
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
        for symbols in self.split(self.symbols, self.size):
            g.spawn(self.client.watch, symbols, on_data, parse)
        g.join()
        self.out.close()


class MultiProcessingWatcher(Watcher):
    """ uses multiple processes

    it solves network error problem when 100% cpu is used
    thus lags network(e.g. on Aliyun between 9:30-9:35)
    if you have a strong cpu, you should be fine with plain Watcher
    """
    def __init__(self, username, password, symbols, raw, out, size=50, core=2):
        assert core > 1 and isinstance(core, int)

        self.client = L2Client(username, password)
        self.symbols = symbols or get_all_symbols()
        self.raw = raw
        self.size = size
        self.core = core
        self.out = out
        self.lock = gevent.lock.RLock()

    def main_on_data(self, r, f):
        while True:
            try:
                data = r.get()
            except (gipc.GIPCClosed, EOFError):
                break
            if isinstance(data, str):
                data = data.encode('utf-8')
            elif isinstance(data, dict) or isinstance(data, list):
                data = json.dumps(data).encode('utf-8')
            with self.lock:
                f.write(data)

    def child_on_data(self, w, data):
        w.put(data)
        if time.time() % 86400 > 7 * 3600 + 60:
            self.client.market_closed = True

    def spawn_watchs(self, w, symbols_list):
        parse = False if self.raw else True
        on_data = functools.partial(self.child_on_data, w) if self.out else None
        g = gevent.pool.Group()
        for symbols in symbols_list:
            g.spawn(self.client.watch, symbols, on_data, parse)
        g.join()

    def run(self):
        c = self.client
        if not c.login():
            log.error('login failed')
            return

        symbols_list = self.split(self.symbols, self.size)
        size = int(math.ceil(1. * len(symbols_list) / self.core))
        child_sl = self.split(symbols_list, size)
        f = open(self.out, 'ab') if self.out else None
        ps, gs = [], []
        for i in range(self.core):
            r, w = gipc.pipe()
            g = gevent.spawn(self.main_on_data, r, f)
            p = gipc.start_process(target=self.spawn_watchs, args=(w, child_sl[i]))
            ps.append(p)

        for p in ps:
            p.join()
        for g in gs:
            g.kill()
            g.join()
