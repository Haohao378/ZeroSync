import sys
import json
import os
import urllib.request
import urllib.error
import base64
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
    remote_py_code = '\nimport os, platform, subprocess, json, shutil\n\ndef get_cmd_out(cmd):\n    try:\n        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, text=True, timeout=5).strip()\n    except Exception:\n        return None\n\ninfo = {}\ninfo["os"] = f"{platform.system()} {platform.release()} ({platform.machine()})"\n\n# 1. CPU 探测 (兼容 Linux/Mac/Win)\ntry:\n    if platform.system() == "Linux":\n        model = get_cmd_out("lscpu | grep \'Model name\' | cut -d\':\' -f2")\n        model = model.strip() if model else "Unknown"\n        info["cpu"] = f"{model} ({os.cpu_count()} Cores)"\n    else:\n        info["cpu"] = f"CPU Cores: {os.cpu_count()}"\nexcept Exception:\n    info["cpu"] = "Unknown"\n\n# 2. 内存探测 (放弃 psutil，直读 Linux 系统内核文件)\ntry:\n    if platform.system() == "Linux":\n        with open("/proc/meminfo", "r") as f:\n            lines = f.readlines()\n        mem_tot = [l.split()[1] for l in lines if "MemTotal" in l]\n        mem_avail = [l.split()[1] for l in lines if "MemAvailable" in l]\n        if mem_tot and mem_avail:\n            info["memory"] = f"Total: {int(mem_tot[0])//1024}MB | Free: {int(mem_avail[0])//1024}MB"\n        else:\n            info["memory"] = "N/A"\n    else:\n        info["memory"] = "N/A (Non-Linux without psutil)"\nexcept Exception:\n    info["memory"] = "Unknown"\n\n# 3. 磁盘探测 (聚焦当前工作目录，即大模型代码所在的同步目录)\ntry:\n    st = os.statvfs(\'.\')\n    total_gb = (st.f_blocks * st.f_frsize) / (1024**3)\n    free_gb = (st.f_bavail * st.f_frsize) / (1024**3)\n    info["disk_cwd"] = f"Total: {total_gb:.1f}GB | Free: {free_gb:.1f}GB"\nexcept Exception:\n    info["disk_cwd"] = "Unknown"\n\n# 4. GPU 探测 (安全调用 nvidia-smi，极度精简输出)\ntry:\n    smi = shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe")\n    # Windows 的兜底路径\n    if not smi and platform.system() == "Windows" and os.path.exists(r"C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"):\n        smi = r"C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"\n        \n    if smi:\n        gpu_out = get_cmd_out(f\'"{smi}" --query-gpu=name,memory.free,memory.total,utilization.gpu --format=csv,noheader\')\n        if gpu_out:\n            gpus = []\n            for i, line in enumerate(gpu_out.strip().split(\'\\n\')):\n                parts = [p.strip() for p in line.split(\',\')]\n                if len(parts) >= 4:\n                    gpus.append(f"GPU {i}: {parts[0]} | VRAM Free: {parts[1]}/{parts[2]} | Util: {parts[3]}")\n            info["gpu"] = " || ".join(gpus) if gpus else "N/A (No output)"\n        else:\n            info["gpu"] = "N/A (nvidia-smi failed or timeout)"\n    else:\n        info["gpu"] = "N/A (No GPU/driver detected)"\nexcept Exception as e:\n    info["gpu"] = f"Probe Error: {type(e).__name__}"\n    \n# 5. 用户身份与 Docker 内部识别\ntry:\n    import getpass\n    try:\n        user = getpass.getuser()\n    except Exception:\n        # 如果连 getpass 都失败，直接拿底层 UID\n        user = f"UID:{os.getuid()}" \n    \n    in_docker = "Yes" if os.path.exists("/.dockerenv") else "No"\n    info["context"] = f"User: {user} | InDocker: {in_docker}"\nexcept Exception:\n    info["context"] = "Unknown"\n\n# 6. 外网连通性与代理探测 (纯 Python urllib，完美继承终端环境变量，无需 curl)\ntry:\n    import urllib.request\n    proxy_keys = ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY"]\n    active_proxies = [k for k in proxy_keys if os.environ.get(k)]\n    proxy_status = " (Proxy Configured)" if active_proxies else ""\n    \n    # urllib 会自动拦截并使用终端中的 http_proxy / all_proxy\n    # 设置 2 秒超时，请求百度如果成功，说明真有网\n    req = urllib.request.Request("http://www.baidu.com", method="HEAD")\n    urllib.request.urlopen(req, timeout=2)\n    info["network"] = f"Online{proxy_status}"\nexcept Exception as e:\n    info["network"] = f"Offline / Timeout{proxy_status}"\n\n# 7. 核心环境工具探测\ntools = []\ntools.append(f"Python {platform.python_version()}")\nif shutil.which("conda"): tools.append("Conda: Yes")\nif shutil.which("docker"): tools.append("Docker: Yes")\nnvcc_ver = get_cmd_out("nvcc --version | grep release | awk \'{print $NF}\'")\nif nvcc_ver: tools.append(f"CUDA(nvcc): {nvcc_ver}")\n\ninfo["environment"] = " | ".join(tools)\n\n# 8. 工作区顶层目录结构 (满足 Agent 的好奇心，防范其手动执行 ls -R)\ntry:\n    items = os.listdir(\'.\')\n    # 过滤掉以点开头的隐藏文件(如 .git, .idea)，并且只截取前 30 个文件夹和 50 个文件防 Token 爆炸\n    dirs = sorted([d for d in items if os.path.isdir(d) and not d.startswith(\'.\')])[:60]\n    files = sorted([f for f in items if os.path.isfile(f) and not f.startswith(\'.\')])[:100]\n    \n    ws_info = []\n    if dirs: ws_info.append(f"[Dirs] {\', \'.join(dirs)}")\n    if files: ws_info.append(f"[Files] {\', \'.join(files)}")\n    \n    # 顺便统计一下有多少个隐藏文件，让它心里有数\n    hidden_count = len([x for x in items if x.startswith(\'.\')])\n    if hidden_count > 0: ws_info.append(f"({hidden_count} hidden)")\n    \n    # 如果文件超标，给个截断提示\n    remaining = len(items) - len(dirs) - len(files) - hidden_count\n    if remaining > 0: ws_info.append(f"(...and {remaining} more)")\n    \n    info["workspace"] = " | ".join(ws_info) if ws_info else "Empty Directory"\nexcept Exception:\n    info["workspace"] = "Unknown / Permission Denied"\n\n# 强制输出干净的 JSON\nprint(json.dumps(info))\n'
    b64_code = base64.b64encode(remote_py_code.encode('utf-8')).decode('utf-8')
    py_payload = f'''"import base64; exec(base64.b64decode('{b64_code}').decode('utf-8'))"'''
    linux_command = f'python3 -c {py_payload} || python -c {py_payload}'
    payload = json.dumps({'command': linux_command, 'timeout': 30}).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', f'Bearer {TOKEN}')
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            result = res_data.get('stdout') or res_data.get('stderr')
            if not result or not result.strip():
                print('【探针警告】未从远端获取到任何信息。')
                return
            try:
                data = json.loads(result.strip())
                print('======== [Remote Host Telemetry] ========')
                print(f"Context   : {data.get('context', 'N/A')}")
                print(f"Network   : {data.get('network', 'N/A')}")
                print(f"OS        : {data.get('os', 'N/A')}")
                print(f"CPU       : {data.get('cpu', 'N/A')}")
                print(f"Memory    : {data.get('memory', 'N/A')}")
                print(f"Disk(CWD) : {data.get('disk_cwd', 'N/A')}")
                print(f"GPU       : {data.get('gpu', 'N/A')}")
                print(f"Env       : {data.get('environment', 'N/A')}")
                print(f"Workspace : {data.get('workspace', 'N/A')}")
                print('=========================================')
            except json.JSONDecodeError:
                print('【探针警告】无法解析远端探针数据，原始输出如下：')
                print(result.strip())
    except Exception as e:
        print('【系统拦截】网关请求失败，连接可能已断开。请通知用户重新建立连接，或忽略此 Skill。')
if __name__ == '__main__':
    main()