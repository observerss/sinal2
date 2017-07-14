## 又一个新浪Level2行情端

### 相同

- 支持新浪Level2普及版和标准版等

### 不同

- 轻量级, 专注于行情获取
- 去耦合, 模块更容易复用
- 不强制异步, 需要异步可以在外部用gevent或者自己patch
- 提供简单的命令行供调试

### 安装

```python
pip install python-sinal2
```

### 使用

```python
from sinal2 import L2Client, L2Parser
def on_data(data):
    print(data)

c = L2Client(USERNAME, PASSWORD)
if c.login():
    csv = c.get_trans('sh601398')

    # 这条命令会一直监听到15:01收盘
    c.watch(['sh601398'], on_data=on_data, parse=True)
```

### 命令行

配置新浪用户名密码到环境变量

```bash
export SINA_USERNAME=UUUUUUUUU
export SINA_PASSWORD=PPPPPPPPP
```

然后查看单个票

```bash
sinal2 watch -s sh601398
```

也可以把原始数据输出到文件

```bash
sinal2 watch -s sh601398 --raw -o sh601398.l2
```

收盘后下载逐笔数据

```bash
sinal2 trans -s sh601398 -o sh601398.trans
```

如果不加股票代码则默认是全部沪深A股+沪深B股, 实盘请确保20M以上的高速带宽, 逐笔下载也知道需要2M带宽

