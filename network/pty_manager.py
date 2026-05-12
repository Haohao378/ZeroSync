import threading
import time
import re
import queue
from typing import Optional, Callable, Tuple
import paramiko

class PTYAgentLockError(Exception):
    pass

class PTYTimeoutError(Exception):
    pass

class StatefulPTYManager:
    AGENT_BOUNDARY_MARKER = '__ZEROSYNC_AGENT_CMD_END_MARKER_8F2A9C__'
    AGENT_START_MARKER = '__ZEROSYNC_AGENT_CMD_START_MARKER_8F2A9C__'

    def __init__(self, ssh_client: paramiko.SSHClient):
        self.ssh = ssh_client
        self.channel: Optional[paramiko.Channel] = None
        self._read_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._output_buffer = ''
        self._buffer_lock = threading.Lock()
        self.on_output_callback: Optional[Callable[[str], None]] = None
        self._is_agent_locked = False
        self._agent_lock_mutex = threading.Lock()
        self._agent_result_queue = queue.Queue()

    def start(self, initial_cmd: str=''):
        if not self.ssh or not self.ssh.get_transport() or (not self.ssh.get_transport().is_active()):
            raise RuntimeError('SSH Client is not connected.')
        self.channel = self.ssh.invoke_shell(term='xterm', width=120, height=40)
        self.channel.setblocking(0)
        self._stop_event.clear()
        self._read_thread = threading.Thread(target=self._continuous_read_loop, daemon=True, name='PTYReadLoop')
        self._read_thread.start()
        if initial_cmd:
            self.human_write(initial_cmd + '\n')

    def stop(self):
        self._stop_event.set()
        if self.channel:
            self.channel.close()
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)

    def _continuous_read_loop(self):
        while not self._stop_event.is_set():
            if self.channel and self.channel.recv_ready():
                try:
                    data = self.channel.recv(4096).decode('utf-8', errors='replace')
                    if not data:
                        time.sleep(0.01)
                        continue
                    if self.on_output_callback:
                        self.on_output_callback(data)
                    with self._buffer_lock:
                        self._output_buffer += data
                        if self._is_agent_locked:
                            self._check_agent_boundary_unsafe()
                except Exception as e:
                    import logging
                    logging.error(f'PTY read error: {e}')
                    time.sleep(0.1)
            else:
                time.sleep(0.01)

    def _check_agent_boundary_unsafe(self):
        if self.AGENT_BOUNDARY_MARKER in self._output_buffer:
            parts = self._output_buffer.split(self.AGENT_BOUNDARY_MARKER)
            raw_result = parts[0]
            self._output_buffer = self.AGENT_BOUNDARY_MARKER.join(parts[1:])
            clean_result = self._clean_agent_output(raw_result)
            self._agent_result_queue.put(clean_result)

    def _clean_agent_output(self, raw_output: str) -> str:
        if hasattr(self, 'AGENT_START_MARKER') and self.AGENT_START_MARKER in raw_output:
            actual_output = raw_output.split(self.AGENT_START_MARKER)[-1]
        else:
            lines = raw_output.split('\n')
            if not lines:
                return raw_output
            actual_output = '\n'.join(lines[1:])
        ansi_escape = re.compile('\\x1B(?:[@-Z\\\\-_]|\\[[0-?]*[ -/]*[@-~])')
        actual_output = ansi_escape.sub('', actual_output)
        cleaned_lines = [line.strip('\r') for line in actual_output.split('\n') if line.strip()]
        return '\n'.join(cleaned_lines).strip()

    def human_write(self, data: str):
        with self._agent_lock_mutex:
            if self._is_agent_locked:
                raise PTYAgentLockError('UI is currently locked by Agent Copilot.')
        if self.channel and self.channel.send_ready():
            self.channel.send(data.encode('utf-8'))

    def send_interrupt(self):
        if self.channel and self.channel.send_ready():
            self.channel.send(b'\x03')
        if self._is_agent_locked:
            with self._buffer_lock:
                partial_output = self._output_buffer
                self._output_buffer = ''
            clean_partial = self._clean_agent_output(partial_output)
            clean_partial += '\n[System: Execution Interrupted by User]'
            self._agent_result_queue.put(clean_partial + '\n?EXIT_CODE:130?')

    def agent_execute(self, command: str, timeout: int=30) -> Tuple[str, int]:
        with self._agent_lock_mutex:
            if self._is_agent_locked:
                raise PTYAgentLockError('Agent tried to execute, but PTY is already locked (Concurrent Agent calls?).')
            self._is_agent_locked = True
        while not self._agent_result_queue.empty():
            self._agent_result_queue.get_nowait()
        with self._buffer_lock:
            self._output_buffer = ''
        try:
            marker_end_p1 = self.AGENT_BOUNDARY_MARKER[:15]
            marker_end_p2 = self.AGENT_BOUNDARY_MARKER[15:]
            marker_start_p1 = self.AGENT_START_MARKER[:15]
            marker_start_p2 = self.AGENT_START_MARKER[15:]
            safe_command = command.rstrip()
            if not safe_command.endswith(';') and (not safe_command.endswith('&')) and ('\n' not in safe_command):
                safe_command += ';'
            elif '\n' in safe_command and (not safe_command.endswith('\n')):
                safe_command += '\n'
            magic_cmd = f'echo {marker_start_p1}""{marker_start_p2} ; {safe_command} echo "?EXIT_CODE:$??" ; echo {marker_end_p1}""{marker_end_p2}\r'
            if self.channel and self.channel.send_ready():
                self.channel.send(magic_cmd.encode('utf-8'))
            else:
                raise RuntimeError('SSH Channel is not ready.')
            try:
                result_str = self._agent_result_queue.get(timeout=timeout)
                exit_code = 0
                final_stdout = result_str
                final_stdout = final_stdout.replace('echo "?EXIT_CODE:$??"', '')
                final_stdout = final_stdout.replace('?EXIT_CODE:$??', '')
                match = re.search('\\?EXIT_CODE:(\\d+)\\?', final_stdout)
                if match:
                    exit_code = int(match.group(1))
                    final_stdout = final_stdout.replace(match.group(0), '').strip()
                final_stdout = '\n'.join([line for line in final_stdout.splitlines() if line.strip() and line.strip() != ';']).strip()
                return (final_stdout, exit_code)
            except queue.Empty:
                self.channel.send(b'\x03')
                raise PTYTimeoutError(f'Agent command timed out after {timeout}s and was forcibly interrupted.')
        finally:
            with self._agent_lock_mutex:
                self._is_agent_locked = False