from __future__ import annotations

import redis
from rq import Queue, Worker

from .settings import get_settings


def main() -> None:
    settings = get_settings()
    connection = redis.from_url(settings.redis_url)
    queue = Queue(settings.queue_name, connection=connection)
    Worker([queue], connection=connection).work()


if __name__ == "__main__":
    main()
