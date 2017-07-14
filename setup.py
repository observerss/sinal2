#!/usr/bin/env python
import sys
from setuptools import setup
from setuptools import find_packages
from sinal2 import __version__


setup(name='python-sinal2',
      version=__version__,
      description='Sina Level2 Data Fetcher',
      author='Jingchao Hu',
      author_email='jingchaohu@gmail.com',
      url='http://github.com/observerss/sinal2',
      packages=find_packages(),
      install_requires=['tqdm', 'requests', 'websocket-client', 'gevent'],
      python_requires='>=3.5',
      entry_points={
          'console_scripts': [
              'sinal2 = sinal2.cli:cli',
          ],
      },
      classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
      ]
     )
