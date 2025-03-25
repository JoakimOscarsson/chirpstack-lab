import logging
import asyncio

from config import parse_config
from gateway import Gateway
from device_manager import DeviceManager

async def main_async():
    """
    The main async entry point. We'll:
      1. Parse config
      2. Create Gateway + DeviceManager (single device for now)
      3. Start the device manager's async loop
    """

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

def main():
    """
    The synchronous entry point that just launches the async loop.
    """
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("🛑 Simulator stopped.")

if __name__ == "__main__":
    main()
