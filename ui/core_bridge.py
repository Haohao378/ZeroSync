import threading
import asyncio
import os
import time
import logging
from typing import Callable, Optional
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from config import SyncConfig, SSHConfig
    from main import SSHTunnelManager
    from storage.state_manager import StateManager
    from delta.calculator import DeltaCalculator
    from core.heuristic import HeuristicEngine
    from network.grpc_client import AsyncNetworkClient
    from core.engine import SyncEngine
    from core.types import FSEvent, EventType
    from utils.file_lock import check_file_lock
    if sys.platform == 'win32':
        from monitor.win_monitor import WindowsMonitor as OSMonitor
    else:
        from monitor.mac_fsevents import MacFSEventsMonitor as OSMonitor
except ImportError as e:
    logging.error(f'Failed to import core modules: {e}')

class CoreBridge:

    def __init__(self, log_callback: Callable[[str, str], None], status_callback: Callable[[str], None], ready_callback: Callable[[], None]=None, stop_callback: Callable[[], None]=None, reconnect_callback: Callable[[], None]=None):
        self.log_cb = log_callback
        self.status_cb = status_callback
        self.ready_cb = ready_callback
        self.stop_cb = stop_callback
        self.reconnect_cb = reconnect_callback
        self._sync_thread: Optional[threading.Thread] = None
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self.engine: Optional[SyncEngine] = None
        self.tunnel: Optional[SSHTunnelManager] = None
        self.is_running = False
        self.is_paused = False
        self.active_config_dict = {}

    def start_engine(self, config_dict: dict):
        if self.is_running:
            return
        self.active_config_dict = config_dict
        self.is_running = True
        self.is_paused = False
        self.log_cb('Bridge: Initializing backend sync thread...', 'INFO')
        self._sync_thread = threading.Thread(target=self._backend_thread_worker, daemon=True)
        self._sync_thread.start()

    def stop_engine(self):
        if not self.is_running:
            return
        self.log_cb('Bridge: Stopping sync engine gracefully...', 'INFO')
        self.is_running = False
        self.status_cb('stopped')
        if self.engine and self._async_loop:
            if self._async_loop.is_running():
                self.log_cb('Scheduling engine.stop() in event loop...', 'DEBUG')
                self._async_loop.call_soon_threadsafe(self.engine.stop)
            else:
                self.log_cb('Event loop is not running!', 'ERROR')
        else:
            self.log_cb('Engine or async loop is None', 'ERROR')

    def pause_sync_for_pull(self):
        self.is_paused = True
        self.status_cb('paused')
        self.log_cb('Engine PAUSED. Safe mode is enabled, you can manually pull remote files to local.', 'WARN')

    def resume_sync(self):
        self.is_paused = False
        self.status_cb('running')
        self.log_cb('Engine RESUMED. Real-time synchronization has been restored.', 'INFO')

    def trigger_full_init(self):
        if not self.is_running or not self.engine:
            self.log_cb('Engine is not running, cannot perform full initialization.', 'ERROR')
            return
        self.log_cb('Starting full directory scan and upload synchronization...', 'INFO')
        threading.Thread(target=self._full_init_worker, daemon=True).start()

    def _full_init_worker(self):
        watch_dir = self.active_config_dict.get('local_dir')
        count = 0
        mod_events = []
        for root, dirs, files in os.walk(watch_dir):
            root_norm = root.replace('\\', '/')
            for d in dirs:
                dir_path = os.path.join(root_norm, d).replace('\\', '/')
                event = FSEvent(event_id=f'init_d_{time.time()}_{count}', event_type=EventType.CREATED, path=dir_path, timestamp=time.time(), meta=self.engine.monitor._get_file_meta(dir_path))
                asyncio.run_coroutine_threadsafe(self.engine._on_stable_event(event), self._async_loop)
                count += 1
            for name in files:
                full_path = os.path.join(root_norm, name).replace('\\', '/')
                meta = self.engine.monitor._get_file_meta(full_path)
                create_event = FSEvent(event_id=f'init_fc_{time.time()}_{count}', event_type=EventType.CREATED, path=full_path, timestamp=time.time(), meta=meta)
                asyncio.run_coroutine_threadsafe(self.engine._on_stable_event(create_event), self._async_loop)
                count += 1
                if meta and meta.size > 0:
                    mod_event = FSEvent(event_id=f'init_fm_{time.time()}_{count}', event_type=EventType.MODIFIED, path=full_path, timestamp=time.time(), meta=meta)
                    mod_events.append(mod_event)
        self.log_cb(f'Structure synced. Preparing to upload {len(mod_events)} files concurrently...', 'INFO')
        time.sleep(2.0)
        for mod_event in mod_events:
            asyncio.run_coroutine_threadsafe(self.engine._on_stable_event(mod_event), self._async_loop)
        self.log_cb(f'Full scan completed, {count} items have been pushed to the synchronization queue! You can continue normal operation.', 'INFO')

    def _backend_thread_worker(self):
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        self._async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._async_loop)
        try:
            self._async_loop.run_until_complete(self._async_engine_runner())
        except Exception as e:
            self.log_cb(f'Backend Crash: {e}', 'ERROR')
            self.status_cb('error')
            self.is_running = False
        finally:
            self.is_running = False
            if self.stop_cb:
                self.stop_cb()
            if self.tunnel:
                try:
                    self.tunnel.stop()
                except Exception as e:
                    self.log_cb(f'Tunnel stop error: {e}', 'WARN')

    async def _async_engine_runner(self):
        ssh_data = self.active_config_dict.get('ssh', {})
        ssh_conf = SSHConfig(hostname=ssh_data.get('hostname'), port=ssh_data.get('port', 22), username=ssh_data.get('username'), password=ssh_data.get('password'), key_path=ssh_data.get('key_path'))
        config = SyncConfig(watch_dir=self.active_config_dict.get('local_dir'), remote_dir=self.active_config_dict.get('remote_dir'), ssh=ssh_conf, grpc_port=self.active_config_dict.get('grpc_port', 50051))
        docker_name = self.active_config_dict.get('docker_name', '')
        self.tunnel = SSHTunnelManager(config, docker_name=docker_name)
        self.tunnel.start()
        await asyncio.sleep(1.5)
        if self.tunnel and getattr(self.tunnel, 'server', None):
            if not self.tunnel.server.is_active:
                raise RuntimeError(f'SSH 隧道打通失败！本地端口 {config.grpc_port} 极可能已被残留的僵尸进程占用。')

        async def connection_watchdog():
            while self.is_running:
                await asyncio.sleep(5.0)
                if not self.is_running:
                    break
                if self.tunnel and getattr(self.tunnel, 'server', None):
                    if not self.tunnel.server.is_active:
                        self.status_cb('error')
                        self.log_cb('Physical network disconnected (SSH tunnel dropped), attempting to reconnect...', 'WARN')
                        retry_count = 0
                        while self.is_running and (not self.tunnel.server.is_active):
                            try:
                                retry_count += 1
                                self.tunnel.stop()
                                self.tunnel.start()
                                if self.tunnel.server.is_active:
                                    self.status_cb('running')
                                    self.log_cb('Network restored, SSH tunnel reconnected successfully! Unsent data will be automatically retransmitted.', 'SUCCESS')
                                    if self.reconnect_cb:
                                        self._async_loop.call_soon_threadsafe(self.reconnect_cb)
                                    break
                            except Exception as e:
                                self.log_cb(f'Reconnection attempt {retry_count} failed, waiting to retry... ({str(e)})', 'WARN')
                            await asyncio.sleep(5.0)
        watchdog_task = asyncio.create_task(connection_watchdog())
        state_mgr = StateManager(config.db_path)
        monitor = OSMonitor(watch_dir=config.watch_dir, since_id=state_mgr.get_last_event_id())
        heuristic = HeuristicEngine(file_lock_check_func=check_file_lock)
        delta_calc = DeltaCalculator(state_mgr.get_db())
        network = AsyncNetworkClient(target_address=f'127.0.0.1:{config.grpc_port}', use_tls=False)
        remote_base = config.remote_dir.replace('\\', '/')
        original_send = network.send_event

        async def protected_send_event(event):
            if self.is_paused:
                self.log_cb(f'[Pull Protection] Local change event ignored: {os.path.basename(event.path)}', 'DEBUG')
                return
            rel_path = os.path.relpath(event.path, config.watch_dir).replace('\\', '/')
            event.path = f'{remote_base}/{rel_path}'.replace('//', '/')
            if getattr(event, 'target_path', None):
                rel_target = os.path.relpath(event.target_path, config.watch_dir).replace('\\', '/')
                event.target_path = f'{remote_base}/{rel_target}'.replace('//', '/')
            await original_send(event)
        network.send_event = protected_send_event
        original_send_patches = network.send_patches

        async def protected_send_patches(path, patches):
            if self.is_paused:
                return
            rel_path = os.path.relpath(path, config.watch_dir).replace('\\', '/')
            remote_abs_path = f'{remote_base}/{rel_path}'.replace('//', '/')
            await original_send_patches(remote_abs_path, patches)
        network.send_patches = protected_send_patches
        self.engine = SyncEngine(monitor, heuristic, delta_calc, network, state_mgr, max_workers=2)
        try:
            if self.ready_cb:
                self._async_loop.call_soon_threadsafe(self.ready_cb)
            self.status_cb('running')
            await self.engine.start()
        except Exception as e:
            self.log_cb(f'Engine Run Error: {e}', 'ERROR')
            raise e
        finally:
            if 'watchdog_task' in locals():
                watchdog_task.cancel()
                self.log_cb('Watchdog stopped.', 'DEBUG')