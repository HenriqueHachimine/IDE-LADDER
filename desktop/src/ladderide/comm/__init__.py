"""Comunicacao com o dispositivo (protocolo LDP)."""
from .client import CommError, DeviceClient, DeviceError, DownloadResult
from .protocol import Cmd, DevState, Fault, ProtoError
from .snapshot import DeviceInfo, DeviceStatus, Snapshot
from .transport import (ProcessTransport, SerialTransport, TcpTransport, Transport, TransportError,
                        list_serial_ports)

__all__ = ["CommError", "DeviceClient", "DeviceError", "DownloadResult", "Cmd", "DevState", "Fault",
           "ProtoError", "DeviceInfo", "DeviceStatus", "Snapshot", "ProcessTransport", "SerialTransport",
           "TcpTransport", "Transport", "TransportError", "list_serial_ports"]
