"""Minimal GoSDK binding via ctypes — enough to stream uniform surfaces + intensity.

ctypes rather than a compiled C shim: the SDK is a plain C API, so a shim would
only add a build step and a second place for bugs (D11).

Layout of one received data set: GoDataSet -> N messages; we want
UNIFORM_SURFACE (int16 heights, 0x8000 invalid) and SURFACE_INTENSITY (uint8),
which arrive as separate messages for the same frame.
"""
from __future__ import annotations

import ctypes as C
import os
from pathlib import Path

import numpy as np

# --- constants from GoSdkDef.h / GoDataTypes.h ---
GO_MODE_SURFACE = 3
MSG_STAMP = 0
MSG_UNIFORM_SURFACE = 8
MSG_SURFACE_INTENSITY = 9
GO_OUTPUT_SOURCE_SURFACE = 4
GO_OUTPUT_SOURCE_SURFACE_INTENSITY = 7
GO_SURFACE_GENERATION_TYPE_CONTINUOUS = 0
GO_SURFACE_GENERATION_TYPE_FIXED_LENGTH = 1
# 600mm matches the Tobetsu field config and, at the sensor's ~890Hz time trigger,
# gives ~3s per surface — enough to sweep an object through the laser line by hand.
SURFACE_LENGTH_MM = float(os.environ.get("GOCATOR_SURFACE_MM", 600.0))
INVALID_16BIT = -32768
kOK = 1
kERROR_TIMEOUT = -993

SDK_ROOT = Path(os.environ.get("GOSDK_ROOT", Path.home() / "gosdk/GO_SDK"))
LIB_DIR = SDK_ROOT / "lib" / os.environ.get("GOSDK_LIBDIR", "linux_arm64")


class GoSdkError(RuntimeError):
    pass


def _check(status: int, what: str) -> None:
    if status != kOK:
        raise GoSdkError(f"{what} failed: kStatus {status}")


