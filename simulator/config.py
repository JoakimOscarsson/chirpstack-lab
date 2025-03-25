# config.py

import os
import argparse
import logging
import yaml

logger = logging.getLogger(__name__)

BUILT_IN_DEFAULTS = {
    "gateway_eui": "0102030405060708",
    "udp_ip": "chirpstack-gateway-bridge",
    "udp_port": 1700,

    "nwk_skey": "00000000000000000000000000000000",
    "app_skey": "00000000000000000000000000000000",
    "devaddr": "26011BDA",
    "send_interval": 10
}

def parse_config():
    """
    1) Start with built-in defaults.
    2) Override via environment variables (for single-device scenario).
    3) Override via CLI arguments (for single-device scenario).
    4) If --config is provided, parse that file to possibly define:
       - gateway: { eui, udp_ip, udp_port }
       - devices: [ {...}, {...} ]

       If 'devices' is empty or not specified, we do single-device scenario 
       with fallback to built-in defaults (and/or env/CLI).
       If multiple devices are specified, each device must have 'devaddr' 
       and must be unique.

    Returns a dict with:
      {
        "gateway": {
          "eui": str,
          "udp_ip": str,
          "udp_port": int
        },
        "devices": [
          {
            "devaddr": str,
            "nwk_skey": str,
            "app_skey": str,
            "send_interval": int
          },
          ...
        ]
      }
    """

    # 1) Start with built-in defaults
    conf = {
        "gateway_eui": BUILT_IN_DEFAULTS["gateway_eui"],
        "udp_ip": BUILT_IN_DEFAULTS["udp_ip"],
        "udp_port": BUILT_IN_DEFAULTS["udp_port"],

        "nwk_skey": BUILT_IN_DEFAULTS["nwk_skey"],
        "app_skey": BUILT_IN_DEFAULTS["app_skey"],
        "devaddr": BUILT_IN_DEFAULTS["devaddr"],
        "send_interval": BUILT_IN_DEFAULTS["send_interval"]
    }

    # 2) Override with environment variables (single device)
    if os.getenv("GATEWAY_EUI"):
        conf["gateway_eui"] = os.getenv("GATEWAY_EUI")
    if os.getenv("UDP_IP"):
        conf["udp_ip"] = os.getenv("UDP_IP")
    if os.getenv("UDP_PORT"):
        conf["udp_port"] = int(os.getenv("UDP_PORT"))

    if os.getenv("NWK_SKEY"):
        conf["nwk_skey"] = os.getenv("NWK_SKEY")
    if os.getenv("APP_SKEY"):
        conf["app_skey"] = os.getenv("APP_SKEY")
    if os.getenv("DEVADDR"):
        conf["devaddr"] = os.getenv("DEVADDR")
    if os.getenv("SEND_INTERVAL"):
        conf["send_interval"] = int(os.getenv("SEND_INTERVAL"))

    # 3) Parse CLI arguments
    parser = argparse.ArgumentParser(description="LoRaWAN Simulator")
    parser.add_argument("--config", help="Path to a YAML config file", default=None)

    parser.add_argument("--gateway-eui", help="Gateway EUI", default=None)
    parser.add_argument("--udp-ip", help="Gateway UDP IP", default=None)
    parser.add_argument("--udp-port", type=int, help="Gateway UDP port", default=None)

    parser.add_argument("--nwk-skey", help="NwkSKey (single device)", default=None)
    parser.add_argument("--app-skey", help="AppSKey (single device)", default=None)
    parser.add_argument("--devaddr", help="DevAddr (single device)", default=None)
    parser.add_argument("--send-interval", type=int, help="Send interval (single device)", default=None)

    args = parser.parse_args()

    if args.gateway_eui:
        conf["gateway_eui"] = args.gateway_eui
    if args.udp_ip:
        conf["udp_ip"] = args.udp_ip
    if args.udp_port:
        conf["udp_port"] = args.udp_port

    if args.nwk_skey:
        conf["nwk_skey"] = args.nwk_skey
    if args.app_skey:
        conf["app_skey"] = args.app_skey
    if args.devaddr:
        conf["devaddr"] = args.devaddr
    if args.send_interval:
        conf["send_interval"] = args.send_interval

    # We'll store the final gateway + devices in a structured dict
    final_cfg = {
        "gateway": {
            "eui": conf["gateway_eui"],
            "udp_ip": conf["udp_ip"],
            "udp_port": conf["udp_port"]
        },
        "devices": []  # We'll build this next
    }

    # 4) If --config is provided, parse that file
    if args.config:
        with open(args.config, "r") as f:
            file_config = yaml.safe_load(f) or {}  # handle empty file returning None

        # If user specified 'gateway' in config, override final_cfg["gateway"]
        gw_conf = file_config.get("gateway", {})
        if "eui" in gw_conf:
            final_cfg["gateway"]["eui"] = gw_conf["eui"]
        if "udp_ip" in gw_conf:
            final_cfg["gateway"]["udp_ip"] = gw_conf["udp_ip"]
        if "udp_port" in gw_conf:
            final_cfg["gateway"]["udp_port"] = gw_conf["udp_port"]

        # If user specified 'devices' in config, parse them
        dev_list = file_config.get("devices", [])
        if len(dev_list) > 0:
            # We have multi-device or single-device from config
            validated_devices = _validate_multi_devices(dev_list)
            final_cfg["devices"] = validated_devices
        else:
            # No devices in config -> single device from built-in/env/CLI
            final_cfg["devices"].append({
                "devaddr": conf["devaddr"],
                "nwk_skey": conf["nwk_skey"],
                "app_skey": conf["app_skey"],
                "send_interval": conf["send_interval"]
            })
    else:
        # No config file -> single device from built-in/env/CLI
        final_cfg["devices"].append({
            "devaddr": conf["devaddr"],
            "nwk_skey": conf["nwk_skey"],
            "app_skey": conf["app_skey"],
            "send_interval": conf["send_interval"]
        })

    logger.debug(f"Final config: {final_cfg}")
    return final_cfg

def _validate_multi_devices(dev_list):
    """
    Validate each device in dev_list:
      - If there's more than 1 device, each MUST specify devaddr.
      - If there's exactly 1 device, devaddr is also mandatory (since user is specifying).
      - We'll fallback to built-in defaults for anything not specified except devaddr if multi > 1.
      - Must be unique devaddr across all.
    Returns a list of device dicts with all fields filled.
    """
    used_devaddrs = set()
    validated = []

    # We'll consider "multi-device" as dev_list with length >= 2,
    # but even if it's a single device in dev_list, we treat it as "the user is specifying the device"
    for idx, dev_conf in enumerate(dev_list):
        devaddr = dev_conf.get("devaddr")
        # If multiple devices, devaddr must be specified
        # If there's only one device in the file, devaddr also must be specified 
        # because user intentionally wrote a device block
        if not devaddr:
            raise ValueError(f"Device at index {idx} missing 'devaddr'. It's required in config if specifying a device block.")

        nwk_skey = dev_conf.get("nwk_skey", BUILT_IN_DEFAULTS["nwk_skey"])
        app_skey = dev_conf.get("app_skey", BUILT_IN_DEFAULTS["app_skey"])
        send_interval = dev_conf.get("send_interval", BUILT_IN_DEFAULTS["send_interval"])

        if devaddr in used_devaddrs:
            raise ValueError(f"Duplicate devaddr '{devaddr}' in config file. Must be unique.")
        used_devaddrs.add(devaddr)

        validated.append({
            "devaddr": devaddr,
            "nwk_skey": nwk_skey,
            "app_skey": app_skey,
            "send_interval": send_interval
        })

    return validated
