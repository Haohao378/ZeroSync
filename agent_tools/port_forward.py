import sys
import json
import os
import uuid
import time
import urllib.request
import urllib.error
import socket
AUTH_FILE = os.path.join(os.path.dirname(__file__), '.agent_auth.json')
try:
    with open(AUTH_FILE, 'r', encoding='utf-8') as f:
        auth_data = json.load(f)
        BASE_URL = auth_data.get('endpoint')
        TOKEN = auth_data.get('token')
except Exception:
    print('【系统拦截】当前服务器未连接。请通知用户在客户端重新建立连接，或者如果只需要本地操作，请直接忽略此 Skill。')
    sys.exit(1)
ENDPOINT = f'{BASE_URL}/api/agent/execute'

def get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def send_to_backend(command: str, timeout: int=10):
    payload = json.dumps({'command': command, 'timeout': timeout}).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', f'Bearer {TOKEN}')
    with urllib.request.urlopen(req) as response:
        res_data = json.loads(response.read().decode('utf-8'))
        return res_data.get('stdout', '') + res_data.get('stderr', '')

def main():
    if len(sys.argv) < 2:
        print('Usage: python port_forward.py <remote_port> ["command_to_start_service"]')
        sys.exit(1)
    remote_port = sys.argv[1]
    start_cmd = sys.argv[2] if len(sys.argv) > 2 else None
    local_port = get_free_local_port()
    if start_cmd:
        log_file = f'/tmp/svc_{uuid.uuid4().hex[:6]}.log'
        env_vars = 'PYTHONUNBUFFERED=1 NO_PROXY=localhost,127.0.0.1,::1 no_proxy=localhost,127.0.0.1,::1'
        wrapper_cmd = f"{env_vars} nohup {start_cmd} > {log_file} 2>&1 & PID=$!; sleep 2.5; if kill -0 $PID 2>/dev/null; then   echo 'SUCCESS_ALIVE'; else   echo 'CRASHED';   tail -n 15 {log_file}; fi"
        try:
            result = send_to_backend(wrapper_cmd, timeout=10)
            if 'CRASHED' in result:
                print(f'【服务启动致命错误】后台服务在启动 2 秒内异常崩溃退出！')
                print(f'极大概率是因为【端口已被占用】或【代码依赖报错】。')
                print(f"====== 崩溃前最后输出的错误日志 ======\n{result.replace('CRASHED', '').strip()}\n======================================")
                print(f'\n[Agent 指令] 请阅读上述日志解决错误。如果端口被占用，请更换端口或使用 kill 结束占用进程后再试。远端完整日志位于: {log_file}')
                sys.exit(1)
            print(f'[*] 进程健康度检查通过：服务已在远端安全运行 (日志位于: {log_file})')
        except Exception as e:
            print(f'【服务启动请求异常】 {e}')
            sys.exit(1)
    magic_command = f'__INTERNAL_PORT_FORWARD__ {remote_port} {local_port}'
    try:
        result = send_to_backend(magic_command)
        if result.startswith('SUCCESS|'):
            local_url = result.split('|')[1].strip()
            print('======== [Web Service Ready] ========')
            print(f'Target Port : {remote_port} (Remote/Docker)')
            print(f'Local URL   : {local_url}')
            print('=====================================')
            print(f'[Agent 指令] 映射成功！请告知用户：无需关心服务器防火墙或 Docker 配置，请直接在本地浏览器点击 {local_url} 即可访问。')
        else:
            print('【映射失败】未能成功建立内网隧道：\n', result)
    except Exception as e:
        print('【系统拦截】网关请求失败，连接可能已断开。请通知用户重新建立连接，或忽略此 Skill。')
if __name__ == '__main__':
    main()