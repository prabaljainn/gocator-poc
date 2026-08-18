# DGX Spark ⇄ Gocator Setup Runbook

**Status: bench verified 2026-08-19.** Network, environment, and detector are confirmed working on the Spark. Only GoSDK remains (needs an LMI download — see Phase 4). Diagram: [diagrams/network-setup.png](diagrams/network-setup.png).

## Verified facts (measured, not assumed)

| Thing | Value | How verified |
|---|---|---|
| Spark host | `spark-lab-local` · `spark-4faa` · Ubuntu 24.04.4 · aarch64 | `ssh spark-lab-local` |
| Spark wired iface | `enP7s7` = **192.168.1.3/24**, gigabit, link up | `ip -br addr`, `ethtool` |
| Spark Wi-Fi | `wlP9s9` = 192.168.3.241 (internet + SSH) | same |
| Gocator | **192.168.1.10**, ping 0.6 ms, 0 % loss | `ping`, `curl` |
| Gocator ports | 80 (web), 3190 (control), 3192 (upgrade), 3196 (data) — **all open** | TCP connect probe |
| Toolchain | gcc 13.3, make 4.3, cmake 3.28, python 3.12, git 2.43 | `--version` |
| Disk | 3.5 TB free (`/dev/nvme0n1p2`) | `df -h` |
| **Detector on ARM64** | `selftest ok: 199.4mm vs 200.0mm (0.3% err)` | `detect.py --selftest` on the Spark |

No network reconfiguration was needed — DHCP already placed the Spark on the sensor's subnet.

## What is already done on the Spark

```
~/gocator-poc/            # repo (rsync'd, minus .rec/.venv/out)
~/gocator-poc/.venv/      # numpy scipy opencv-python-headless pillow
                          # fastapi uvicorn[standard] zstandard
```
Detector selftest passes. The CPU pipeline is proven on target hardware.

## Everyday commands

```bash
ssh spark-lab-local                                    # in
cd ~/gocator-poc && .venv/bin/python detect.py --selftest

# push local code changes to the Spark
rsync -az --exclude .venv --exclude out --exclude '*.rec' --exclude .git \
  ~/Repos/Gocator-poc/ spark-lab-local:~/gocator-poc/

# health check (network + sensor + env), from the Mac
ssh spark-lab-local 'bash ~/gocator-poc/scripts/check-sensor.sh'
```

## Phase 4 — GoSDK (the one remaining blocker)

The sensor is reachable and its data channel (3196) accepts connections, but it stays silent until a client speaks the Gocator control protocol on 3190. That protocol is what GoSDK implements.

**What prabal needs to do (once):**
1. Log in at LMI's download centre (same account as the firmware) → **GO_SDK**, version matching the sensor firmware (check it in the web UI at `http://192.168.1.10` → Manage → System).
2. Drop the zip anywhere on the Mac, then: `scp GO_SDK*.zip spark-lab-local:~/`

**Then (I can run this):**
```bash
unzip ~/GO_SDK*.zip -d ~/gosdk && cd ~/gosdk/GO_SDK
make -f Platform/kApi/kApi-Linux_Arm64.mk        # kApi first
make -f Gocator/GoSdk/GoSdk-Linux_Arm64.mk       # then GoSdk
# → lib/linux_arm64/libGoSdk.so + libkApi.so
```
First-light proof, before any of our code: build and run the SDK's `ReceiveSurface` sample against `192.168.1.10` — a printed surface size (~3389 × 4033) confirms the whole sensor → Spark data path.

> Note: `Emulator and Accelerator.zip` in the repo is **Windows tooling, not the SDK** — it can't build here.

## Phase 5 — Our stack (after the SDK lands)

```bash
make -C ~/gocator-poc/backend/app/acquisition GOSDK=~/gosdk/GO_SDK   # C shim
cd ~/gocator-poc && .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```
Dashboard from the Mac: **http://192.168.1.3:8000** (note `.3`, not `.5` — DHCP's assignment). systemd unit only after first light.

Frontend dev loop (on the Mac): `npm run dev`, Vite proxies `/api` + `/ws` to `192.168.1.3:8000`.

## First-light checklist

| # | Step | Proves | Status |
|---|---|---|---|
| 1 | Mac browser opens `http://192.168.1.10` | sensor alive, wiring right | ✅ done |
| 2 | Spark pings + curls the sensor | Spark network path | ✅ done |
| 3 | `detect.py --selftest` on Spark | pipeline runs on ARM64 | ✅ done |
| 4 | SDK sample receives one surface | GoSDK build + data channel | ⬜ needs SDK |
| 5 | Backend + `FakeLiveSource` session | pipeline + WS + UI, **no sensor risk** | ⬜ next build |
| 6 | Live session, hand under the laser | end-to-end laser → dashboard | ⬜ |

The trigger is time-based (~994 Hz, fixed 600 mm surfaces), so surfaces complete every ~3.4 s even on a static bench — step 6 works indoors with no motion.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Sensor not at `.10` | field IP change → SDK discovery (UDP 3220), or `arp -a` after power cycle |
| Web UI fine, SDK gets no data | Ethernet output off / accelerator paired → web UI: Output → Ethernet → enable Gocator protocol + Surface + Surface Intensity; unpair accelerator |
| `curl` returns 406 / "Item encoding not supported" | **not an error** — the sensor's web server rejects curl's default headers; use `--compressed -H 'User-Agent: Mozilla/5.0'` |
| Frames slow / gapped | 100 Mb link → `ethtool enP7s7` must say 1000Mb/s |
| SDK build fails | wrong platform makefile → use `Linux_Arm64`; build kApi before GoSdk |
| Dashboard unreachable from Mac | bind `--host 0.0.0.0`; check `sudo ufw status` |
| Spark wired IP changed | DHCP renewal → re-check `ip -br addr`, or pin it: `sudo nmcli con mod <con> ipv4.method manual ipv4.addresses 192.168.1.3/24` |

## Deployed (2026-08-19)

The service runs on the Spark as a systemd **user** unit and serves both API and UI:

```bash
ssh spark-lab-local systemctl --user status gocator      # state
ssh spark-lab-local systemctl --user restart gocator     # after a code change
ssh spark-lab-local journalctl --user -u gocator -f      # logs
```

**Dashboard: http://192.168.1.3:8000** — open it from the Mac or a phone on the same switch.

Deploy a change from the Mac:
```bash
rsync -az --exclude .venv --exclude out --exclude '*.rec' --exclude .git \
  --exclude node_modules --exclude data ~/Repos/Gocator-poc/ spark-lab-local:~/gocator-poc/
ssh spark-lab-local 'export PATH=$HOME/.local/node/bin:$PATH; cd ~/gocator-poc/frontend && npm run build'
ssh spark-lab-local systemctl --user restart gocator
```

Notes:
- Node 22 is installed at `~/.local/node` (Ubuntu's Node 18 is too old for Vite 8; no sudo was needed).
- SSH pins `IdentityFile ~/.ssh/id_ed25519` + `IdentitiesOnly yes` in `~/.ssh/config`; without it the agent offers every key and trips the server's `MaxAuthTries`.
- If the service should survive logout, run `sudo loginctl enable-linger prabal` once.

**Verified on the Spark:** backend selftest passes, and a full replay of the Tobetsu recording produced **42 frames → 55 heads**, identical to the Mac. Detection throughput is noticeably faster than the MacBook.