class _Lib:
    """Loads libGoSdk/libkApi once and declares the signatures we use."""

    _inst: "_Lib | None" = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
            cls._inst._load()
        return cls._inst

    def _load(self):
        # kApi first: libGoSdk links against it. Keep both handles — kObject_*
        # and kIpAddress_* are exported by kApi only, not by GoSdk.
        ka = C.CDLL(str(LIB_DIR / "libkApi.so"), mode=C.RTLD_GLOBAL)
        go = C.CDLL(str(LIB_DIR / "libGoSdk.so"), mode=C.RTLD_GLOBAL)
        self.go, self.ka = go, ka
        p, u64, i32, u32, sz = C.c_void_p, C.c_uint64, C.c_int32, C.c_uint32, C.c_size_t

        def sig(name, restype, argtypes, lib=go):
            f = getattr(lib, name)
            f.restype, f.argtypes = restype, argtypes
            return f

        self.GoSdk_Construct = sig("GoSdk_Construct", i32, [C.POINTER(p)])
        self.GoSystem_Construct = sig("GoSystem_Construct", i32, [C.POINTER(p), p])
        # no GoSystem_Destroy in the ABI — kApi objects free via kObject_Destroy
        self.GoSystem_FindSensorByIpAddress = sig(
            "GoSystem_FindSensorByIpAddress", i32, [p, p, C.POINTER(p)])
        self.GoSensor_Connect = sig("GoSensor_Connect", i32, [p])
        self.GoSensor_Disconnect = sig("GoSensor_Disconnect", i32, [p])
        self.GoSensor_Setup = sig("GoSensor_Setup", p, [p])
        self.GoSetup_ScanMode = sig("GoSetup_ScanMode", i32, [p])
        self.GoSetup_SetScanMode = sig("GoSetup_SetScanMode", i32, [p, i32])
        self.GoSetup_IntensityEnabled = sig("GoSetup_IntensityEnabled", i32, [p])
        self.GoSetup_EnableIntensity = sig("GoSetup_EnableIntensity", i32, [p, i32])
        self.GoSetup_SurfaceGeneration = sig("GoSetup_SurfaceGeneration", p, [p])
        self.GoSurfaceGeneration_GenerationType = sig(
            "GoSurfaceGeneration_GenerationType", i32, [p])
        self.GoSurfaceGeneration_SetGenerationType = sig(
            "GoSurfaceGeneration_SetGenerationType", i32, [p, i32])
        self.GoSurfaceGenerationFixedLength_Length = sig(
            "GoSurfaceGenerationFixedLength_Length", C.c_double, [p])
        self.GoSurfaceGenerationFixedLength_SetLength = sig(
            "GoSurfaceGenerationFixedLength_SetLength", i32, [p, C.c_double])
        self.GoSensor_Flush = sig("GoSensor_Flush", i32, [p])
        self.GoSensor_Output = sig("GoSensor_Output", p, [p])
        self.GoOutput_Ethernet = sig("GoOutput_Ethernet", p, [p])
        self.GoEthernet_ClearSources = sig("GoEthernet_ClearSources", i32, [p])
        self.GoEthernet_AddSource = sig("GoEthernet_AddSource", i32, [p, i32, i32])
        self.GoEthernet_SourceCount = sig("GoEthernet_SourceCount", sz, [p, i32])
        self.GoSystem_EnableData = sig("GoSystem_EnableData", i32, [p, i32])
        self.GoSystem_Start = sig("GoSystem_Start", i32, [p])
        self.GoSystem_Stop = sig("GoSystem_Stop", i32, [p])
        self.GoSystem_ReceiveData = sig("GoSystem_ReceiveData", i32, [p, C.POINTER(p), u64])
        self.GoDataSet_Count = sig("GoDataSet_Count", sz, [p])
        self.GoDataSet_At = sig("GoDataSet_At", p, [p, sz])
        self.GoDataMsg_Type = sig("GoDataMsg_Type", i32, [p])
        # kObject_Destroy is a header inline over this real export; the second
        # arg is the `destroyChildren` flag (kFALSE for a plain destroy).
        _destroy = sig("xkObject_DestroyImpl", i32, [p, i32], ka)
        self.kObject_Destroy = lambda obj: _destroy(obj, 0) if obj else kOK

        self.GoSurfaceMsg_Length = sig("GoSurfaceMsg_Length", sz, [p])
        self.GoSurfaceMsg_Width = sig("GoSurfaceMsg_Width", sz, [p])
        self.GoSurfaceMsg_RowAt = sig("GoSurfaceMsg_RowAt", C.POINTER(C.c_int16), [p, sz])
        self.GoSurfaceMsg_XResolution = sig("GoSurfaceMsg_XResolution", u32, [p])
        self.GoSurfaceMsg_YResolution = sig("GoSurfaceMsg_YResolution", u32, [p])
        self.GoSurfaceMsg_ZResolution = sig("GoSurfaceMsg_ZResolution", u32, [p])
        self.GoSurfaceMsg_ZOffset = sig("GoSurfaceMsg_ZOffset", i32, [p])

        self.GoSurfaceIntensityMsg_Length = sig("GoSurfaceIntensityMsg_Length", sz, [p])
        self.GoSurfaceIntensityMsg_Width = sig("GoSurfaceIntensityMsg_Width", sz, [p])
        self.GoSurfaceIntensityMsg_RowAt = sig(
            "GoSurfaceIntensityMsg_RowAt", C.POINTER(C.c_uint8), [p, sz])

        self.kIpAddress_Parse = sig("kIpAddress_Parse", i32, [p, C.c_char_p], ka)


class _IpAddress(C.Structure):
    """kIpAddress: version enum + 16 address bytes."""
    _fields_ = [("version", C.c_int32), ("address", C.c_uint8 * 16)]


def _rows_to_array(msg, n_rows, width, row_fn, dtype):
    """Copy SDK-owned row pointers into one owned numpy array.

    The copy is deliberate — the message is destroyed right after, and views
    into freed SDK memory are a segfault waiting to happen.
    """
    out = np.empty((n_rows, width), dtype=dtype)
    itemsize = out.itemsize
    for r in range(n_rows):
        src = row_fn(msg, r)
        C.memmove(out[r].ctypes.data, src, width * itemsize)
    return out


