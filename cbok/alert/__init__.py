import logging
import warnings

warnings.filterwarnings(
    "ignore",
    message="Couldn't find ffmpeg or avconv"
)

logging.getLogger("filelock").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
