import os
import time
import logging
from typing import Optional
from network.agent_ipc import AgentActionDelegate, ExecuteResponse, PullResponse, StatusResponse
logger = logging.getLogger('ZeroSyncAgentDelegate')

class ZeroSyncAgentDelegate(AgentActionDelegate):

    def __init__(self, bridge, pty_manager, workspace_view, agent_ssh, active_config):
        self.bridge = bridge
        self.pty = pty_manager
        self.ui_view = workspace_view
        self.agent_ssh = agent_ssh
        self.config = active_config

    def execute_command(self, command: str, timeout: int, env_vars: dict) -> ExecuteResponse:
        start_time = time.time()
        if command.startswith('__INTERNAL_PORT_FORWARD__'):
            parts = command.split()
            remote_port = int(parts[1])
            local_port = int(parts[2])
            target_host = '127.0.0.1'
            docker_name = self.config.get('docker_name', '')
            if docker_name:
                try:
                    cmd = "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' " + f'"{docker_name}"'
                    stdin, stdout, stderr = self.agent_ssh.exec_command(cmd)
                    ip_out = stdout.read().decode('utf-8').strip()
                    docker_ip = next((ip for ip in ip_out.split() if ip), '')
                    if docker_ip:
                        target_host = docker_ip
                        logger.info(f'Agent PortForward: Auto-detected Docker IP {target_host} for {docker_name}')
                except Exception as e:
                    logger.warning(f'Agent PortForward: Failed to get Docker IP, fallback to 127.0.0.1. Error: {e}')
            self._start_paramiko_forward(local_port, target_host, remote_port)
            return ExecuteResponse(stdout=f'SUCCESS|http://127.0.0.1:{local_port}', stderr='', exit_code=0, execution_time=time.time() - start_time)
        try:
            self.ui_view.set_agent_lock(True)
            out_str, exit_code = self.pty.agent_execute(command, timeout=timeout)
            return ExecuteResponse(stdout=out_str, stderr='', exit_code=exit_code, execution_time=time.time() - start_time)
        except Exception as e:
            return ExecuteResponse(stdout='', stderr=str(e), exit_code=-1, execution_time=time.time() - start_time)
        finally:
            self.ui_view.set_agent_lock(False)

    def pull_remote_file(self, remote_path: str, dest_dir: Optional[str]) -> PullResponse:
        local_sync_dir = self.config.get('local_dir', '.')
        remote_base_dir = self.config.get('remote_dir', '/')
        if remote_path.startswith(remote_base_dir):
            rel_path = os.path.relpath(remote_path, remote_base_dir).replace('\\', '/')
            local_path = os.path.normpath(os.path.join(local_sync_dir, rel_path))
        else:
            local_path = os.path.normpath(os.path.join(local_sync_dir, os.path.basename(remote_path)))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        try:
            if self.bridge:
                self.bridge.pause_sync_for_pull()
            logger.info(f'Agent pulling: {remote_path} -> {local_path}')
            docker_name = self.config.get('docker_name', '')
            if docker_name:
                import uuid
                tmp_host_path = f'/tmp/agent_dl_{uuid.uuid4().hex}.tmp'
                clean_remote = remote_path.replace('"', '\\"')
                cmd1 = f'docker cp "{docker_name}:{clean_remote}" "{tmp_host_path}"'
                _, stdout1, stderr1 = self.agent_ssh.exec_command(cmd1)
                if stdout1.channel.recv_exit_status() != 0:
                    raise RuntimeError(f"Docker CP 失败: {stderr1.read().decode('utf-8')}")
                sftp = self.agent_ssh.open_sftp()
                try:
                    self._sftp_get_recursive(sftp, tmp_host_path, local_path)
                finally:
                    sftp.close()
                    self.agent_ssh.exec_command(f'rm -rf "{tmp_host_path}"')
            else:
                sftp = self.agent_ssh.open_sftp()
                try:
                    self._sftp_get_recursive(sftp, remote_path, local_path)
                finally:
                    sftp.close()
            return PullResponse(status='success', local_path=local_path, error_msg='')
        except Exception as e:
            return PullResponse(status='failed', local_path='', error_msg=str(e))
        finally:
            if self.bridge:
                time.sleep(2)
                self.bridge.resume_sync()

    def _sftp_get_recursive(self, sftp, remote_path: str, local_path: str):
        import stat
        import os
        remote_stat = sftp.stat(remote_path)
        if stat.S_ISDIR(remote_stat.st_mode):
            os.makedirs(local_path, exist_ok=True)
            for item in sftp.listdir(remote_path):
                self._sftp_get_recursive(sftp, f'{remote_path}/{item}', os.path.join(local_path, item))
        else:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            sftp.get(remote_path, local_path)

    def get_system_status(self) -> StatusResponse:
        return StatusResponse(is_connected=True, sync_queue_size=self.bridge.engine.task_queue.qsize() if self.bridge and getattr(self.bridge, 'engine', None) else 0, is_terminal_idle=not self.pty._is_agent_locked, workspace_path=self.config.get('remote_dir', ''), docker_container=self.config.get('docker_name', ''))

    def _start_paramiko_forward(self, local_port: int, remote_host: str, remote_port: int):
        import threading
        import socket
        import select

        def forward_loop():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.bind(('127.0.0.1', local_port))
                server.listen(100)
                logger.info(f'Agent Tunnel Started: Local 127.0.0.1:{local_port} -> Remote {remote_host}:{remote_port}')
            except Exception as e:
                logger.error(f'Agent Tunnel Bind failed: {e}')
                return

            def handler(client_sock):
                try:
                    transport = self.agent_ssh.get_transport()
                    chan = transport.open_channel('direct-tcpip', (remote_host, remote_port), client_sock.getpeername())
                    if chan is None:
                        client_sock.close()
                        return
                except Exception as e:
                    logger.error(f'Agent Tunnel SSH channel open failed: {e}')
                    client_sock.close()
                    return
                while True:
                    r, w, x = select.select([client_sock, chan], [], [])
                    if client_sock in r:
                        data = client_sock.recv(4096)
                        if not data:
                            break
                        chan.sendall(data)
                    if chan in r:
                        data = chan.recv(4096)
                        if not data:
                            break
                        client_sock.sendall(data)
                chan.close()
                client_sock.close()
            while True:
                try:
                    client_sock, addr = server.accept()
                    threading.Thread(target=handler, args=(client_sock,), daemon=True).start()
                except Exception:
                    break
        threading.Thread(target=forward_loop, daemon=True).start()