class GocatorStream:
    """Connect, force Surface mode, stream (z16, intensity) frames.

    Usage:
        with GocatorStream("192.168.1.10") as s:
            for z16, inten, meta in s.frames():
                ...
    """

    def __init__(self, ip: str = "192.168.1.10", timeout_us: int = 20_000_000):
        self.ip = ip
        self.timeout_us = timeout_us
        self.lib = _Lib()
        self.system = C.c_void_p()
        self.sensor = C.c_void_p()
        self.meta: dict = {}
        self._started = False

    # --- lifecycle ---
    def open(self) -> "GocatorStream":
        L = self.lib
        assembly = C.c_void_p()
        _check(L.GoSdk_Construct(C.byref(assembly)), "GoSdk_Construct")
        _check(L.GoSystem_Construct(C.byref(self.system), None), "GoSystem_Construct")

        addr = _IpAddress()
        _check(L.kIpAddress_Parse(C.byref(addr), self.ip.encode()), "kIpAddress_Parse")
        _check(L.GoSystem_FindSensorByIpAddress(
            self.system, C.byref(addr), C.byref(self.sensor)), "FindSensorByIpAddress")
        _check(L.GoSensor_Connect(self.sensor), "GoSensor_Connect")

        setup = L.GoSensor_Setup(self.sensor)
        if not setup:
            raise GoSdkError("GoSensor_Setup returned NULL")
        mode = L.GoSetup_ScanMode(setup)
        self.meta["scan_mode_before"] = mode
        dirty = False
        if mode != GO_MODE_SURFACE:
            # The detector needs stacked surfaces; profile mode yields no surface
            # messages at all.
            _check(L.GoSetup_SetScanMode(setup, GO_MODE_SURFACE), "SetScanMode(SURFACE)")
            self.meta["scan_mode_changed"] = True
            dirty = True

        # Intensity acquisition must be on before it can be an output source,
        # otherwise AddSource(SURFACE_INTENSITY) returns kERROR_PARAMETER.
        self.meta["intensity_enabled_before"] = bool(L.GoSetup_IntensityEnabled(setup))
        if not self.meta["intensity_enabled_before"]:
            _check(L.GoSetup_EnableIntensity(setup, 1), "EnableIntensity")
            self.meta["intensity_enabled"] = True
            dirty = True

        # CONTINUOUS generation never finalises a surface, so no surface message
        # is ever emitted and ReceiveData just times out. Fixed-length closes a
        # surface every SURFACE_LENGTH_MM of (time-triggered) travel.
        sgen = L.GoSetup_SurfaceGeneration(setup)
        if sgen:
            gtype = L.GoSurfaceGeneration_GenerationType(sgen)
            self.meta["surface_gen_before"] = gtype
            if gtype != GO_SURFACE_GENERATION_TYPE_FIXED_LENGTH:
                _check(L.GoSurfaceGeneration_SetGenerationType(
                    sgen, GO_SURFACE_GENERATION_TYPE_FIXED_LENGTH), "SetGenerationType")
                dirty = True
            if abs(L.GoSurfaceGenerationFixedLength_Length(sgen) - SURFACE_LENGTH_MM) > 0.5:
                _check(L.GoSurfaceGenerationFixedLength_SetLength(sgen, SURFACE_LENGTH_MM),
                       "SetLength")
                dirty = True
            self.meta["surface_length_mm"] = SURFACE_LENGTH_MM

        # Acquisition settings must reach the sensor before output sources are
        # touched — SURFACE_INTENSITY is only a legal source once intensity
        # acquisition is actually on, else AddSource returns kERROR_PARAMETER.
        if dirty:
            _check(L.GoSensor_Flush(self.sensor), "GoSensor_Flush(setup)")

        # Scan mode alone isn't enough: the Ethernet output keeps its own source
        # list, and while it still carries only Profile the sensor sends nothing
        # we can use and ReceiveData just times out.
        out = L.GoSensor_Output(self.sensor)
        eth = L.GoOutput_Ethernet(out) if out else None
        if eth:
            have_surf = L.GoEthernet_SourceCount(eth, GO_OUTPUT_SOURCE_SURFACE)
            have_int = L.GoEthernet_SourceCount(eth, GO_OUTPUT_SOURCE_SURFACE_INTENSITY)
            self.meta["eth_sources_before"] = {"surface": have_surf, "intensity": have_int}
            added = False
            if not have_surf:
                _check(L.GoEthernet_AddSource(eth, GO_OUTPUT_SOURCE_SURFACE, 0),
                       "AddSource(SURFACE)")
                added = True
            if not have_int:
                # Intensity is not optional — the detector keys on its texture.
                st = L.GoEthernet_AddSource(eth, GO_OUTPUT_SOURCE_SURFACE_INTENSITY, 0)
                if st == kOK:
                    added = True
                else:
                    # Don't sink the whole session: heights still stream, and the
                    # caller sees intensity=None and can say so.
                    self.meta["intensity_source_error"] = st
            if added:
                _check(L.GoSensor_Flush(self.sensor), "GoSensor_Flush(output)")
                self.meta["eth_sources_added"] = True
        return self

    def start(self) -> None:
        # Without EnableData the SDK never opens the data channel and every
        # ReceiveData call times out, even with the sensor running happily.
        _check(self.lib.GoSystem_EnableData(self.system, 1), "GoSystem_EnableData")
        _check(self.lib.GoSystem_Start(self.system), "GoSystem_Start")
        self._started = True

    def stop(self) -> None:
        if self._started:
            self.lib.GoSystem_Stop(self.system)
            self._started = False

    def close(self) -> None:
        self.stop()
        if self.sensor:
            self.lib.GoSensor_Disconnect(self.sensor)
            self.sensor = C.c_void_p()
        if self.system:
            self.lib.kObject_Destroy(self.system)
            self.system = C.c_void_p()

    def __enter__(self):
        self.open()
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # --- data ---
    def frames(self):
        """Yield (z16, intensity, meta) per surface. intensity is None if the
        sensor isn't configured to send it."""
        L = self.lib
        while True:
            dataset = C.c_void_p()
            st = L.GoSystem_ReceiveData(self.system, C.byref(dataset), self.timeout_us)
            if st != kOK:
                raise GoSdkError(f"GoSystem_ReceiveData failed: kStatus {st}")
            try:
                z16 = inten = None
                meta = dict(self.meta)
                for i in range(L.GoDataSet_Count(dataset)):
                    msg = L.GoDataSet_At(dataset, i)
                    t = L.GoDataMsg_Type(msg)
                    if t == MSG_UNIFORM_SURFACE:
                        h, w = L.GoSurfaceMsg_Length(msg), L.GoSurfaceMsg_Width(msg)
                        z16 = _rows_to_array(msg, h, w, L.GoSurfaceMsg_RowAt, np.int16)
                        meta |= {
                            "x_res_nm": L.GoSurfaceMsg_XResolution(msg),
                            "y_res_nm": L.GoSurfaceMsg_YResolution(msg),
                            "z_res_nm": L.GoSurfaceMsg_ZResolution(msg),
                            "z_offset_um": L.GoSurfaceMsg_ZOffset(msg),
                        }
                    elif t == MSG_SURFACE_INTENSITY:
                        h = L.GoSurfaceIntensityMsg_Length(msg)
                        w = L.GoSurfaceIntensityMsg_Width(msg)
                        inten = _rows_to_array(
                            msg, h, w, L.GoSurfaceIntensityMsg_RowAt, np.uint8)
                if z16 is not None:
                    yield z16, inten, meta
            finally:
                L.kObject_Destroy(dataset)


if __name__ == "__main__":
    import sys
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.10"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    with GocatorStream(ip) as s:
        print(f"connected to {ip}; mode before = {s.meta.get('scan_mode_before')}, "
              f"changed = {s.meta.get('scan_mode_changed', False)}")
        for i, (z16, inten, meta) in enumerate(s.frames()):
            valid = (z16 != INVALID_16BIT).mean()
            print(f"frame {i}: z16 {z16.shape} valid={valid:.1%} "
                  f"intensity={'none' if inten is None else inten.shape} "
                  f"x_res={meta['x_res_nm']/1e6:.4f}mm y_res={meta['y_res_nm']/1e6:.4f}mm")
            if i + 1 >= n:
                break
    print("ok")
