"""Sensor + system control panel API.

Reads and writes the Gocator's live configuration through GoSDK, and reports what
this machine is actually running. Deliberately narrow: only the settings the
pipeline depends on are writable, because GocatorStream.open() would otherwise
fight whatever is set here.
"""
from __future__ import annotations

import os
import platform
import socket
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import ml_detector

router = APIRouter(prefix="/api/sensor", tags=["sensor"])

REPO = Path(__file__).resolve().parents[2]
SENSOR_IP = os.environ.get("GOCATOR_SENSOR", "192.168.1.10")
PORTS = {"control": 3190, "upgrade": 3192, "data": 3196, "web": 80}

# A live session owns the sensor connection; a second one is asking for trouble.
_busy = lambda: None  # replaced by main.py with a callable returning the runner


def set_busy_check(fn):
    global _busy
    _busy = fn


def _tcp(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout):
            return True
    except OSError:
        return False


_reach = {"t": 0.0, "ok": False}


def reachable(ttl: float = 5.0) -> bool:
    """Cheap cached TCP probe. /api/health is polled every couple of seconds, so
    this must not open a socket every time."""
    now = time.time()
    if now - _reach["t"] > ttl:
        _reach["t"] = now
        _reach["ok"] = _tcp(SENSOR_IP, PORTS["control"], timeout=1.0)
    return _reach["ok"]


@router.get("/status")
def status():
    """Cheap reachability probe — no SDK, safe while a session is streaming."""
    ports = {name: _tcp(SENSOR_IP, p) for name, p in PORTS.items()}
    return {
        "ip": SENSOR_IP,
        "ports": ports,
        "reachable": any(ports.values()),
        "streaming": bool(_busy()),
    }


def _connected_sensor():
    """Connect read-only. Caller must close via _release."""
    import ctypes as C
    from . import gosdk as G

    L = G._Lib()
    assembly = C.c_void_p()
    system = C.c_void_p()
    sensor = C.c_void_p()
    G._check(L.GoSdk_Construct(C.byref(assembly)), "GoSdk_Construct")
    G._check(L.GoSystem_Construct(C.byref(system), None), "GoSystem_Construct")
    addr = G._IpAddress()
    G._check(L.kIpAddress_Parse(C.byref(addr), SENSOR_IP.encode()), "kIpAddress_Parse")
    G._check(L.GoSystem_FindSensorByIpAddress(system, C.byref(addr), C.byref(sensor)),
             "FindSensorByIpAddress")
    G._check(L.GoSensor_Connect(sensor), "GoSensor_Connect")
    return L, G, system, sensor


def _release(L, system, sensor):
    try:
        L.GoSensor_Disconnect(sensor)
        L.kObject_Destroy(system)
    except Exception:
        pass


def _read_config(L, G, sensor) -> dict:
    setup = L.GoSensor_Setup(sensor)
    cfg = {
        "scan_mode": L.GoSetup_ScanMode(setup),
        "scan_mode_is_surface": L.GoSetup_ScanMode(setup) == G.GO_MODE_SURFACE,
        "intensity_enabled": bool(L.GoSetup_IntensityEnabled(setup)),
    }
    sgen = L.GoSetup_SurfaceGeneration(setup)
    if sgen:
        gt = L.GoSurfaceGeneration_GenerationType(sgen)
        cfg["generation_type"] = gt
        cfg["is_fixed_length"] = gt == G.GO_SURFACE_GENERATION_TYPE_FIXED_LENGTH
        cfg["fixed_length_mm"] = round(L.GoSurfaceGenerationFixedLength_Length(sgen), 3)
    out = L.GoSensor_Output(sensor)
    eth = L.GoOutput_Ethernet(out) if out else None
    if eth:
        cfg["eth_source_surface"] = L.GoEthernet_SourceCount(eth, G.GO_OUTPUT_SOURCE_SURFACE)
        cfg["eth_source_intensity"] = L.GoEthernet_SourceCount(
            eth, G.GO_OUTPUT_SOURCE_SURFACE_INTENSITY)
    return cfg


