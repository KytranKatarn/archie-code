"""CLI entry point — python -m archie_engine."""

import asyncio
import logging
import signal

from archie_engine import __version__
from archie_engine.config import EngineConfig
from archie_engine.engine import Engine


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger = logging.getLogger(__name__)
    config = EngineConfig()
    engine = Engine(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        loop.create_task(engine.stop())
        loop.call_soon(loop.stop)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        loop.run_until_complete(engine.start())
        print(f"ARCHIE Engine v{__version__} listening on ws://{config.ws_host}:{engine.server.port}")
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(engine.stop())
        loop.close()


if __name__ == "__main__":
    main()
