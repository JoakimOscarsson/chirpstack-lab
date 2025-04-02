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

- Simulate duty cycle restrictions
- Add RX1/2 windows logic and match delays
- Simulate DevStatusAns and get stubbattery iot from device
- Implement channel hopping and expand channel simulation to accountr for busy channels
- Remove pingslotchannelreq since its only for class b?



"""


"""
Refactoring needs:
 - Architecture: Do each module, class and method respect the separation of concerns?
 - Radio envelope: turn into metadata package
 - Types: eg. environment->enum
 - function names
 - function arguments. do we need to send as much. Should we pack in some metadataclass?
 - Where do we store what parameter?


"""

"""

Things to add:
Chmas - update radio.enabled channels
Redundancy (NbTrans) - repeat uplinks in loop
Duty Cycle - track airtiem + delay
rd1_dr_offset - apply offset to uplink DR
rx2_datarate - use in RX2 receive logic
rx2_frequency - check in downlink accept logic
RX timing - add asyc timers and match timing windows (though I want to always receive, but nly print a debug log if wrong timing)
Smulate usage of multiple channels
Simulate multi-divice crowdedness on channels
Simulate distance
update configuration when adding devices (include options to set more parameters)
parse non mac commands to application logic and print there
confirmed up/down links
autojoin




"""