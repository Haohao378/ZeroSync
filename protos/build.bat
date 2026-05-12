@echo off
chcp 65001 >nul
:: 切换到当前批处理文件所在目录
cd /d "%~dp0"

echo ===================================================
echo   [ZeroSync] Protobuf 协议自动编译工具
echo ===================================================

:: 检查环境中是否安装了 grpcio-tools
python -c "import grpc_tools" 2>nul
if errorlevel 1 (
    echo.
    echo [错误] 您的 Python 环境缺少编译依赖！
    echo 请先在终端执行: pip install grpcio-tools
    echo.
    pause
    exit /b 1
)

echo [1/2] 正在编译 sync.proto ...
:: 将生成的文件输出到上一级目录 (即项目根目录 ..)
python -m grpc_tools.protoc -I. --python_out=.. --grpc_python_out=.. sync.proto

if errorlevel 1 (
    echo.
    echo [错误] 编译失败，请检查上面的报错信息。
    pause
    exit /b 1
)

echo [2/2] 编译成功！
echo 桥接文件已生成: sync_pb2.py 和 sync_pb2_grpc.py
echo 生成路径: 项目根目录
echo.
pause