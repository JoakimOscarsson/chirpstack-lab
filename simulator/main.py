import asyncio
import logging
import signal

from config import parse_config
from gateway import Gateway
from device_manager import DeviceManager

async def shutdown(device_task, gateway, logger):
    """
    Perform graceful shutdown by cancelling tasks and closing the gateway.
    """
    logger.info("Initiating graceful shutdown...")
    
    # Cancel the device manager's task
    device_task.cancel()
    try:
        await device_task
    except asyncio.CancelledError:
        logger.info("Device tasks cancelled.")
    
    # Close the gateway's transport gracefully
    await gateway.close_async()
    logger.info("Shutdown complete.")

async def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting LoRaWAN simulator")

    # Parse configuration
    cfg = parse_config()
    gateway_cfg = cfg["gateway"]
    devices_list = cfg["devices"]

    # Create the DeviceManager (initially without gateway)
    device_manager = DeviceManager(None)

    # Create the Gateway and wire the downlink handler to DeviceManager
    gateway = Gateway(
        eui=gateway_cfg["eui"],
        udp_ip=gateway_cfg["udp_ip"],
        udp_port=gateway_cfg["udp_port"],
        downlink_handler=device_manager.dispatch_downlink
    )
    device_manager.gateway = gateway  # Set after gateway is created
    await gateway.setup_async()
    asyncio.create_task(gateway.pull_data_loop())

    logger.info(f"Config has {len(devices_list)} device(s).")
    for dev_conf in devices_list:
        device_manager.add_device(
            dev_addr=dev_conf["devaddr"],
            nwk_skey=dev_conf["nwk_skey"],
            app_skey=dev_conf["app_skey"],
            send_interval=dev_conf["send_interval"]
        )

    # Start the device manager's asynchronous loop
    device_task = asyncio.create_task(device_manager.start_all_devices_async())

    # Create an event to signal shutdown
    shutdown_event = asyncio.Event()

    # Define a signal handler that sets the shutdown event
    def _signal_handler():
        logger.info("Shutdown signal received.")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, _signal_handler)
    loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    # Wait until a shutdown signal is received
    await shutdown_event.wait()
    
    # Perform graceful shutdown
    await shutdown(device_task, gateway, logger)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # If KeyboardInterrupt escapes, it's safe to exit
        pass
    logging.getLogger(__name__).info("🛑 Simulator stopped.")