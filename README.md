# Echo Kiosk Offline Updates for Home Assistant

Home Assistant integration that mirrors the [LineageOS Echo Kiosk Satellite](https://github.com/jxlarrea/lineageos-echo-kiosk-satellite) device images (and, optionally, [Kiosk Satellite](https://github.com/jxlarrea/kiosk-satellite) APKs) from GitHub into Home Assistant's own web server — so LineageOS Echo devices and kiosks on a network **without internet access** update from Home Assistant instead of GitHub.

Implements the exact flow described in upstream docs:
[offline-updates.md](https://github.com/jxlarrea/lineageos-echo-kiosk-satellite/blob/main/docs/offline-updates.md) (images) and
[kiosk-satellite custom repository](https://github.com/jxlarrea/kiosk-satellite/blob/main/docs/updates.md#custom-repository) (APKs), sharing one folder.

## What it does

Each check (default every 6 h, plus after every Home Assistant restart):

1. Fetches the release list for the image repo (default `jxlarrea/lineageos-echo-kiosk-satellite`).
2. Saves it as `echo-releases.json` in `<config>/www/echo-updates/` with every download link rewritten to point at Home Assistant (`/local/echo-updates/…`) — the same rewrite the upstream mirror script does with `sed`.
3. Downloads the newest release **zip + `.zip.sig`** for each device codename you configure. Files land under the names GitHub gives them; a release without its signature does not install, so both are mirrored.
4. Optionally fetches the release list for Kiosk Satellite (default `jxlarrea/kiosk-satellite`), saves it as `releases.json` in the same folder, and mirrors the newest APKs (`kiosk-satellite-<tag>.apk` universal plus per-ABI) — Kiosk Satellite's **Custom Repository** reads exactly this list.
5. Prunes older zips/APKs — devices only ever download the newest release — and skips re-downloading files it already has at the right size.

Entities & services:

- `sensor.*_mirror_status` — `ok` / `warning` (a check failed but the last good mirror is being served) / `error`, with last-sync time, folder and upstream errors in attributes. Survives failed checks: nothing on disk is deleted while a check fails.
- One sensor per device codename + one for Kiosk Satellite: mirrored version, file, size and local download URL.
- `echo_offline_updates.sync` — check GitHub now.
- `echo_offline_updates.adb_commands` — response-only service; returns the ready-made commands for pointing each device at the folder, with your URLs filled in.

## Install with HACS

1. In HACS: **⋮ → Custom repositories**, paste `https://github.com/kevingailey/ha-echo-offline-updates`, set category **Integration**.
2. Install **Echo Kiosk Offline Updates**, restart Home Assistant.
3. **Settings → Devices & services → Add integration → Echo Kiosk Offline Updates**.

## Configuration

| Field | Default | Notes |
| --- | --- | --- |
| GitHub repository with the device images | `jxlarrea/lineageos-echo-kiosk-satellite` | Change to a fork if you build your own images. |
| Base URL the devices use to reach Home Assistant | `http://homeassistant.local:8123/local/echo-updates` | Must be reachable **from the device's VLAN**. Across VLANs, mDNS (`homeassistant.local`) often does not resolve — prefer `http://<HA-IP>:8123/local/echo-updates`. Plain `http://` is supported by the devices. |
| Device codenames | `biscuit cronos crown` | Space/comma separated: `biscuit` = Echo Dot (2nd gen), `cronos` = Echo Show 5 (2nd gen), `crown` = Echo Show 8 (1st gen). Leave empty to only mirror Kiosk Satellite. |
| Folder name under `www` | `echo-updates` | Folder is created automatically. |
| Hours between update checks | `6` | GitHub's anonymous API allows 60 requests/h; anything ≥ 1 is safe. |
| Also mirror Kiosk Satellite | on | Shares the same folder; toggle **Mirror only the universal APK** if you want the ~570 MB per-ABI APKs skipped in favor of the one ~250 MB universal APK. |
| Kiosk Satellite repository | `jxlarrea/kiosk-satellite` | Point at any fork — e.g. your own LAT-flavored release repo. |

Disk note: a full mirror is roughly **1.5–2 GB** (crown ≈ 590 MB, cronos ≈ 550 MB, biscuit ≈ 380 MB, kiosk ≈ 570 MB) inside `<config>/www/`, i.e. inside Home Assistant backups. Trim codenames or use the universal-APK option if that matters.

## Point the devices at Home Assistant

Or just call the **Device setup commands** service to get this with your URL filled in.

On an Echo Show:

```bash
adb shell setprop persist.echo.ota.releases http://<HA-IP>:8123/local/echo-updates/echo-releases.json
adb shell echo_service update check
adb shell echo_service update status
```

On an Echo Dot (2nd gen):

```bash
adb shell setprop persist.biscuit.ota.releases http://<HA-IP>:8123/local/echo-updates/echo-releases.json
adb shell biscuit_service update check
adb shell biscuit_service update status
```

The setting survives restarts and updates. To go back to GitHub: `adb shell setprop persist.echo.ota.releases ""` (or `persist.biscuit.ota.releases`).

On a kiosk running Kiosk Satellite: **Settings → Device → Updates → Update source → Custom Repository**, Repository URL `http://<HA-IP>:8123/local/echo-updates/releases.json` (the URL may end in `/releases.json`; the app keeps the folder). It also syncs across a fleet, and the Home Assistant Update entity keeps working.

## Verifying

- Open `http://<HA-IP>:8123/local/echo-updates/echo-releases.json` in a browser. `/local/` is served without authentication, exactly what the devices use; every `browser_download_url` in it should point at your Home Assistant.
- `update status` on the Echo should name the newest release in the folder. Kiosk Satellite: tap the version line (kiosk menu or remote admin) to check immediately.
- Devices check a minute after every boot; EchoService/BiscuitService are re-checked twice a day by Kiosk Satellite, and the kiosk app checks 20 s after launch and every 12 h.

### First boot of a fresh image

A newly installed LineageOS image downloads Kiosk Satellite from GitHub on its first boot. On a network without internet access, `adb install` the mirrored APK (`kiosk-satellite-<tag>.apk` from the folder) instead; the device guides cover the [installer steps](https://github.com/jxlarrea/lineageos-echo-kiosk-satellite/blob/main/docs/echo-show-8.md#kiosk-satellite-installer).

## Troubleshooting

- **Mirror status is `warning`** — a GitHub fetch or download failed on the last check; the folder still holds the last good mirror and devices keep seeing it. Attributes name the failing repo/device.
- **Rate limiting (HTTP 403)** — you are hitting the anonymous GitHub API limit; raise the check interval.
- **Device says newest release is missing** — the codename may be missing from the config, or `update status` tells you the exact reason (upstream docs list the common cases).
- **`releases.json` shows an update but the kiosk doesn't** — the APK names in `releases.json` must exist in the folder; both are mirrored by this integration, so check the kiosk's Update source URL against the `Kiosk Satellite release` sensor.

## Development

- `mirror.py` holds the pure GitHub→folder logic (URL rewriting, release selection, asset matching) with no Home Assistant imports, so it can be tested standalone against a real API response.
- CI runs `hassfest` and the HACS validator on every push.
