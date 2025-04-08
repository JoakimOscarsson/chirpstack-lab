import asyncio
import logging
import signal

from config import parse_config
from gateway import Gateway
from iot_device import IotDevice
from message_bus import MessageBus  # Your pub/sub event system

# --------- Global Logger Configuration ---------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# --------- Gateway Setup ---------
async def setup_gateway(gateway_cfg, message_bus):
    async def handle_downlink(raw_payload):
        await message_bus.publish(raw_payload)

    gateway = Gateway(
        eui=gateway_cfg["eui"],
        udp_ip=gateway_cfg["udp_ip"],
        udp_port=gateway_cfg["udp_port"],
        downlink_handler=handle_downlink  
    )
    await gateway.setup_async()
    logger.info("Gateway initialized.")
    return gateway

# --------- Device Setup ---------
def setup_devices(devices_cfg, message_bus, gateway):
    devices = []
    for dev in devices_cfg:
        device = IotDevice(
            dev_addr=dev["devaddr"],
            nwk_skey=dev["nwk_skey"],
            app_skey=dev["app_skey"],
            distance=dev["distance"],
            environment=dev["environment"],
            send_interval=dev["send_interval"],
            message_bus=message_bus
        )

        device.lorawan_module.set_uplink_interface(gateway.send_uplink_async)

        devices.append(device)
        logger.info(f"Device {dev['devaddr']} initialized.")
    return devices

# --------- Shutdown Logic ---------
async def shutdown(tasks, gateway):
    logger.info("Initiating graceful shutdown...")

    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            logger.info(f"Task {task.get_name()} cancelled.")

    await gateway.close_async()
    logger.info("Shutdown complete.")

# --------- Main Entrypoint ---------
async def main():
    logger.info("🚀 Starting LoRaWAN simulator")

    cfg = parse_config()
    gateway_cfg = cfg["gateway"]
    devices_cfg = cfg["devices"]

    # Init message bus
    message_bus = MessageBus()

    # Init gateway and start pull loop
    gateway = await setup_gateway(gateway_cfg, message_bus)
    gateway_pull_task = asyncio.create_task(gateway.pull_data_loop(), name="gateway_pull_loop")

    # Init and start devices
    devices = setup_devices(devices_cfg, message_bus, gateway)
    device_tasks = [
        asyncio.create_task(device.run_uplink_cycle(), name=f"uplink_{device.lorawan_module.dev_addr}")
        for device in devices
    ]

    all_tasks = [gateway_pull_task] + device_tasks

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received.")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, _signal_handler)
    loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    await shutdown_event.wait()
    await shutdown(all_tasks, gateway)

# --------- Run Entrypoint ---------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    logger.info("🛑 Simulator stopped.")



"""
backlog:


- Implement channel hopping and expand channel simulation to accountr for busy channels
- Add support for adr through config
- add callback to app for downlink
- add battery drain simulation
- Add choice to set init DR



"""


"""
Refactoring needs:
 - Radio envelope: turn into metadata package
 - Types: eg. environment->enum
 - function names
 - function arguments. do we need to send as much. Should we pack in some metadataclass?
 - Where do we store what parameter?


"""

"""

Things to add:
Simulate multi-divice crowdedness on channels
update configuration when adding devices (include options to set more parameters)
autojoin



Implement RX1 DR offset logic (uplink DR - offset, clamped)

Validate MIC of downlinks using NwkSKey

Add random RX window jitter / simulate device clock drift

Add channel collision detection in ChannelSimulator

Switch environment to Enum and validate inputs

Move device + radio config to dataclass or config object

Add optional battery drain model

Implement basic OTAA join simulation

Add metrics logging/export (e.g., total TXs, ACK rate, duty cycle violations)

CLI config runner or YAML-based test case runner




1 (High)
Implement collision/interference logic
Reflect actual packet loss from overlapping transmissions.
2 (High)
OTAA join procedure
Align with typical real-world LoRaWAN flow & dynamic keys.
3 (Med)
Advanced path-loss & environment model
Improve realism (Okumura-Hata, terrain, obstacles, etc.).
4 (Med)
Battery drain simulation
Provide a realistic â€œDevStatusâ€ response and device behavior.
5 (Med)
Expand MAC commands & ADR
Let the network server adapt SF & power fully in real time.
6 (Low)
Multi-gateway or multi-region support
Explore network coverage / collisions from multiple gateways.
7 (Low)
Scalability & performance approach
Support 100s or 1000s of IoT devices without performance hits.
8 (Low)
Visualization / Dashboard
Graphical overview of transmissions, SNR, collisions, etc.




"""