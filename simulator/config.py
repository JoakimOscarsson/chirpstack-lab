# config.py

import os
import argparse
import logging

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

def parse_config():
    """
    Parse config from:
      1) Hard-coded defaults
      2) Environment variables
      3) YAML file (if --config is provided)
      4) CLI arguments

    Returns a dict containing final config for:
      - 'gateway': { 'eui', 'udp_ip', 'udp_port' }
      - 'device_defaults': { 'nwk_skey', 'app_skey', 'devaddr', 'send_interval' }
      - 'devices': [ ... ] (for future multi-device usage)
    """

    # -------- 1. Define fallback defaults --------
    default_cfg = {
        "gateway": {
            "eui": "0102030405060708",
            "udp_ip": "chirpstack-gateway-bridge",
            "udp_port": 1700
        },
        "device_defaults": {
            "nwk_skey": "00000000000000000000000000000000",
            "app_skey": "00000000000000000000000000000000",
            "devaddr": "26011BDA",
            "send_interval": 10
        },
        # Future: store multiple device definitions here
        "devices": []
    }

    # -------- 2. Override defaults with Environment Variables (single device only) --------
    # Gateway
    if os.getenv("GATEWAY_EUI"):
        default_cfg["gateway"]["eui"] = os.getenv("GATEWAY_EUI")
    if os.getenv("UDP_IP"):
        default_cfg["gateway"]["udp_ip"] = os.getenv("UDP_IP")
    if os.getenv("UDP_PORT"):
        default_cfg["gateway"]["udp_port"] = int(os.getenv("UDP_PORT"))

    # Device defaults
    if os.getenv("NWK_SKEY"):
        default_cfg["device_defaults"]["nwk_skey"] = os.getenv("NWK_SKEY")
    if os.getenv("APP_SKEY"):
        default_cfg["device_defaults"]["app_skey"] = os.getenv("APP_SKEY")
    if os.getenv("DEVADDR"):
        default_cfg["device_defaults"]["devaddr"] = os.getenv("DEVADDR")
    if os.getenv("SEND_INTERVAL"):
        default_cfg["device_defaults"]["send_interval"] = int(os.getenv("SEND_INTERVAL"))

    # -------- 3. Parse CLI arguments --------
    parser = argparse.ArgumentParser(description="LoRaWAN Simulator Config")
    
    parser.add_argument("--config", help="Path to a YAML config file", default=None)
    # Gateway overrides
    parser.add_argument("--gateway-eui", help="Gateway EUI", default=None)
    parser.add_argument("--udp-ip", help="Gateway UDP IP", default=None)
    parser.add_argument("--udp-port", type=int, help="Gateway UDP Port", default=None)

    # Single device overrides
    parser.add_argument("--nwk-skey", help="NwkSKey for single device", default=None)
    parser.add_argument("--app-skey", help="AppSKey for single device", default=None)
    parser.add_argument("--devaddr", help="DevAddr for single device", default=None)
    parser.add_argument("--send-interval", type=int, help="Send interval for single device", default=None)

    args = parser.parse_args()

    # -------- 4. If --config is provided, load from file --------
    if args.config and YAML_AVAILABLE:
        with open(args.config, "r") as f:
            file_config = yaml.safe_load(f)

        # Gateway
        if "gateway" in file_config:
            if "eui" in file_config["gateway"]:
                default_cfg["gateway"]["eui"] = file_config["gateway"]["eui"]
            if "udp_ip" in file_config["gateway"]:
                default_cfg["gateway"]["udp_ip"] = file_config["gateway"]["udp_ip"]
            if "udp_port" in file_config["gateway"]:
                default_cfg["gateway"]["udp_port"] = file_config["gateway"]["udp_port"]

        # Device defaults
        if "device_defaults" in file_config:
            if "nwk_skey" in file_config["device_defaults"]:
                default_cfg["device_defaults"]["nwk_skey"] = file_config["device_defaults"]["nwk_skey"]
            if "app_skey" in file_config["device_defaults"]:
                default_cfg["device_defaults"]["app_skey"] = file_config["device_defaults"]["app_skey"]
            if "devaddr" in file_config["device_defaults"]:
                default_cfg["device_defaults"]["devaddr"] = file_config["device_defaults"]["devaddr"]
            if "send_interval" in file_config["device_defaults"]:
                default_cfg["device_defaults"]["send_interval"] = file_config["device_defaults"]["send_interval"]

        # FUTURE: If 'devices' is present, store it (not yet used)
        if "devices" in file_config:
            default_cfg["devices"] = file_config["devices"]

    elif args.config and not YAML_AVAILABLE:
        logger.warning("PyYAML not installed; ignoring --config file.")

    # -------- 5. Override with CLI for single device/gateway --------
    if args.gateway_eui:
        default_cfg["gateway"]["eui"] = args.gateway_eui
    if args.udp_ip:
        default_cfg["gateway"]["udp_ip"] = args.udp_ip
    if args.udp_port:
        default_cfg["gateway"]["udp_port"] = args.udp_port

    if args.nwk_skey:
        default_cfg["device_defaults"]["nwk_skey"] = args.nwk_skey
    if args.app_skey:
        default_cfg["device_defaults"]["app_skey"] = args.app_skey
    if args.devaddr:
        default_cfg["device_defaults"]["devaddr"] = args.devaddr
    if args.send_interval:
        default_cfg["device_defaults"]["send_interval"] = args.send_interval

    # If multiple devices were specified, just warn for now
    if len(default_cfg["devices"]) > 1:
        logger.warning(
            "Multiple devices detected in config, but multi-device logic not implemented yet. "
            "Using only device_defaults for now."
        )

    logger.debug(f"Final config: {default_cfg}")
    return default_cfg
