import logging
import asyncio
import signal

from config import parse_config
from gateway import Gateway
from device_manager import DeviceManager

async def main_async():
    # Configure the root logger with a simple format and INFO level
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting LoRaWAN simulator")

    # Parse configuration (Defaults, env, YAML, CLI)
    cfg = parse_config()
    gateway_cfg = cfg["gateway"]
    device_cfg = cfg["device_defaults"]  # single device right now

    # Create the Gateway
    gateway = Gateway(
        eui=gateway_cfg["eui"],
        udp_ip=gateway_cfg["udp_ip"],
        udp_port=gateway_cfg["udp_port"]
    )
    await gateway.setup_async()

    # Create the DeviceManager (managing one device for now)
    device_manager = DeviceManager(
        gateway=gateway,
        dev_addr=device_cfg["devaddr"],
        nwk_skey=device_cfg["nwk_skey"],
        app_skey=device_cfg["app_skey"],
        send_interval=device_cfg["send_interval"]
    )

    # Start the device manager's asynchronous loop
    # This call won't return until KeyboardInterrupt or an error
    await device_manager.run_single_device_loop()


async def shutdown(loop, logger, tasks, gateway):
    """
    Cancel running tasks, signal device(s) to stop, and close the gateway gracefully.
    """
    logger.info("Graceful shutdown initiated...")

    # 1. Cancel running tasks (except this one)
    for task in tasks:
        if task is not asyncio.current_task():
            task.cancel()

    # 2. Wait briefly for tasks to cancel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    logger.debug(f"Task cancellation results: {results}")

    # 3. Close gateway transport
    if gateway is not None:
        await gateway.close_async()

    # 4. Stop the event loop
    loop.stop()
    logger.info("Event loop stopped.")


def main():
    logger = logging.getLogger(__name__)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    gateway = None  # We'll capture a reference so we can close it in shutdown

    # Create a task for main_async
    main_task = loop.create_task(main_async())

    # Signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, 
            lambda s=sig: asyncio.create_task(
                shutdown(
                    loop=loop,
                    logger=logger,
                    tasks=asyncio.all_tasks(loop),
                    gateway=gateway
                )
            )
        )

    try:
        loop.run_forever()
    finally:
        loop.close()
        logger.info("🛑 Simulator stopped.")

if __name__ == "__main__":
    main()
