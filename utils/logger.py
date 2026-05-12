import os
import sys
import logging
import logging.handlers
from queue import Queue
_log_queue_listener = None
_ui_log_callback = None

def register_ui_log_callback(cb):
    global _ui_log_callback
    _ui_log_callback = cb

class UIForwardHandler(logging.Handler):

    def emit(self, record):
        if _ui_log_callback:
            try:
                msg = f'[{record.name}] {record.getMessage()}'
                _ui_log_callback(msg, record.levelname)
            except Exception:
                pass

def setup_logger(name: str='ZeroSync', log_dir: str='logs', level: int=logging.INFO, max_bytes: int=20 * 1024 * 1024, backup_count: int=5) -> logging.Logger:
    global _log_queue_listener
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger()
    if logger.handlers:
        return logging.getLogger(name)
    logger.setLevel(level)
    fmt = '%(asctime)s.%(msecs)03d | %(levelname)-8s | [%(threadName)s] %(name)s - %(message)s'
    date_fmt = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(fmt, datefmt=date_fmt)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    file_path = os.path.join(log_dir, 'zerosync.log')
    file_handler = logging.handlers.RotatingFileHandler(file_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    log_queue = Queue(-1)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    logger.addHandler(queue_handler)
    ui_handler = UIForwardHandler()
    ui_handler.setLevel(level)
    _log_queue_listener = logging.handlers.QueueListener(log_queue, console_handler, file_handler, ui_handler, respect_handler_level=True)
    _log_queue_listener.start()
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    business_logger = logging.getLogger(name)
    business_logger.info('===================================================')
    business_logger.info('ZeroSync High-Performance Logger Initialized.')
    business_logger.info('===================================================')
    return business_logger

def shutdown_logger():
    global _log_queue_listener
    if _log_queue_listener:
        _log_queue_listener.stop()
        logging.getLogger('ZeroSync').info('Logger completely flushed and shutdown.')