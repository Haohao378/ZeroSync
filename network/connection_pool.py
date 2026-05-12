import asyncio
import logging
from typing import Optional
import grpc
from grpc.aio import Channel
logger = logging.getLogger('ChannelManager')

class ChannelManager:

    def __init__(self, target_address: str, use_tls: bool=True):
        self.target_address = target_address
        self.use_tls = use_tls
        self._channel: Optional[Channel] = None
        self._state_watcher_task: Optional[asyncio.Task] = None
        self._is_connected = False

    def _get_channel_options(self) -> list:
        return [('grpc.max_send_message_length', 32 * 1024 * 1024), ('grpc.max_receive_message_length', 32 * 1024 * 1024), ('grpc.keepalive_time_ms', 60000), ('grpc.keepalive_timeout_ms', 10000), ('grpc.keepalive_permit_without_calls', 1), ('grpc.max_connection_idle_ms', 0), ('grpc.tcp_fastopen', 1)]

    async def connect(self) -> Channel:
        if self._channel is not None:
            return self._channel
        options = self._get_channel_options()
        logger.info(f'Connecting to {self.target_address} (TLS: {self.use_tls})...')
        if self.use_tls:
            credentials = grpc.ssl_channel_credentials()
            self._channel = grpc.aio.secure_channel(self.target_address, credentials, options=options)
        else:
            self._channel = grpc.aio.insecure_channel(self.target_address, options=options)
        self._state_watcher_task = asyncio.create_task(self._watch_connectivity_state())
        return self._channel

    async def _watch_connectivity_state(self):
        if not self._channel:
            return
        try:
            state = self._channel.get_state(try_to_connect=True)
            while True:
                if state == grpc.ChannelConnectivity.READY:
                    if not self._is_connected:
                        logger.info('gRPC Channel State: READY (Connected)')
                        self._is_connected = True
                elif state == grpc.ChannelConnectivity.TRANSIENT_FAILURE:
                    logger.warning('gRPC Channel State: TRANSIENT_FAILURE (Network dropped, retrying...)')
                    self._is_connected = False
                elif state == grpc.ChannelConnectivity.SHUTDOWN:
                    logger.error('gRPC Channel State: SHUTDOWN')
                    self._is_connected = False
                    break
                await self._channel.wait_for_state_change(state)
                state = self._channel.get_state(try_to_connect=False)
        except asyncio.CancelledError:
            logger.debug('Connectivity watcher stopped.')
        except Exception as e:
            logger.error(f'Connectivity watcher error: {e}')

    def get_channel(self) -> Channel:
        if not self._channel:
            raise RuntimeError('Channel is not connected. Call connect() first.')
        return self._channel

    async def close(self):
        if self._state_watcher_task:
            self._state_watcher_task.cancel()
        if self._channel:
            await self._channel.close()
            self._channel = None
        self._is_connected = False