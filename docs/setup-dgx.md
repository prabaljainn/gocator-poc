# DGX Spark ⇄ Gocator Setup Runbook

Goal: DGX Spark receives the live surface stream from the Gocator over the switch; the dashboard is opened from the Mac's browser. Diagram: [diagrams/network-setup.png](diagrams/network-setup.png).

## Addressing plan

Everything wired sits on one L2 segment through the switch (Gocator = port 5, DGX = port 4, Mac = any free port). Internet stays on Wi-Fi for Mac and DGX — the wired interfaces get static IPs and **no gateway**, so default routes are untouched.

| Device | Wired IP | Notes |
|---|---|---|
| Gocator 2690 | `192.168.1.10` | LMI factory default. If it doesn't answer, see Troubleshooting. |
| DGX Spark | `192.168.1.5/24` | static, no gateway (internet via Wi-Fi) |
| MacBook | `192.168.1.7/24` | static, no gateway (internet via Wi-Fi) |
| Dashboard | `http://192.168.1.5:8000` | FastAPI on the DGX, opened from the Mac |

Bandwidth check: one surface = ~41 MB every ~3.4 s ≈ 100 Mbit/s sustained — fine on gigabit, will choke on a 100 Mb port. The switch must be gigabit.

## Phase 1 — Physical

1. Gocator on switch port 5, DGX on port 4, Mac on any free port. Power the Gocator (same 24–48 VDC supply used in the field).
2. Link lights on all three ports.

## Phase 2 — Mac: talk to the sensor (5 min, do this first)

System Settings → Network → the wired adapter → Details → TCP/IP → Configure IPv4: **Manually** → IP `192.168.1.7`, mask `255.255.255.0`, router **empty**.

Verify:
```bash
ping -c 3 192.168.1.10          # sensor answers
open http://192.168.1.10        # Gocator web UI loads
```
In the web UI note the **firmware version** (Manage → System) — the GoSDK build must match its major.minor.

## Phase 3 — DGX: wired interface (over SSH)

```bash
nmcli device status                       # find the wired iface name (enP…/eth…)
sudo nmcli con add type ethernet ifname <IFACE> con-name gocator-lan \
  ipv4.method manual ipv4.addresses 192.168.1.5/24     # deliberately no gateway
sudo nmcli con up gocator-lan
ping -c 3 192.168.1.10                    # sensor visible from the DGX
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.10   # expect 200
```
Also confirm no firewall in the way: `sudo ufw status` (expect inactive; if active, allow from `192.168.1.0/24` and open `8000`).

## Phase 4 — GoSDK on the DGX

1. Get the **GO_SDK** package matching the sensor firmware (LMI download center — same place the firmware came from; the `Emulator and Accelerator/` folder in this repo is the Windows tooling, not the SDK). Unzip on the DGX.
2. Build the Linux **ARM64** targets: `kApi` first, then `GoSdk` (makefiles ship in the zip). Output: `libGoSdk.so` + headers.
3. First-frame proof using an SDK sample (e.g. the receive-surface example) pointed at `192.168.1.10` — a printed surface size (`3389 × 4033`-ish) proves the entire sensor→DGX data path before any of our code runs.

## Phase 5 — Our stack on the DGX

1. Repo onto the DGX (git pull, or `rsync -av --exclude .venv --exclude out ~/Repos/Gocator-poc/ dgx:~/gocator-poc/` from the Mac).
2. `python3 -m venv .venv && .venv/bin/pip install numpy scipy opencv-python-headless pillow fastapi uvicorn zstandard`
3. Sanity: `.venv/bin/python detect.py --selftest` (the detector core is pure CPU — identical behavior on ARM64).
4. Build the C shim against the SDK: `make -C backend/app/acquisition GOSDK=/path/to/GO_SDK`.
5. Run: `.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`. systemd unit comes after first light, not before.

## Phase 6 — Dashboard

- **Field/normal use**: DGX serves the built React bundle — Mac browser → `http://192.168.1.5:8000`. Nothing runs on the Mac.
- **Development**: `npm run dev` on the Mac (Vite on `localhost:5173`, proxying `/api` and `/ws` to `192.168.1.5:8000`) — hot reload against the live backend.

## First-light checklist (in order, each step proves one thing)

| # | Action | Proves |
|---|---|---|
| 1 | Mac browser opens sensor web UI | sensor alive, network wiring correct |
| 2 | DGX pings + curls sensor | DGX wired config correct |
| 3 | SDK sample receives one surface | GoSDK build + data channel work |
| 4 | Sensor in Run mode, shim test prints frame stamps | our C shim works |
| 5 | Backend up, `FakeLiveSource` session from a recorded frame set | pipeline + WS + UI work with **no sensor risk** |
| 6 | Live session, hand/target moved under the laser on the bench | end-to-end: laser → dashboard |

Bench note: the trigger is time-based, so surfaces complete every ~3.4 s even with nothing moving — a static bench scene still streams, which is perfect for step 6.

## Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| `192.168.1.10` doesn't answer | IP was changed for the field setup → run SDK discovery from the DGX (broadcasts on UDP 3220), or check the sensor via `arp -a` after power-cycling; worst case, sensor label + LMI recovery tool |
| Web UI loads but SDK gets no data | Ethernet output disabled or sensor paired to an accelerator → web UI: Output → Ethernet → enable Gocator protocol, Surface + Surface Intensity; unpair any accelerator |
| Frames arrive but slowly / gaps | 100 Mb link somewhere → check switch port LEDs / `ethtool <IFACE>` shows 1000 Mb |
| SDK build fails on ARM64 | building the x64 makefile by mistake → use the `Arm64` platform makefiles; kApi before GoSdk |
| Dashboard unreachable from Mac | backend bound to localhost → `--host 0.0.0.0`; or ufw active on DGX |
| Two devices fight over an IP | someone left DHCP on the segment → keep the switch isolated: only these three devices on it |
