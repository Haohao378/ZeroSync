import asyncio
import logging
import os
import shutil
import argparse
import sys
try:
    import zstandard as zstd
    import grpc
    from grpc.aio import server, ServicerContext
except ImportError:
    print('\n[Fatal Error] Missing required packages.')
    print('Please run: pip install grpcio zstandard\n')
    sys.exit(1)
try:
    import sync_pb2
    import sync_pb2_grpc
except ImportError:
    print('\n[Fatal Error] Missing sync_pb2.py or sync_pb2_grpc.py.')
    print('These files should be in the same directory as this script.\n')
    sys.exit(1)
logging.basicConfig(level=logging.INFO, format='%(asctime)s.%(msecs)03d | SERVER | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('ZeroSyncServer')

class SyncServiceServicer(sync_pb2_grpc.SyncServiceServicer):

    def __init__(self):
        self.decompressor = zstd.ZstdDecompressor()
        logger.info('Server started in Global Daemon Mode (Directory Agnostic).')

    async def SyncEventStream(self, request_iterator, context: ServicerContext):
        async for event in request_iterator:
            try:
                real_path = event.path
                if event.event_type == 'CREATED':
                    if not os.path.exists(real_path):
                        if '.' in os.path.basename(real_path):
                            os.makedirs(os.path.dirname(real_path), exist_ok=True)
                            open(real_path, 'a').close()
                        else:
                            os.makedirs(real_path, exist_ok=True)
                elif event.event_type == 'DELETED':
                    if os.path.isfile(real_path):
                        os.remove(real_path)
                    elif os.path.isdir(real_path):
                        shutil.rmtree(real_path, ignore_errors=True)
                elif event.event_type == 'RENAMED':
                    target_path = event.target_path
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    if os.path.exists(target_path):
                        if os.path.isdir(target_path):
                            shutil.rmtree(target_path, ignore_errors=True)
                        else:
                            os.remove(target_path)
                    if os.path.exists(real_path):
                        os.rename(real_path, target_path)
                logger.info(f'Event Applied -> {event.event_type}: {real_path}')
                yield sync_pb2.ServerAck(event_id=event.event_id)
            except Exception as e:
                logger.error(f'Failed to apply {event.event_type} on {event.path}: {e}')

    async def UploadPatches(self, request: sync_pb2.PatchUploadRequest, context: ServicerContext):
        try:
            real_path = request.path
            if not os.path.exists(real_path):
                os.makedirs(os.path.dirname(real_path), exist_ok=True)
                open(real_path, 'wb').close()
            with open(real_path, 'r+b') as f:
                for patch in request.patches:
                    if patch.length == 0:
                        f.truncate(patch.offset)
                        continue
                    if patch.compressed_data:
                        raw_data = self.decompressor.decompress(patch.compressed_data)
                        f.seek(patch.offset)
                        f.write(raw_data)
            logger.info(f'Patched {len(request.patches)} blocks -> {real_path}')
            return sync_pb2.UploadResponse(success=True, error_msg='')
        except Exception as e:
            err_msg = str(e)
            logger.error(f'Patching failed on {request.path}: {err_msg}')
            return sync_pb2.UploadResponse(success=False, error_msg=err_msg)

async def serve(port: int):
    options = [('grpc.max_send_message_length', 32 * 1024 * 1024), ('grpc.max_receive_message_length', 32 * 1024 * 1024)]
    server_ins = server(options=options)
    sync_pb2_grpc.add_SyncServiceServicer_to_server(SyncServiceServicer(), server_ins)
    in_docker = os.path.exists('/.dockerenv')
    listen_addr = f'0.0.0.0:{port}' if in_docker else f'127.0.0.1:{port}'
    server_ins.add_insecure_port(listen_addr)
    logger.info('==================================================')
    logger.info('  ZeroSync Global Daemon Engine Starting...       ')
    logger.info('==================================================')
    logger.info(f'Listening Address: {listen_addr} (Docker: {in_docker})')
    await server_ins.start()
    await server_ins.wait_for_termination()
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ZeroSync Remote Server Agent')
    parser.add_argument('--port', type=int, default=50051, help='Port to listen on (default: 50051).')
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.port))
    except KeyboardInterrupt:
        logger.info('Server agent stopped by user.')