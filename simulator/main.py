import os
import time
import logging

from config import parse_config
from gateway import Gateway
from device_manager import DeviceManager

def main():
    # Configure the root logger with a simple format and INFO level
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting LoRaWAN simulator")

    # Parse configuration (Defaults, env, YAML, CLI)
    cfg = parse_config()

    # Extract sub-config for convenience
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

    # Main loop
    try:
        while True:
            device_manager.send_all_uplinks()
            logger.info("Uplink sent by device_manager.")
            time.sleep(device_cfg["send_interval"])
    except KeyboardInterrupt:
        logger.info("🛑 Simulator stopped.")

if __name__ == "__main__":
    main()
