#!/bin/bash

# 后台运行 HTTP 服务器
nohup python3 http_server3.py > http_server3.log 2>&1 &

# 数据保存在 data_store.json 中

# 查看日志
tail -f http_server3.log