@router.get("/config")
def get_config():
    """Live read over GoSDK. Takes ~1.5 s — it opens a real connection."""
    if _busy():
        raise HTTPException(409, "a session is streaming; stop it before reading config")
    try:
        L, G, system, sensor = _connected_sensor()
    except Exception as e:
        raise HTTPException(503, f"cannot reach sensor: {type(e).__name__}: {e}")
    try:
        return {"ip": SENSOR_IP, "config": _read_config(L, G, sensor)}
    finally:
        _release(L, system, sensor)


class ConfigPatch(BaseModel):
    intensity_enabled: Optional[bool] = None
    fixed_length_mm: Optional[float] = None
    scan_mode_surface: Optional[bool] = None


@router.post("/config")
def set_config(patch: ConfigPatch):
    """Write settings and flush. Only the three the pipeline actually depends on."""
    if _busy():
        raise HTTPException(409, "a session is streaming; stop it before changing config")
    try:
        L, G, system, sensor = _connected_sensor()
    except Exception as e:
        raise HTTPException(503, f"cannot reach sensor: {type(e).__name__}: {e}")
    try:
        before = _read_config(L, G, sensor)
        setup = L.GoSensor_Setup(sensor)
        changed = []

        if patch.scan_mode_surface is not None and patch.scan_mode_surface:
            if L.GoSetup_ScanMode(setup) != G.GO_MODE_SURFACE:
                G._check(L.GoSetup_SetScanMode(setup, G.GO_MODE_SURFACE), "SetScanMode")
                changed.append("scan_mode -> surface")

        if patch.intensity_enabled is not None:
            if bool(L.GoSetup_IntensityEnabled(setup)) != patch.intensity_enabled:
                G._check(L.GoSetup_EnableIntensity(setup, int(patch.intensity_enabled)),
                         "EnableIntensity")
                changed.append(f"intensity -> {patch.intensity_enabled}")

        if patch.fixed_length_mm is not None:
            if not (10.0 <= patch.fixed_length_mm <= 5000.0):
                raise HTTPException(400, "fixed_length_mm must be 10-5000")
            sgen = L.GoSetup_SurfaceGeneration(setup)
            if not sgen:
                raise HTTPException(400, "sensor exposes no surface generation")
            if abs(L.GoSurfaceGenerationFixedLength_Length(sgen) - patch.fixed_length_mm) > 0.01:
                G._check(L.GoSurfaceGenerationFixedLength_SetLength(
                    sgen, patch.fixed_length_mm), "SetLength")
                changed.append(f"fixed_length_mm -> {patch.fixed_length_mm}")

        if changed:
            G._check(L.GoSensor_Flush(sensor), "GoSensor_Flush")
        return {"changed": changed, "before": before, "after": _read_config(L, G, sensor)}
    finally:
        _release(L, system, sensor)


@router.get("/system")
def system_info():
    """What this box is actually running — the half of 'tuning' that isn't the sensor."""
    info = {
        "host": platform.node(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "detector_conf": ml_detector.CONF_THR,
        "model": None,
        "model_task": None,
        "retired_models": [p.name for p in ml_detector._RETIRED],
    }
    m = ml_detector._MODEL
    if m is not None:
        info["model"] = Path(str(getattr(m, "ckpt_path", "") or "")).name or "?"
        info["model_task"] = getattr(m, "task", None)
    if ml_detector._MODEL_PATH is not None:
        info["model"] = ml_detector._MODEL_PATH.name
    for mod, key in (("torch", "torch"), ("ultralytics", "ultralytics"),
                     ("cv2", "opencv"), ("numpy", "numpy")):
        try:
            info[key] = __import__(mod).__version__
        except Exception:
            info[key] = None
    try:
        import torch
        info["cuda"] = torch.cuda.is_available()
        info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:
        info["cuda"], info["gpu"] = False, None
    return info


class DetectorPatch(BaseModel):
    conf: float


@router.post("/detector")
def set_detector(p: DetectorPatch):
    """Detection confidence threshold — the one knob worth turning from the UI."""
    if not (0.01 <= p.conf <= 0.95):
        raise HTTPException(400, "conf must be between 0.01 and 0.95")
    ml_detector.CONF_THR = float(p.conf)
    return {"detector_conf": ml_detector.CONF_THR}
