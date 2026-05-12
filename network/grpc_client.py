import asyncio
import logging
from typing import List, Optional
import grpc
from grpc.aio import AioRpcError
from core.types import FSEvent, DeltaPatch
from network.connection_pool import ChannelManager
logger = logging.getLogger('AsyncNetworkClient')

class _MockSyncStub:

    def __init__(self, channel):
        self.channel = channel
        self.SyncEventStream = channel.stream_stream('/sync.SyncService/SyncEventStream', request_serializer=lambda x: str(x).encode(), response_deserializer=lambda x: x)
        self.UploadPatches = channel.unary_unary('/sync.SyncService/UploadPatches', request_serializer=lambda x: str(x).encode(), response_deserializer=lambda x: x)
try:
    import sync_pb2
    import sync_pb2_grpc
    HAS_PROTO = True
except ImportError:
    HAS_PROTO = False

class AsyncNetworkClient:

    def __init__(self, target_address: str='127.0.0.1:50051', use_tls: bool=False):
        self.channel_mgr = ChannelManager(target_address, use_tls)
        self.stub = None
        self._event_queue: asyncio.Queue[FSEvent] = asyncio.Queue()
        self._stream_task: Optional[asyncio.Task] = None
        self.is_running = False
        self._unacked_events = {}

    async def connect(self) -> None:
        channel = await self.channel_mgr.connect()
        if HAS_PROTO:
            self.stub = sync_pb2_grpc.SyncServiceStub(channel)
        else:
            self.stub = _MockSyncStub(channel)
        self.is_running = True
        self._stream_task = asyncio.create_task(self._maintain_event_stream())

    async def send_event(self, event: FSEvent) -> None:
        if not self.is_running:
            raise RuntimeError('Network client is not running.')
        ack_event = asyncio.Event()
        event._ack_event = ack_event
        await self._event_queue.put(event)
        try:
            await asyncio.wait_for(ack_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(f'ACK timeout for {event.event_type.value} on {event.path}')

    async def send_patches(self, path: str, patches: List[DeltaPatch]) -> None:
        if not patches:
            return
        logger.debug(f'Uploading {len(patches)} patches for {path}')
        try:
            MAX_PAYLOAD_SIZE = 2 * 1024 * 1024
            current_batch = []
            current_size = 0
            for p in patches:
                patch_size = len(p.compressed_data) if p.compressed_data else 0
                patch_size += 64
                if current_batch and current_size + patch_size > MAX_PAYLOAD_SIZE:
                    await self._send_patch_batch(path, current_batch)
                    current_batch = []
                    current_size = 0
                current_batch.append(p)
                current_size += patch_size
            if current_batch:
                await self._send_patch_batch(path, current_batch)
            logger.info(f'Successfully uploaded {len(patches)} patches for {path}')
        except AioRpcError as rpc_err:
            logger.error(f'gRPC Error uploading patches for {path}: {rpc_err.code().name} - {rpc_err.details()}')
            raise
        except Exception as e:
            logger.error(f'Failed to upload patches for {path}: {e}')
            raise

    async def _send_patch_batch(self, path: str, batch: List[DeltaPatch]) -> None:
        if HAS_PROTO:
            pb_patches = [sync_pb2.PatchData(offset=p.offset, length=p.length, compressed_data=p.compressed_data) for p in batch]
            request = sync_pb2.PatchUploadRequest(path=path, patches=pb_patches)
        else:
            request = {'path': path, 'patches': [{'offset': p.offset, 'len': p.length} for p in batch]}
        response = await self.stub.UploadPatches(request, timeout=30.0)
        if HAS_PROTO and (not response.success):
            raise RuntimeError(f'Server rejected patches for {path}: {response.error_msg}')

    def _format_pb(self, event):
        if HAS_PROTO:
            return sync_pb2.FSEventMessage(event_id=event.event_id, event_type=event.event_type.value, path=event.path, target_path=event.target_path or '', timestamp=event.timestamp)
        return {'id': event.event_id, 'type': event.event_type.value, 'path': event.path}

    async def _maintain_event_stream(self):
        while self.is_running:
            try:
                stream_call = self.stub.SyncEventStream()
                logger.info('Event Stream established. Ready for high-concurrency transmission.')
                unacked_events = self._unacked_events

                async def receive_acks():
                    try:
                        async for ack in stream_call:
                            ack_id = ack.event_id if hasattr(ack, 'event_id') else ack.get('id')
                            if ack_id in unacked_events:
                                orig_event = unacked_events.pop(ack_id)
                                if hasattr(orig_event, '_ack_event'):
                                    orig_event._ack_event.set()
                                self._event_queue.task_done()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.debug('ACK Receiver stopped (Connection reset).')
                ack_task = asyncio.create_task(receive_acks())
                for old_event in list(unacked_events.values()):
                    await stream_call.write(self._format_pb(old_event))
                while self.is_running:
                    get_task = asyncio.create_task(self._event_queue.get())
                    done, pending = await asyncio.wait([get_task, ack_task], return_when=asyncio.FIRST_COMPLETED)
                    if get_task in done:
                        event = get_task.result()
                        unacked_events[event.event_id] = event
                        try:
                            await stream_call.write(self._format_pb(event))
                        except Exception:
                            pass
                    if ack_task in done:
                        if get_task not in done:
                            get_task.cancel()
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                err_msg = str(e)
                if 'RPC already finished' not in err_msg and 'Locally cancelled' not in err_msg:
                    logger.warning(f'Event Stream disconnected: {err_msg}. Reconnecting in 2s...')
                    raise RuntimeError(err_msg)
            if 'ack_task' in locals() and (not ack_task.done()):
                ack_task.cancel()
            await asyncio.sleep(2.0)

    async def stop(self):
        self.is_running = False
        if self._stream_task:
            self._stream_task.cancel()
        await self.channel_mgr.close()