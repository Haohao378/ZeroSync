import os
import time
import secrets
import asyncio
import threading
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

class ExecuteRequest(BaseModel):
    command: str = Field(..., description='需要注入到 PTY 执行的 Shell 命令')
    timeout: int = Field(30, description='命令执行的超时时间(秒)')
    env_vars: Optional[Dict[str, str]] = Field(default_factory=dict, description='临时环境变量')

class ExecuteResponse(BaseModel):
    stdout: str = Field(..., description='标准输出')
    stderr: str = Field(..., description='标准错误')
    exit_code: int = Field(..., description='退出状态码 (0 表示成功)')
    execution_time: float = Field(..., description='执行耗时')

class PullRequest(BaseModel):
    remote_path: str = Field(..., description='远端需要拉取的文件或目录路径')
    dest_dir: Optional[str] = Field(None, description='可选的本地临时存放目录')

class PullResponse(BaseModel):
    status: str = Field(..., description='状态: success/failed/in_progress')
    local_path: str = Field(..., description='拉取到本地的绝对路径')
    error_msg: str = Field('', description='错误信息（如果有）')

class StatusResponse(BaseModel):
    is_connected: bool = Field(..., description='当前是否连接到了远程服务器')
    sync_queue_size: int = Field(..., description='当前本地同步队列积压的文件数量')
    is_terminal_idle: bool = Field(..., description='PTY 终端当前是否空闲')
    workspace_path: str = Field(..., description='远端挂载的工作区路径')
    docker_container: Optional[str] = Field(None, description='当前操作的 Docker 容器名')

class AgentActionDelegate(ABC):

    @abstractmethod
    def execute_command(self, command: str, timeout: int, env_vars: dict) -> ExecuteResponse:
        raise NotImplementedError('execute_command must be implemented by host application')

    @abstractmethod
    def pull_remote_file(self, remote_path: str, dest_dir: Optional[str]) -> PullResponse:
        raise NotImplementedError('pull_remote_file must be implemented by host application')

    @abstractmethod
    def get_system_status(self) -> StatusResponse:
        raise NotImplementedError('get_system_status must be implemented by host application')

class AgentIPCGateway:

    def __init__(self, host: str='127.0.0.1', port: int=50052, delegate: Optional[AgentActionDelegate]=None):
        self.host = host
        self.port = port
        self.delegate = delegate
        self.access_token = secrets.token_hex(32)
        self.app = FastAPI(title='ZeroSync Agent IPC API', description='Local bridge for Agentic Copilot integration.', version='1.0.0')
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._logger = logging.getLogger('AgentIPCGateway')
        self._setup_middlewares()
        self._setup_routes()

    def _setup_middlewares(self):
        self.app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

    def _verify_token(self, credentials: HTTPAuthorizationCredentials=Depends(HTTPBearer())):
        if not secrets.compare_digest(credentials.credentials, self.access_token):
            self._logger.warning(f'Unauthorized Agent access attempt intercepted!')
            raise HTTPException(status_code=401, detail='Invalid or Missing Agent Access Token')
        return True

    def _setup_routes(self):

        @self.app.post('/api/agent/execute', response_model=ExecuteResponse, dependencies=[Depends(self._verify_token)])
        def _api_execute(req: ExecuteRequest):
            if not self.delegate:
                raise HTTPException(status_code=503, detail='System not ready: Delegate is missing.')
            try:
                return self.delegate.execute_command(req.command, req.timeout, req.env_vars)
            except Exception as e:
                self._logger.error(f'Agent Execution Error: {e}', exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post('/api/agent/pull', response_model=PullResponse, dependencies=[Depends(self._verify_token)])
        def _api_pull(req: PullRequest):
            if not self.delegate:
                raise HTTPException(status_code=503, detail='System not ready.')
            try:
                return self.delegate.pull_remote_file(req.remote_path, req.dest_dir)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get('/api/agent/status', response_model=StatusResponse, dependencies=[Depends(self._verify_token)])
        def _api_status():
            if not self.delegate:
                raise HTTPException(status_code=503, detail='System not ready.')
            try:
                return self.delegate.get_system_status()
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

    def _run_server(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        config = uvicorn.Config(app=self.app, host=self.host, port=self.port, log_level='error', loop='asyncio')
        self._server = uvicorn.Server(config)
        self._logger.info(f'Agent IPC Gateway started at http://{self.host}:{self.port}')
        self._logger.info(f'AGENT ACCESS TOKEN: {self.access_token}')
        loop.run_until_complete(self._server.serve())

    def start(self):
        if self._thread and self._thread.is_alive():
            self._logger.warning('Agent IPC Gateway is already running.')
            return
        self._thread = threading.Thread(target=self._run_server, daemon=True, name='AgentIPCThread')
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=2.0)
            self._logger.info('Agent IPC Gateway stopped.')

    def get_agent_config(self) -> dict:
        return {'endpoint': f'http://{self.host}:{self.port}', 'token': self.access_token}