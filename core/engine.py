import asyncio
import logging
import uuid
import traceback
from concurrent.futures import ProcessPoolExecutor
from typing import Protocol, List, AsyncGenerator
from core.types import FSEvent, EventType, SyncTask, DeltaPatch
from core.heuristic import HeuristicEngine
from delta.calculator import calculate_delta_worker
logger = logging.getLogger('SyncEngine')

class MonitorProtocol(Protocol):

    async def listen(self) -> AsyncGenerator[FSEvent, None]:
        ...

    def get_current_event_id(self) -> str:
        ...

class DeltaCalcProtocol(Protocol):

    def calculate_delta_sync(self, path: str, inode: int) -> List[DeltaPatch]:
        ...

class NetworkProtocol(Protocol):

    async def connect(self) -> None:
        ...

    async def send_patches(self, path: str, patches: List[DeltaPatch]) -> None:
        ...

    async def send_event(self, event: FSEvent) -> None:
        ...

class StateProtocol(Protocol):

    def save_last_event_id(self, event_id: str) -> None:
        ...

    def update_merkle_tree(self, path: str, force_rehash: bool=False) -> None:
        ...

class SyncEngine:

    def __init__(self, monitor: MonitorProtocol, heuristic: HeuristicEngine, delta_calc: DeltaCalcProtocol, network: NetworkProtocol, state_mgr: StateProtocol, max_workers: int=4):
        self.monitor = monitor
        self.heuristic = heuristic
        self.delta_calc = delta_calc
        self.network = network
        self.state_mgr = state_mgr
        self.num_workers = 4
        self.task_queue: asyncio.Queue[SyncTask] = asyncio.Queue(maxsize=100000)
        self.process_pool = ProcessPoolExecutor(max_workers=max_workers)
        self.is_running = False
        self._workers: List[asyncio.Task] = []
        self.active_mod_tasks = set()
        self._file_locks = {}

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        logger.info('Starting Sync Engine...')
        await self.network.connect()
        worker = asyncio.create_task(self._task_consumer('Main-Barrier-Worker', self.task_queue))
        self._workers.append(worker)
        producer = asyncio.create_task(self._event_producer_loop())
        self._workers.append(producer)
        try:
            while self.is_running:
                done, pending = await asyncio.wait([producer], timeout=1.0)
                if done:
                    break
            if not producer.done():
                producer.cancel()
            if self.active_mod_tasks:
                logger.info(f'Graceful Drain: Waiting for {len(self.active_mod_tasks)} active tasks to finish (max 3s)...')
                await asyncio.wait(self.active_mod_tasks, timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.info('Sync Engine shutting down...')
        except Exception as e:
            logger.critical(f'Fatal error in event loop: {e}\n{traceback.format_exc()}')
        finally:
            for worker in self._workers:
                if not worker.done():
                    worker.cancel()
            for bg_task in list(self.active_mod_tasks):
                if not bg_task.done():
                    bg_task.cancel()
            if hasattr(self.network, 'stop'):
                asyncio.create_task(self.network.stop())
            if hasattr(self.monitor, 'stop'):
                self.monitor.stop()

    def stop(self):
        self.is_running = False

    def _get_file_lock(self, path: str) -> asyncio.Lock:
        if path not in self._file_locks:
            self._file_locks[path] = asyncio.Lock()
        return self._file_locks[path]

    async def _on_stable_event(self, event: FSEvent):
        task = SyncTask(task_id=uuid.uuid4().hex, event=event)
        try:
            await asyncio.wait_for(self.task_queue.put(task), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(f'Task queue full! Dropping event: {event.path}')

    async def _event_producer_loop(self):
        async for raw_event in self.monitor.listen():
            if not self.is_running:
                break
            await self.heuristic.process_raw_event(raw_event, self._on_stable_event)

    async def _task_consumer(self, worker_name: str, queue: asyncio.Queue):
        logger.debug(f'{worker_name} started.')
        while self.is_running:
            try:
                task = await queue.get()
                event = task.event
                if event.event_type == EventType.MODIFIED:

                    async def locked_mod_task(t=task):
                        lock = self._get_file_lock(t.event.path)
                        async with lock:
                            await self._process_modified_task(t)
                    bg_task = asyncio.create_task(locked_mod_task())
                    self.active_mod_tasks.add(bg_task)
                    bg_task.add_done_callback(self.active_mod_tasks.discard)
                else:
                    if self.active_mod_tasks:
                        logger.debug(f'🧱 [Barrier] 遇到结构事件 {event.event_type.value}，等待前方 {len(self.active_mod_tasks)} 个并发修改完成...')
                        await asyncio.gather(*self.active_mod_tasks, return_exceptions=True)
                    await self._process_structural_task(task)
                queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'{worker_name} unhandled error: {e}')

    async def _process_modified_task(self, task: SyncTask):
        event = task.event
        loop = asyncio.get_running_loop()
        while task.retry_count <= task.max_retries:
            try:
                import os
                from core.types import FileMeta
                try:
                    stat = os.stat(event.path)
                    event.meta = FileMeta(size=stat.st_size, mtime=stat.st_mtime, inode=stat.st_ino, is_dir=stat.st_mode & 16384 != 0)
                except FileNotFoundError:
                    logger.debug(f'Task {task.task_id} aborted: File {event.path} no longer exists.')
                    return
                except Exception as e:
                    raise e
                if event.meta.is_dir:
                    return
                patches: List[DeltaPatch] = await loop.run_in_executor(self.process_pool, calculate_delta_worker, self.state_mgr.db.db_path, event.path, event.meta.inode)
                if patches:
                    await self.network.send_patches(event.path, patches)
                self.state_mgr.save_last_event_id(event.event_id)
                self.state_mgr.update_merkle_tree(event.path, force_rehash=True)
                return
            except Exception as e:
                logger.error(f'Failed to process MODIFIED task {task.task_id}: {e}')
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    await asyncio.sleep(2 ** task.retry_count)
                else:
                    break

    async def _process_structural_task(self, task: SyncTask):
        event = task.event
        import copy
        while task.retry_count <= task.max_retries:
            try:
                logger.info(f'Processing STRUCTURAL {event.event_type.value}: {event.path}')
                event_copy = copy.copy(event)
                await self.network.send_event(event_copy)
                self.state_mgr.save_last_event_id(event.event_id)
                self.state_mgr.update_merkle_tree(event.path, force_rehash=False)
                if event.event_type == EventType.RENAMED and event.target_path:
                    import os
                    import time
                    if os.path.isdir(event.target_path):
                        for root, _, files in os.walk(event.target_path):
                            for f in files:
                                fb_event = FSEvent(event_id=f'fb_{time.time()}', event_type=EventType.MODIFIED, path=os.path.join(root, f), target_path=None, timestamp=time.time(), meta=None)
                                await self.task_queue.put(SyncTask(task_id=uuid.uuid4().hex, event=fb_event))
                    elif os.path.isfile(event.target_path):
                        fb_event = FSEvent(event_id=f'fb_{time.time()}', event_type=EventType.MODIFIED, path=event.target_path, target_path=None, timestamp=time.time(), meta=None)
                        await self.task_queue.put(SyncTask(task_id=uuid.uuid4().hex, event=fb_event))
                return
            except Exception as e:
                logger.error(f'Failed to process STRUCTURAL task {task.task_id}: {e}')
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    await asyncio.sleep(2 ** task.retry_count)
                else:
                    break