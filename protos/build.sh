#!/bin/bash

# 切换到脚本所在目录
cd "$(dirname "$0")"

echo "==================================================="
echo "  [ZeroSync] Protobuf 协议自动编译工具 (macOS/Linux)"
echo "==================================================="

# 1. 检查 Python 环境
PY_BIN=$(which python3 || which python)

if [ -z "$PY_BIN" ]; then
    echo "[错误] 未找到 Python 环境，请先安装 Python 3。"
    exit 1
fi

# 2. 检查 grpcio-tools 是否安装
$PY_BIN -c "import grpc_tools" 2>/dev/null
if [ $? -ne 0 ]; then
    echo ""
    echo "[错误] 您的 Python 环境缺少编译依赖！"
    echo "请先在终端执行: pip install grpcio-tools"
    echo ""
    exit 1
fi

echo "[1/2] 正在编译 sync.proto ..."

# 3. 执行编译 (输出到上一级根目录)
$PY_BIN -m grpc_tools.protoc -I. --python_out=.. --grpc_python_out=.. sync.proto

if [ $? -eq 0 ]; then
    echo "[2/2] 编译成功！"
    echo "桥接文件已生成至项目根目录: sync_pb2.py 和 sync_pb2_grpc.py"
    echo ""
else
    echo "[错误] 编译失败，请检查上面的报错信息。"
    exit 1
fi