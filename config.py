import json
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class SSHConfig:
    hostname: str
    port: int
    username: str
    password: Optional[str] = None
    key_path: Optional[str] = None

@dataclass
class SyncConfig:
    watch_dir: str
    remote_dir: str
    ssh: SSHConfig
    grpc_port: int = 50051
    db_path: str = '.zerosync.db'
    log_dir: str = 'logs'

def load_config(config_path: str='config.json') -> SyncConfig:
    if not os.path.exists(config_path):
        default_conf = {'watch_dir': 'D:\\my_project', 'remote_dir': '/home/lab23/workspace', 'grpc_port': 50051, 'ssh': {'hostname': '219.216.65.163', 'port': 22, 'username': 'lab23', 'password': 'lab@gpu23', 'key_path': None}}
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_conf, f, indent=4)
        raise FileNotFoundError(f'Config not found. Generated template at {config_path}. Please edit it.')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        raise RuntimeError(f"Config file '{config_path}' is empty or malformed. Please fix or delete it to regenerate.")
    ssh_data = data.get('ssh', {})
    ssh_conf = SSHConfig(hostname=ssh_data['hostname'], port=ssh_data.get('port', 22), username=ssh_data['username'], password=ssh_data.get('password'), key_path=ssh_data.get('key_path'))
    return SyncConfig(watch_dir=os.path.abspath(data['watch_dir']), remote_dir=data['remote_dir'], ssh=ssh_conf, grpc_port=data.get('grpc_port', 50051), db_path=data.get('db_path', '.zerosync.db'), log_dir=data.get('log_dir', 'logs'))