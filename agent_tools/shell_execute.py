import os
import sys
import json
import urllib.request
import urllib.error
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

def main():
    if len(sys.argv) < 2:
        print('Usage: python shell_execute.py <command>')
        sys.exit(1)
    command = sys.argv[1]
    payload = json.dumps({'command': command, 'timeout': 7 * 86400}).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', f'Bearer {TOKEN}')
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if res_data.get('exit_code') != 0:
                out = res_data.get('stdout') or ''
                err = res_data.get('stderr') or ''
                combined = f'{out}\n{err}'.strip() if err else out.strip()
                print(f"[Exit Code: {res_data.get('exit_code')}]\n{combined}")
            else:
                print(res_data.get('stdout') or '')
    except urllib.error.HTTPError as e:
        print(f"IPC API Error: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print('【系统拦截】网关请求失败，连接可能已断开。请通知用户重新建立连接，或忽略此 Skill。')
if __name__ == '__main__':
    main()