#!/bin/bash

# 定义要杀死的进程名
PROCESS_NAME="http_server3.py"

echo "尝试杀死进程: ${PROCESS_NAME}"

# 使用 ps aux 查找所有进程
# 通过 grep 过滤出包含 PROCESS_NAME 的行
# 使用 grep -v grep 排除 grep 命令本身的进程
# 使用 awk '{print $2}' 提取进程ID (PID，通常是第二列)
PIDS=$(ps aux | grep "${PROCESS_NAME}" | grep -v grep | awk '{print $2}')

# 检查是否找到了PID
if [ -z "$PIDS" ]; then
  echo "未找到进程 '${PROCESS_NAME}'。"
else
  echo "找到进程ID: ${PIDS}"
  echo "正在杀死进程..."
  # 逐一杀死找到的PID
  for PID in $PIDS; do
    # kill 命令发送 SIGTERM 信号 (SIGHUP或SIGKILL)
    # -9 是 SIGKILL，强制杀死，不给进程清理机会
    # 推荐先尝试不带-9的kill，如果进程不退出再使用-9
    # kill "$PID" # 尝试温和杀死
    kill -9 "$PID" # 强制杀死
    if [ $? -eq 0 ]; then
      echo "成功杀死进程 PID: $PID"
    else
      echo "无法杀死进程 PID: $PID"
    fi
  done
fi

echo "脚本执行完毕。"
