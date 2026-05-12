import os
import sys
import json
import urllib.request
AUTH_FILE = os.path.join(os.path.dirname(__file__), '.agent_auth.json')
try:
    with open(AUTH_FILE, 'r', encoding='utf-8') as f:
        auth_data = json.load(f)
        BASE_URL = auth_data.get('endpoint')
        TOKEN = auth_data.get('token')
except Exception:
    print('【系统拦截】当前服务器未连接。请通知用户在客户端重新建立连接，或者如果只需要本地操作，请直接忽略此 Skill。')
    sys.exit(1)
ENDPOINT = f'{BASE_URL}/api/agent/pull'

def main():
    if len(sys.argv) < 2:
        print('Usage: python safe_pull.py <remote_absolute_path> [optional_other_paths...]')
        sys.exit(1)
    workspace = auth_data.get('workspace', '/')
    for input_path in sys.argv[1:]:
        if not input_path.startswith('/'):
            import os
            remote_path = os.path.join(workspace, input_path).replace('\\', '/')
        else:
            remote_path = input_path
        print(f'Requesting safe pull for: {remote_path} ...')
        payload = json.dumps({'remote_path': remote_path, 'dest_dir': None}).encode('utf-8')
        req = urllib.request.Request(ENDPOINT, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', f'Bearer {TOKEN}')
        try:
            with urllib.request.urlopen(req, timeout=3600) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                if res_data.get('status') == 'success':
                    print(f"Pull Success! File saved to local path: {res_data.get('local_path')}")
                else:
                    print(f"Pull Failed: {res_data.get('error_msg')}")
        except Exception as e:
            print('【系统拦截】网关请求失败，连接可能已断开。请通知用户重新建立连接，或忽略此 Skill。')
if __name__ == '__main__':
    main()