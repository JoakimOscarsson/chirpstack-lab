# LoRaWAN Simulator - Technical Documentation

## Table of Contents
1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
   1. [High-Level Components](#21-high-level-components)
   2. [System Architecture Diagram](#22-system-architecture-diagram)
3. [Detailed Module Responsibilities](#3-detailed-module-responsibilities)
   1. [`main.py`](#31-mainpy)
   2. [`gateway.py`](#32-gatewaypy)
   3. [`device.py`](#33-devicepy)
   4. [`device_manager.py`](#34-device_managerpy)
   5. [`mac_commands.py`](#35-mac_commandspy)
4. [Data Flows](#4-data-flows)
   1. [Sending an Uplink](#41-sending-an-uplink)
   2. [Receiving a Downlink](#42-receiving-a-downlink)
5. [Deployment Scenarios](#5-deployment-scenarios)
   1. [Single Container](#51-single-container)
   2. [Multiple Containers](#52-multiple-containers)
6. [Future Enhancements](#6-future-enhancements)
7. [Conclusion](#7-conclusion)
8. [References & Notes](#8-references--notes)

---

## 1. Overview

This simulator is designed to emulate LoRaWAN gateways and devices for testing ChirpStack (or similar LoRaWAN Network Servers) without requiring physical hardware. The core goals are:

- **Mimic real gateway behavior** using the Semtech UDP Packet Forwarder protocol.  
- **Simulate multiple LoRaWAN devices** with realistic uplink/downlink flows, frame counters, encryption, and MAC command handling.  
- **Provide a modular design** so that users can easily add features like ADR, confirmed uplinks, OTAA joins, and more.

The system can be deployed in **single-container mode** (gateway + multiple devices in one Docker container) or **multi-container mode** (separate containers for gateway simulation and device simulation).

---

## 2. Architecture

### 2.1 High-Level Components

1. **Gateway**  
   - Simulates the Semtech UDP Packet Forwarder.  
   - Sends uplinks (“rxpk”) to the LoRaWAN Network Server (LNS).  
   - Listens for downlinks (“txpk”) from the LNS.  
   - Forwards inbound downlinks to the correct Device object.

2. **Device**  
   - Holds LoRaWAN-specific state (DevAddr, session keys, frame counters).  
   - Builds encrypted, MIC-validated uplink packets.  
   - Decodes downlink PHYPayloads and handles MAC commands.

3. **DeviceManager** (Optional)  
   - Manages multiple Device instances in one process.  
   - Routes downlinks to the correct device.  
   - Schedules periodic uplinks per device configuration.

4. **Utilities**  
   - Common encryption, MIC calculation, base64 encoding/decoding, and logging helpers.

5. **MAC Commands**  
   - A dedicated module (`mac_commands.py`) for parsing and generating MAC command payloads.  
   - Keeps device logic simpler by offloading command-specific details here.

6. **Main Entry Point** (`main.py`)  
   - Orchestrates the initialization of the Gateway and Devices.  
   - Parses config/environment for runtime parameters.  
   - Starts the main loop or concurrency for sending/receiving messages.

### 2.2 System Architecture Diagram

Below is a conceptual system diagram (ASCII-style) showing how the simulator interacts with ChirpStack and an MQTT broker:
