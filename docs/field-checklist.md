# Field checklist — Jetson + Gocator

For a site visit without a laptop-deep debug session. Dashboard: **http://192.168.23.101:8000**

## Before you leave

- [ ] `curl -s http://192.168.23.101:8000/api/health` returns JSON with `sensor_reachable: true`
- [ ] Disk: `disk_free_gb` in that response. A pass costs **~13 MB per surface**, one surface
      every ~4 s, so roughly **11 GB/hour**. Recording stops at 5 GB free.
- [ ] Clock: `ssh jetson-lab-local date`. There is no NTP at the site, so if it is wrong,
      every session you record is stamped wrong. Fix before travelling:
      ```bash
      ssh jetson-lab-local "sudo date -u -s '$(date -u '+%Y-%m-%d %H:%M:%S')'; sudo hwclock -w -f /dev/rtc0; sudo hwclock -w -f /dev/rtc1"
      ```
- [ ] Bring calipers and plant tags. See "what to bring back".

## Power-on order

1. Sensor first, give it ~30 s.
2. Jetson. The container is `--restart unless-stopped`, so the dashboard comes back by itself.
3. Open **Control**. Healthy looks like:
   - Sensor: `reachable` green, ports control/data/web open
   - This machine: model `sunflower_curated_yolov8n.pt`, gpu `Orin`
   - `retired: sunflower_curated_yolov8n.onnx` is **normal** — the ONNX is skipped because
     this box has no onnxruntime, and the `.pt` is used instead.

## Running a pass

Live tab → start a live session. Leave `fps` alone; live ignores it, the sensor sets the rate.

While it runs, health should show `connected: true` and `frames_done` climbing about once
every 4 s.

## If something looks wrong

| symptom | cause | fix |
|---|---|---|
| `sensor_reachable: false` | cable, sensor power, or the eth0 alias | `ssh jetson-lab-local "ip -4 -br addr show eth0"` — needs **both** 192.168.23.101 and 192.168.1.20. Re-add: `sudo ip addr add 192.168.1.20/24 dev eth0` |
| session shows `reconnecting (attempt N)` | link dropped | It recovers on its own. Frames already recorded are safe. Only intervene if it never reconnects. |
| session state `error` | something other than a link drop | `docker logs gocator-poc \| tail -40` |
| dashboard not loading | container | `docker ps`, then `docker start gocator-poc` |
| `heads_found` stays 0 with heads in frame | detection, not plumbing | Record anyway — the raw frames are what matter. Lower conf on the Control tab and note it. |

**Whatever happens, the raw frames hit disk before detection runs.** A detector problem never
costs field data. Do not stop a pass because detections look wrong.

## What to bring back

Both of these close out questions that are currently unanswerable:

1. **Caliper measurements with plant tags.** 20-30 pairs is enough to turn every accuracy
   number from unvalidated into characterised. Enter them against the session in the UI, or
   just write them down with the tag and the session id.
2. **At least one pass with real heads in frame.** The detector was trained on the Tobetsu
   recording, whose field of view is narrower than this sensor's — live heads reach the
   network about **27% smaller** than anything it was trained on. One real recording settles
   whether that matters and provides live-geometry training data.

Sessions live in `/data/gocator-poc/data/sessions/` on the Jetson. Nothing is deleted
automatically.
