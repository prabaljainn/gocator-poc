# Talking to the Gocator 2690 — verified endpoint reference

Everything here was probed against the live sensor at `192.168.1.10` from the Spark on 2026-08-19. Nothing is guessed; failures are recorded as failures. Undocumented by LMI — this is reverse-engineered from the sensor's own web bundle (`main.41ff6d09.js`), so treat it as firmware-version-specific.

## Ports

| Port | Protocol | State | Purpose |
|---|---|---|---|
| 80 | HTTP + WebSocket | open | web UI, `command.cgi`, `/ws/*` |
| 3190 | Gocator control | open | GoSDK control channel |
| 3192 | Gocator upgrade | open | firmware |
| 3196 | Gocator data | open | **surface/profile stream** — accepts TCP but stays silent until a client speaks the control protocol (GoSDK) |
| 3220/udp | discovery | — | sensor discovery broadcast |

## HTTP quirk (costs an hour if you don't know it)

`curl` gets `HTTP 406` / `Item encoding not supported` from this server unless you send browser-ish headers. **Not a fault:**

```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' http://192.168.1.10/
```

## `command.cgi` — HTTP command endpoint

`GET http://192.168.1.10/command.cgi?id=<ID>[&extra=...]` → JSON `{"id": N, "status": S}` or a binary body for downloads. `status: 1` = OK; `status: -998` = missing/invalid parameters (several IDs need params we haven't mapped).

Command IDs extracted from the web bundle:

| ID | Name | Notes |
|---|---|---|
| 0 | firmware upgrade | POST upload, `&skipValidation=1` |
| 4097 | — | |
| 4100 | `SET_MODE` | needs params |
| 4101 | `GET_MODE` | returned `-998` bare — needs params |
| 4102 | — | |
| **4103** | **file download** | **verified working** — see below |
| 4104, 4106, 4109 | — | |
| 4110 | `PING` | returned `-998` bare |
| 4115 | — | |
| 4116 | restore backup | POST upload of `.bak` |
| 4122, 4123 | — | |
| 4124 | `GET_ENCODER` | |
| 4125 | — | |
| 4126 | `RESET_ENCODER` | |
| 4127, 4128 | — | |
| 4352 | `GET_PROTOCOL_VERSION_CONTROL` | |

### Downloading the live recording buffer — **verified, gives real data with no SDK**

```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' \
  -o live.rec \
  'http://192.168.1.10/command.cgi?id=4103&download=true&fileName=_live.rec'
```

Returns `HTTP 200`, `Content-Type: application/octet-stream`, `Content-Disposition: attachment; filename="_live.rec"`, chunked. **Measured: 164 MB** while the sensor was recording — the same kDat6 container as a saved `.rec`, so [`rec_reader.py`](../rec_reader.py) parses it unchanged.

This is a genuine sensor→disk→pipeline path that needs no SDK. Its ceiling: it is a *buffer download*, not a stream — you get history, not frames as they complete, and a big buffer takes tens of seconds to transfer (allow a generous `--max-time`; 30 s was not enough for 164 MB).

## WebSockets — `ws://192.168.1.10/ws/<channel>`

**Subprotocol `binary` is mandatory** (`new WebSocket(url, ["binary"])`, `binaryType = "arraybuffer"`). Without it the server answers `NegotiationError: no subprotocols supported`.

```python
websockets.connect("ws://192.168.1.10/ws/health", subprotocols=["binary"])
```

| Channel | Verified | Behaviour |
|---|---|---|
| `/ws/health` | ✅ **streaming live** | 5 messages / 7.3 KB in an 8 s probe, binary frames. Sensor telemetry. |
| `/ws/control` | ✅ connects | Silent until the client sends a command; command framing not yet mapped. |
| `/ws/data`, `/ws/stream`, `/ws/log`, `/ws/status` | ❌ | HTTP 404 — not channels |
| `/ws/` (bare) | ❌ | HTTP 200, not a WebSocket |

Health frame sample (first 48 bytes):
```
ae05000000805a00000000000000274e00000000000000000000000000001252...
```
Little-endian u32 counters/IDs with 64-bit values — consistent with kApi health indicator records. Not yet fully decoded.

## Other paths in the web bundle

`/index.html`, `/visualizer.html`, `/empty.html`, `/info.xml`, `/definitions/GlobalBuildDefinitions.json`, `/ftu/manifest.xml`, `/assets/GocatorEip.zip`, `/assets/GSD.zip`, `/images/`.

## How to get surface data — three routes, honestly compared

| Route | Live? | Needs SDK | Status |
|---|---|---|---|
| **GoSDK on TCP 3196** | ✅ true streaming, frame-by-frame | yes (LMI download, ARM64 build) | the supported path; [setup-dgx.md](setup-dgx.md) Phase 4 |
| **`command.cgi` buffer download** | ❌ history, not a stream | **no** | ✅ verified working today — 164 MB pulled |
| **Reverse-engineer `/ws/control`** | ✅ probably (it feeds the browser's live view) | no | unmapped command framing; undocumented and firmware-fragile |

For the live pipeline, GoSDK on 3196 is the one to build on: it is documented, stable across firmware, and delivers frames as they complete. The `command.cgi` download is what unblocks *development with real data* right now, and stays useful as a field backup.

## Reproducing this reference

The sensor serves its own UI bundle; that is where the constants live:
```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' \
  http://192.168.1.10/main.41ff6d09.js -o main.js     # ~2.7 MB, minified
grep -oE '[A-Za-z_$][A-Za-z0-9_$]*=4[0-9]{3}\b' main.js | sort -u -t= -k2 -n
grep -oE 'SUBPROTOCOL="[^"]+"' main.js
```
The bundle hash changes with firmware — re-read `index.html` for the current filename.

## Sensor output configuration (web UI: Output → Ethernet)

Observed on the bench sensor 2026-08-19:

- **Protocol: `Gocator`** ✅ — the TCP control+data protocol GoSDK speaks. Correct setting; leave it.
- **Auto Disconnect: on, 10 s** — the sensor drops a client that stops reading for 10 s. Our acquisition loop must keep draining the socket; a slow detector must never back-pressure the receive path (it doesn't: detection runs on a separate worker off a queue).
- **Data → Profiles → `Top` (checked)**, Events → Exposure End (unchecked).

⚠️ **`Profiles` means the sensor is in Profile mode, not Surface mode.** A profile is a single laser cross-section; our detector needs **Surfaces** (the stacked 2D heightmap + intensity, `GvSurfaceMsg`), which is what the Tobetsu `.rec` contains.

To stream what the pipeline expects: web UI → **Scan → Mode → Surface** (with the fixed-length 600 mm setting used in the field), then re-check **Output → Ethernet → Data**, which will then offer **Surfaces** and **Surface Intensity** — both must be checked. Intensity is not optional here: the detector keys entirely on the intensity texture map.
