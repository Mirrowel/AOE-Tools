import logging
import queue

log_queue = queue.Queue()
log_history = []

class QueueHandler(logging.Handler):
    """A custom logging handler that puts messages into a queue."""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        message = self.format(record)
        log_history.append(message)
        self.log_queue.put(message)

def setup_logging():
    """Configures the root logger."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Console handler
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # GUI queue handler
    queue_handler = QueueHandler(log_queue)
    queue_handler.setFormatter(formatter)
    logger.addHandler(queue_handler)