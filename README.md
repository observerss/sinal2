## SinaL2, 又一个新浪Level2行情端

### 相同

- 支持新浪Level2普及版和标准版等

### 不同

- 轻量级, 专注于行情获取
- 去耦合, 模块更容易复用
- 不强制异步, 需要异步可以在外部用gevent或者自己patch
- 命令行调试
- 自带高性能下载全部数据的实现

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

#### 配置新浪用户名密码到环境变量

```bash
export SINA_USERNAME=UUUUUUUUU
export SINA_PASSWORD=PPPPPPPPP
```

#### 查看单个票

```bash
sinal2 watch -s sh601398
```

#### 输出原始信息到文件

```bash
sinal2 watch -s sh601398 --raw -o sh601398.l2
```

#### 盘中同步全部沪深股票L2信息

```bash
sinal2 watch --raw -o all.l2
```

注意, 实盘请确保20M以上的高速带宽

#### 使用多核

一般情况下, 单核gevent足够在开盘时间拉取全部沪深L2数据, 如果电脑实在太慢(比如共享主机或者云服务器), 会发生单CPU 100%还是来不及接收和处理的情况, 长时间后可能会出现网络错误(例如socket的buffer溢出或无响应超时)并丢包, 这时需要开启多核调度, `--core`指定核心数即可

```bash
sinal2 watch --raw -o all.l2 -c 2
```

#### 收盘后下载逐笔数据

```bash
sinal2 trans -s sh601398 -o sh601398.trans
```

#### 全部逐笔

```bash
sinal2 trans -o all.trans
```

下载全部的逐笔数据大约需要2M带宽
