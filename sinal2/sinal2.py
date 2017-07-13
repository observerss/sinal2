#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" Sina Level2 Data

Sina Level2 Client & Parser, Usage::

>>> c = L2Client(USERNAME, PASSWORD)
>>> if c.login():
...     c.watch(['sh601398'], on_data=None, parse=True)

By default, if no on_data callback is found, L2Printer.on_data
will be used to dump parsed info to stdout

[2017-07-13T11:01:35.910000] TRANS sh601398 ▲ 5.12 x 4
[2017-07-13T11:01:35.960000] TRANS sh601398 ▼ 5.11 x 1
"""
import re
import json
import time
import base64
import select
import random
import string 
import logging
import binascii
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, wait

import rsa
import tqdm
import requests
import websocket


log = logging.getLogger('sinal2')


class Helper(object):
    CODES = string.ascii_letters + string.digits
    CACHES = {}

    @classmethod
    def random_string(cls, length=9):
        return ''.join(random.sample(cls.CODES, length))

    @classmethod
    def get_ip(cls):
        if 'ip' not in cls.CACHES:
            url = 'https://ff.sinajs.cn/?list=sys_clientip'
            resp = requests.get(url)
            ip = re.compile('"([^"]+)"').search(resp.text).group(1)
            cls.CACHES['ip'] = ip
        return cls.CACHES['ip']


class SinaClient(object):
    CLIENT = 'ssologin.js(v1.4.5)'
    user_agent = (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)'
        ' Chrome/48.0.2564.116 Safari/537.36'
    )
    def __init__(self, username, password, entry='finance'):
        self.username = username
        self.password = password
        assert entry in ['finance']
        self.entry = entry
        session = requests.session()
        session.headers['User-Agent'] = self.user_agent
        self.session = session
        self.is_logged_in = False
        self.uid = None
        self.nick = None

    def encrypt_passwd(self, passwd, pubkey, servertime, nonce):
        key = rsa.PublicKey(int(pubkey, 16), int('10001', 16))
        message = str(servertime) + '\t' + str(nonce) + '\n' + str(passwd)
        passwd = rsa.encrypt(message.encode('utf-8'), key)
        return binascii.b2a_hex(passwd)

    def login(self):
        log.info('login {}/{}'.format(self.username, self.password))
        nameb64 = base64.b64encode(self.username.encode('utf-8'))
        resp = self.session.get(
            'http://login.sina.com.cn/sso/prelogin.php?'
            'entry={}&callback=sinaSSOController.preloginCallBack&'
            'su={}&rsakt=mod&client={}'.format(
            self.entry, nameb64, self.CLIENT)
        )
        pre_login_str = re.match(r'[^{]+({.+?})', resp.text).group(1)
        pre_login = json.loads(pre_login_str)
        data = {
            'entry': self.entry,
            'gateway': 1,
            'from': '',
            'savestate': 30,
            'qrcode_flag': False,
            'useticket': 0,
            'pagerefer': '',
            'vsnf': 1,
            'su': nameb64,
            'service': 'sso',
            'servertime': pre_login['servertime'],
            'nonce': pre_login['nonce'],
            'pwencode': 'rsa2',
            'rsakv' : pre_login['rsakv'],
            'sp': self.encrypt_passwd(
                self.password, pre_login['pubkey'],
                pre_login['servertime'], pre_login['nonce']),
            'sr': '2560*1440',
            'encoding': 'UTF-8',
            'cdult': 3,
            'domain': 'sina.com.cn',
            'prelt': '132',
            'returntype': 'TEXT'
        }
        resp = self.session.post(
            'http://login.sina.com.cn/sso/login.php?client={}'.format(self.CLIENT),
            data=data
        )
        j = json.loads(resp.text)
        if j['retcode'] == '0':
            self.is_logged_in = True
            self.uid = j['uid']
            self.nick = j['nick']
            log.info('login success, uid {}, nick {}'.format(self.uid, self.nick))
            return True
        else:
            log.error(str(j))


class L2Parser(object):

    PAT_QUOTE = re.compile('^2cn_([a-z0-9]{8})$')  # 买卖10档
    PAT_ORDER = re.compile('^2cn_([a-z0-9]{8})_orders$')  # 买一卖一挂单(前50)
    PAT_TRANS = re.compile('^2cn_([a-z0-9]{8})_[01]$')  # 逐笔成交
    # PAT_INFO = re.compile('^([a-z0-9]{8})_i$')  # 成交量等信息, 丢弃
    # PAT_OTHER = re.compile('^([a-z0-9]{8})$')  # 普通行情信息, 丢弃

    QUOTE_STATUS = {
        'PH': '盘后',
        'PZ': '盘中',
        'TP': '停盘',
        'WX': '午休',
        'LT': '临时停牌',
        'KJ': '开盘集合竞价',
    }
    TRANS_IOTYPE = {
        '0': '主动卖出',
        '1': '撮合成交',
        '2': '主动买入',
    }
    IOTYPE_SYMBOL = {
        '0': '▼',
        '1': '▶',
        '2': '▲',
    }

    @classmethod
    def parse(cls, data):
        result = []
        lines = data.decode('utf-8').split('\n')
        for line in lines:
            line = line.strip()
            if line:
                key, value = line.split('=')
                r, rs = None, []
                if cls.PAT_QUOTE.match(key):
                    r = cls.parse_quote(key, value)
                elif cls.PAT_ORDER.match(key):
                    r = cls.parse_order(key, value)
                elif cls.PAT_TRANS.match(key):
                    rs = cls.parse_trans(key, value)
                else:
                    log.warn('data not recognized: {}'.format(line))
                
                if r:
                    result.append(r)
                elif rs:
                    result.extend(rs)
        return result

    @classmethod
    def str2timestamp(cls, s):
        d = datetime.utcnow()
        d0 = datetime(1970, 1, 1)
        ts = (d - d0).days * 86400
        assert len(s) in [8, 12], s
        ts += int(s[:2]) * 3600
        ts += int(s[3:5]) * 60
        ts += int(s[6:8])
        if len(s) == 12:
            ts += int(s[9:12]) / 1000.
        return ts

    @classmethod
    def floatify(cls, v):
        if v:
            return float(v)
        else:
            return 0.

    @classmethod
    def intify(cls, v):
        if v:
            return int(v)
        else:
            return 0
        
    @classmethod
    def parse_quote(cls, key, value):
        """
        2cn_sh601398=工商银行,15:05:10,2017-07-12,5.060,5.060,5.150,5.050,5.080,PH,31226,219835288,1122631869.880,16486243,5.006,38715067,5.218,5523,84270769,426606888.550,4471,52469364,269632360.840,2170,5409,10,10,5.080,5.070,5.060,5.050,5.040,5.030,5.020,5.010,5.000,4.990,379972,1135225,1831588,2495658,2601000,2316200,1027400,474700,1126100,345600,5.090,5.100,5.110,5.120,5.130,5.140,5.150,5.160,5.170,5.180,2153900,1050798,395334,1192882,1202366,4253802,3160019,4234541,1806971,2719567
        """
        symbol = cls.PAT_QUOTE.search(key).group(1)
        r = value.split(',')
        assert len(r) == 66, r
        F, I = cls.floatify, cls.intify
        return {
            'type': 'quote',
            'symbol': symbol,
            'name': r[0],
            'timestamp': cls.str2timestamp(r[1]),
            'pre_close': float(r[3]),
            'open': float(r[4]),
            'high': float(r[5]),
            'low': float(r[6]),
            'close': float(r[7]),
            'price': float(r[7]),
            'status': r[8], 
            'deals': int(r[9]),
            'volume': int(r[10]),
            'money': float(r[11]),
            # 盘口委卖委买总和
            'summary': {
                'bid': {'price': F(r[13]), 'money': F(r[12]), 'deals': I(r[22])},
                'ask': {'price': F(r[15]), 'money': F(r[14]), 'deals': I(r[23])},
            },
            # 撤单信息
            'cancels': {
                'bid': {'deals': int(r[16]), 'volume': int(r[17]), 'money': float(r[18])},
                'ask': {'deals': int(r[19]), 'volume': int(r[20]), 'money': float(r[21])},
            },
            'bids': [{'price': F(r[i]), 'volume': I(r[i+10])}
                     for i in range(26, 36)],
            'asks': [{'price': F(r[i]), 'volume': I(r[i+10])}
                     for i in range(46, 56)],
        }

    @classmethod
    def parse_order(cls, key, value):
        """
        2cn_sh601398_orders=15:05:10.000,15:05:10.000,5.080,379972,43,5.090,2153900,50,43172|2900|300|700|1000|2000|1000|49300|44000|2000|1000|10000|11100|4100|5200|5000|300|600|300|1000|1400|200|1500|500|100000|6800|1800|26800|300|10600|3000|3000|1400|1000|2300|20000|6000|3500|1800|100|1000|1000|1000,,847800|100|20000|3000|8000|5000|10000|900|100|5000|5000|2000|500|19800|1000|5000|2500|3000|1000|999900|100|1000|3000|500|2500|2000|2300|5000|300|400|400|40000|100|3000|400|3000|500|1000|2000|1000|30800|30000|20000|20000|2000|10000|1000|5000|5000|2000,
        """
        symbol = cls.PAT_ORDER.search(key).group(1)
        r = value.split(',')
        I = cls.intify
        assert len(r) == 12, r
        return {
            'type': 'order',
            'symbol': symbol,
            'timestamp': cls.str2timestamp(r[1]),
            'bid1': {'price': float(r[2]), 'volume': int(r[3]), 'deals': int(r[4]),
                     'volumes': [I(x) for x in r[8].split('|')]},
            'ask1': {'price': float(r[5]), 'volume': int(r[6]), 'deals': int(r[7]),
                     'volumes': [I(x) for x in r[10].split('|')]},
        }

    @classmethod
    def parse_trans(cls, key, value):
        """
        2cn_sh601398_0=1544863|14:59:58.740|5.080|11400|57912.000|2207107|2220336|0|4
        2cn_sh601398_1=1544916|14:59:59.330|5.080|500|2540.000|2207107|2220420|0|4,1544951|14:59:59.620|5.090|5000|25450.000|2220457|1905075|2|4
        """
        symbol = cls.PAT_TRANS.search(key).group(1)
        recs = value.split(',')
        result = []
        for r in recs:
            if r:
                v = r.split('|')
                if v and v[1]:
                    result.append({
                        'type': 'trans',
                        'symbol': symbol,
                        'timestamp': cls.str2timestamp(v[1]),
                        'price': float(v[2]),
                        'volume': int(v[3]),
                        'iotype': v[7],
                    })
        return result


class L2Printer(object):

    @classmethod
    def on_data(cls, data):
        def tolot(v):
            return int(round(v / 100))

        L = tolot

        def format_volumes(vs):
            result = []
            for i, v in enumerate(vs):
                if i % 10 == 0:
                    result.append('\n')
                result.append('{:>8d}'.format(L(v)))
            return ''.join(result)


        if isinstance(data, list):
            for x in data:
                ts = datetime.utcfromtimestamp(x['timestamp']).isoformat()
                type_ = x['type'].upper()
                symbol = x['symbol']
                d = dict(x)
                del d['type']
                del d['timestamp']
                del d['symbol']
                if type_ == 'TRANS':
                    msg = '{} {} x {}'.format(
                        L2Parser.IOTYPE_SYMBOL[d['iotype']], d['price'], L(d['volume']))
                elif type_ == 'ORDER':
                    msg = ''.join([
                        '\nask1 {} x {}:'.format(d['ask1']['price'], L(d['ask1']['volume'])),
                        format_volumes(d['ask1']['volumes']),
                        '\nbid1 {} x {}:'.format(d['bid1']['price'], L(d['bid1']['volume'])),
                        format_volumes(d['bid1']['volumes']),
                    ])
                elif type_ == 'QUOTE':
                    msg = ''.join([
                        '\n{:<8s}{:<8.2f}{:<8s}{:<8.2f}{:<8s}{:<8.2f}{:<8s}{:<8.2f}'.format(
                            'open', d['open'], 'high', d['high'], 'low', d['low'], 'close', d['close']),
                        '\n{:<8s}{:<8.2f}{:<8s}{:<8d}{:<7s}{:<9d}{:<8s}{:<8.2f}'.format(
                            'pclose', d['pre_close'], 'deals', d['deals'], 'volume', L(d['volume']), 'money', d['money']),
                        '\nbidavg  price   {:<8.2f}money   {:<16.2f}deals   {:<8d}'.format(
                            d['summary']['bid']['price'], d['summary']['bid']['money'], d['summary']['bid']['deals']), 
                        '\naskavg  price   {:<8.2f}money   {:<16.2f}deals   {:<8d}'.format(
                            d['summary']['ask']['price'], d['summary']['ask']['money'], d['summary']['ask']['deals']), 
                        '\nbidcan  volume {:<11d}money   {:<14.2f}deals   {:<8d}'.format(
                            L(d['cancels']['bid']['volume']), d['cancels']['bid']['money'], d['cancels']['bid']['deals']), 
                        '\naskcan  volume {:<11d}money   {:<14.2f}deals   {:<8d}'.format(
                            L(d['cancels']['ask']['volume']), d['cancels']['ask']['money'], d['cancels']['ask']['deals']), 
            
                    ])
                    msg += ''.join([
                        '\nbid{:<3d}{:<8.2f}{:<8d} │   ask{:<3d}{:<8.2f}{:<8d}'.format(
                        i+1, d['bids'][i]['price'], L(d['bids'][i]['volume']),
                        i+1, d['asks'][i]['price'], L(d['asks'][i]['volume']))
                        for i in range(10)
                    ])
                else:
                    msg = str(d)
                print('[{}] {} {} {}'.format(ts, type_, symbol, msg))
        else:
            print(data)


class L2Client(SinaClient):
    OPCODE_TEXT = 0x1
    OPCODE_CLOSE = 0x8
    WATCH_TEMPLATE = [
        '2cn_{}', # 10档盘口
        '2cn_{}_orders', # 买卖一挂单
        '2cn_{}_0', # 逐笔(上一秒?)
        '2cn_{}_1', # 逐笔(这一秒?)
        # '{}_i', # 信息
        # '{}', # 汇总信息
    ]
    def __init__(self, username, password):
        self.market_closed = False
        super(L2Client, self).__init__(username, password)

    def watch(self, symbols, on_data=None, parse=True):
        if not on_data:
            on_data = L2Printer.on_data
        wlist = self.make_watchlist(symbols)
        while not self.market_closed:
            try:
                self.run_websocket(symbols, wlist, on_data, parse)
            except:
                log.exception('server disconnect or error, try again 0.1s later')
                time.sleep(0.1)

    def make_watchlist(self, symbols):
        channels = []
        for symbol in symbols:
            for template in self.WATCH_TEMPLATE:
                channels.append(template.format(symbol))
        return ','.join(channels)

    def get_token(self, symbols, wlist):
        ip = Helper.get_ip()
        url = 'https://current.sina.com.cn/auth/api/jsonp.php/' + \
            'var%20KKE_auth_{}=/'.format(Helper.random_string(9)) + \
            'AuthSign_Service.getSignCode?' + \
            'query=hq_pjb&ip={}&list={}&kick=1'.format(ip, wlist)
        resp = self.session.get(url)
        pat = re.compile('result:"([^"]+)",timeout:(\d+)')
        m = pat.search(resp.text)
        if m:
            token, timeout = m.groups()
            timeout = int(timeout)
            return token
        else:
            log.error('token error: {}'.format(resp.text))

    def run_websocket(self, symbols, wlist, on_data=None, parse=True):
        log.info('running websocket for symbols = {}'.format(','.join(symbols)))
        token = self.get_token(symbols, wlist)
        if not token:
            return
        url = 'wss://ff.sinajs.cn/wskt?token={}&list={}'.format(token, wlist)
        ws = websocket.WebSocket()
        ws.settimeout(10)
        ws.connect(url)
        stop_all = threading.Event()

        def update_token(interval=175):
            """ update token every 175s """
            nonlocal token
            while not stop_all.wait(interval):
                token = self.get_token(symbols, wlist)
                if ws and ws.connected:
                    ws.send('*' + token)
                    log.debug('send new token: {}'.format(token))
            
        def keep_alive(interval=60):
            """ talk to server every 60s """
            while not stop_all.wait(interval):
                if ws and ws.connected:
                    log.debug('send empty string')
                    ws.send('')

        # run background workers
        t1 = threading.Thread(target=update_token)
        t2 = threading.Thread(target=keep_alive)
        t1.daemon = t2.daemon = True
        t1.start()
        t2.start()
                
        # poll websocket data
        while not self.market_closed and ws.connected:
            r, w, e = select.select((ws.sock,), (), (), 5)
            if r:
                try:
                    op_code, data = ws.recv_data()
                except websocket.WebSocketConnectionClosedException:
                    log.error('network error, connection dropped')
                    break
                log.debug('recv {} {}'.format(op_code, data))
                if op_code == self.OPCODE_CLOSE:
                    log.info('websocket closed by server, symbols = {}'.format(
                        ','.join(symbols)))
                    break
                elif op_code == self.OPCODE_TEXT:
                    if parse:
                        data = L2Parser.parse(data)  
                    on_data(data)


        ws = None
        stop_all.set()

    def get_trans(self, symbol, concurrency=50, show_progress=True):
        sec = time.time() % 86400
        if  sec < 7 * 3600 or sec > 16 * 3600:
            log.error('can only download after 15:00')
            return

        url = 'http://stock.finance.sina.com.cn/stock/api/openapi.php/' + \
            'StockLevel2Service.getTransactionList?symbol={}'.format(symbol) + \
            '&callback=jsonp&pageNum=52&page={}'
        header = 'ticktime,id,index,symbol,intticktime,trade,' + \
            'volume,amount,buynum,sellnum,iotype,tradechannel'
        rows = []
        headers = header.split(',')

        def get_page(page, bar=None):
            try:
                resp = self.session.get(url.format(page), timeout=5)
                idx = resp.text.find('jsonp')
                r = json.loads(resp.text[idx+6:-2])['result']
                if r['status']['code'] == 0:
                    ld = r['data']['data']
                    if ld:
                        for d in ld:
                            rec = []
                            for name in headers:
                                rec.append(d[name])
                            rows.append(','.join(rec))
                        if show_progress and bar:
                            bar.update(len(ld))
                        return int(r['data']['count']), len(ld)
                    else:
                        return 0, 52
                else:
                    return get_page(page, bar)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                return get_page(page, bar)
            except Exception as e:
                log.exception(e)

        count, size = get_page(1)
        if show_progress:
            bar = tqdm.tqdm(total=count, desc=symbol, leave=False)
            bar.update(size)
        e = ThreadPoolExecutor(concurrency)
        fs = []
        for p in range(2, (count - 1) // size + 2):
            fs.append(e.submit(get_page, p, bar))
        wait(fs)
        if show_progress:
            bar.close()
        if rows:
            return '\n'.join([header] + sorted(rows) + ['\n'])
        else:
            return ''

