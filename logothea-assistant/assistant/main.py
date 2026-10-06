"""uvicorn 진입점: uvicorn assistant.main:app --host 127.0.0.1 --port 8100"""

import logging

from assistant.app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = create_app()
