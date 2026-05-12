import asyncio
import os
import sys
import signal
import subprocess
from typing import Optional
from config import load_config, SyncConfig
from utils.logger import setup_logger, shutdown_logger
from utils.file_lock import check_file_lock
from storage.state_manager import StateManager
from delta.calculator import DeltaCalculator
from core.heuristic import HeuristicEngine
from network.grpc_client import AsyncNetworkClient
from core.engine import SyncEngine
from sshtunnel import SSHTunnelForwarder
if sys.platform == 'win32':
    from monitor.win_monitor import WindowsMonitor as OSMonitor
elif sys.platform == 'darwin':
    from monitor.mac_fsevents import MacFSEventsMonitor as OSMonitor
else:
    raise OSError('Client must run on Windows or Mac.')
logger = setup_logger('ZeroSync')

class SSHTunnelManager:

    def __init__(self, conf: SyncConfig, docker_name=None):
        self.conf = conf
        self.server = None
        self.docker_name = docker_name

    def start(self):
        logger.info(f'Establishing SSH Tunnel to {self.conf.ssh.hostname}...')
        try:
            remote_bind_ip = '127.0.0.1'
            if self.docker_name:
                import paramiko
                logger.info(f'Docker mode detected. Resolving internal IP for container: {self.docker_name}')
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if self.conf.ssh.key_path:
                    ssh.connect(self.conf.ssh.hostname, port=self.conf.ssh.port, username=self.conf.ssh.username, key_filename=self.conf.ssh.key_path, passphrase=self.conf.ssh.password)
                else:
                    ssh.connect(self.conf.ssh.hostname, port=self.conf.ssh.port, username=self.conf.ssh.username, password=self.conf.ssh.password)
                stdin, stdout, stderr = ssh.exec_command(f"docker inspect -f '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {self.docker_name}")
                ip = stdout.read().decode().strip()
                ssh.close()
                if ip:
                    remote_bind_ip = ip
                    logger.info(f'Successfully resolved Docker internal IP: {ip}')
                else:
                    logger.warning(f'Could not resolve IP for container {self.docker_name}. Is it running?')
            tunnel_kwargs = {'ssh_address_or_host': (self.conf.ssh.hostname, self.conf.ssh.port), 'ssh_username': self.conf.ssh.username, 'host_pkey_directories': [], 'local_bind_address': ('127.0.0.1', self.conf.grpc_port), 'remote_bind_address': (remote_bind_ip, self.conf.grpc_port)}
            if self.conf.ssh.key_path:
                tunnel_kwargs['ssh_pkey'] = self.conf.ssh.key_path
                if self.conf.ssh.password:
                    tunnel_kwargs['ssh_private_key_password'] = self.conf.ssh.password
            elif self.conf.ssh.password:
                tunnel_kwargs['ssh_password'] = self.conf.ssh.password
            self.server = SSHTunnelForwarder(**tunnel_kwargs)
            self.server.start()
            logger.info(f'SSH Tunnel established. Local {self.conf.grpc_port} -> Remote {remote_bind_ip}:{self.conf.grpc_port}')
        except Exception as e:
            err_msg = str(e)
            if 'WinError 10060' in err_msg or '10060' in err_msg:
                err_msg = '[WinError 10060] A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected host has failed to respond.'
            logger.critical(f'Failed to establish SSH Tunnel: {err_msg}')
            raise RuntimeError(f'Failed to establish SSH Tunnel: {err_msg}')

    def stop(self):
        if self.server:
            self.server.stop()
            logger.info('SSH Tunnel closed.')

async def main():
    config = load_config()
    tunnel = SSHTunnelManager(config)
    engine = None

    def handle_signal():
        logger.info('Interrupt received, initiating graceful shutdown...')
        if engine:
            engine.stop()
        tunnel.stop()
        shutdown_logger()
        sys.exit(0)
    loop = asyncio.get_running_loop()
    if sys.platform != 'win32':
        loop.add_signal_handler(signal.SIGINT, handle_signal)
        loop.add_signal_handler(signal.SIGTERM, handle_signal)
    try:
        tunnel.start()
        await asyncio.sleep(2.0)
        state_mgr = StateManager(config.db_path)
        last_event_id = state_mgr.get_last_event_id()
        monitor = OSMonitor(watch_dir=config.watch_dir, since_id=last_event_id)
        heuristic = HeuristicEngine(file_lock_check_func=check_file_lock)
        delta_calc = DeltaCalculator(state_mgr.get_db())
        network = AsyncNetworkClient(target_address=f'127.0.0.1:{config.grpc_port}', use_tls=False)
        original_send_event = network.send_event

        async def clean_send_event(event):
            event.path = os.path.relpath(event.path, config.watch_dir).replace('\\', '/')
            if event.target_path:
                event.target_path = os.path.relpath(event.target_path, config.watch_dir).replace('\\', '/')
            await original_send_event(event)
        network.send_event = clean_send_event
        original_send_patches = network.send_patches

        async def clean_send_patches(path, patches):
            clean_path = os.path.relpath(path, config.watch_dir).replace('\\', '/')
            await original_send_patches(clean_path, patches)
        network.send_patches = clean_send_patches
        engine = SyncEngine(monitor=monitor, heuristic=heuristic, delta_calc=delta_calc, network=network, state_mgr=state_mgr, max_workers=4)
        await engine.start()
    except KeyboardInterrupt:
        handle_signal()
    except Exception as e:
        logger.critical(f'System crashed: {e}')
        handle_signal()
if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())