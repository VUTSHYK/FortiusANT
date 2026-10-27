# FortiusANT
FortiusANT enables a pre-smart Tacx trainer (usb- or ANT-connected) to communicate with TrainerRoad, Rouvy or Zwift through ANT.

FortiusANT is running on the computer (Windows, Linux or MacOS) where the trainer is connected and broadcasts the ANT+ signal, using a dongle, to another computer or tablet.
You might also run TrainerRoad or Zwift on the same computer and then two ANT+ dongles on the same computer are required.

Important: legacy Node.js/Bleno and the experimental Python TCP/DirCon server are removed from the runtime. Bluetooth uses the native Python Bless implementation (`bleBless.py`); ANT/USB support remains. Any remaining historical files under `node/` are not part of the runtime.

## This fork: WFTNP / FTMS support (experimental)

This is a development fork of [WouterJD/FortiusANT](https://github.com/WouterJD/FortiusANT), **not** an upstream release. The original FortiusANT provides ANT+/USB trainer support and BLE options. This branch adds a network-based FTMS transport using **WFTNP over TCP** as an alternative to the existing Bless BLE path. The goal is to use a Tacx Vortex attached to a Raspberry Pi without relying on the unreliable BLE bridge.

### Changes compared with the upstream project

- **WFTNP transport:** `pythoncode/wftnpTransport.py` serves FTMS Indoor Bike Data and Fitness Machine Control Point characteristics over TCP using [VUTSHYK/py-wftnp](https://github.com/VUTSHYK/py-wftnp).
- **Control and telemetry separation:** `ftmsBridge.py` holds thread-safe trainer measurements and a bounded command queue; `ftmsControlPoint.py` validates control ownership, ERG target power, and simulation grade commands.
- **Adapter and lifecycle:** `ftmsWftnpAdapter.py` translates FTMS commands to the existing trainer-loop interface; `wftnpRuntime.py` runs the network server on a separate asyncio thread. `FortiusAntBody.py` connects these components to the trainer loop.
- **Configuration:** `FortiusAntCommand.py` adds `--wftnp`, `--wftnp-host`, `--wftnp-port`, and `--wftnp-idle-timeout`. `settings.py` adds WFTNP selection, bind address, and TCP port to the wxPython settings dialog and `FortiusAntSettings.json` persistence. WFTNP and the legacy BLE selections are mutually exclusive in the dialog.
- **Regression tests:** `tests/test_ftms_*.py` and `tests/test_wftnp_*.py` cover the FTMS bridge, ownership, JSON loading, real TCP exchange, and threaded server lifecycle. `.github/workflows/transport-cleanup.yml` runs a multi-platform Python matrix plus a dedicated WFTNP TCP integration job.

### Running the experimental WFTNP mode

Install a compatible `py-wftnp` library first (the CI integration tests pin commit `af8e46ddedfe9f4cd1e16680676dadd320a77242` from `VUTSHYK/py-wftnp`). From the `pythoncode/` directory, with the normal FortiusANT dependencies and trainer connectivity available:

```bash
python FortiusAnt.py --wftnp --wftnp-host 0.0.0.0 --wftnp-port 36866
```

Alternatively select WFTNP in the graphical settings dialog and save the settings for the next run. `0.0.0.0` listens on all network interfaces: use only on a trusted LAN; use `127.0.0.1` for local-only access. Port `36866` is the default.

**Validation status:** GitHub Actions run [#55](https://github.com/VUTSHYK/FortiusANT/actions/runs/40461420498) passed the Python test matrix and actual loopback TCP client/server tests. **Full FortiusANT GUI startup, Raspberry Pi 3 + Tacx Vortex hardware control, and discovery/operation in Zwift have not yet been verified.** A successful `py-wftnp` client test does not establish Zwift compatibility.

### Legacy cleanup performed in this branch

The obsolete `node/` JavaScript/Bleno tree (19 tracked files), its Raspberry
Pi installation scripts `raspberry/3_InstallNodeJs.sh` and
`raspberry/6_SetupNodeJs_FortiusAnt.sh`, and the superseded
`pythoncode/wftnp_bridge.py` were removed in commit
[`2d087dc`](https://github.com/VUTSHYK/FortiusANT/commit/2d087dc1a338c71b626267969bf19866623405c5).
The legacy Node.js installation instructions in `doc/bluetooth.md` were
replaced with Bless and WFTNP guidance.

**Kept intentionally:** `pythoncode/bleBless.py`,
`pythoncode/bleBlessClass.py`, BLE testing tools, ANT+/USB trainer drivers,
settings, GUI, Raspberry Pi hardware utilities, Windows/macOS build resources,
and historical project documentation. Removing any of these would require
separate feature-removal decisions or more validation. This cleanup does not
disable the Bless alternative.


---

## Supported Tacx trainers
USB: Tacx Flow, Fortius, i-Flow, i-Magic with T1902, T1904, T1932, T1942 head units

ANT: Tacx Vortex, Genius, Bushido (with T1982 head unit)

Bushido support is still *experimental* at this time (please consider providing feedback in https://github.com/WouterJD/FortiusANT/issues/117).

## Communication with Trainer Road, Rouvy, Zwift and others
Communication with a Cycling Training Program (CTP) can be done using an ANT- or BLE-dongle (BLE = Bluetooth Low Energy)

The CTP can be run on another computer or Smartphone.

**ANT dongles made by CYCPLUS (identical-looking ones sold as Anself and probably others) have been known to cause problems.** Refer to issue #61 (#97, #207 and others)

# User manual and version information
Refer [wiki](https://github.com/WouterJD/FortiusANT/wiki) first, then ask questions raising an issue. Succes!

For inspiration, visit the [Raspberry Pi Hall of Fame](https://github.com/WouterJD/FortiusANT/wiki/Raspberry-Pi-Hall-of-Fame) and [The Tacx Training Cave](https://github.com/WouterJD/FortiusANT/wiki/The-Tacx-Training-Cave).

![image](https://raw.githubusercontent.com/WouterJD/FortiusANT/master/supportfiles/FortiusAntWorld.jpg)

# License

GPLv3

Copyright (c) 2020...2023 [Wouter Dubbeldam](https://github.com/WouterJD). Please have a look at the [LICENSE](LICENSE) for more details.

# Sponsor
[![Custom badge](https://github.com/WouterJD/FortiusANT/blob/master/pythoncode/sponsor36.bmp)](https://github.com/sponsors/WouterJD)

If you like to use FortiusAnt; please leave a note on the [put yourself on the FortiusAnt map](https://github.com/WouterJD/FortiusANT/issues/14) page; thereby a sponsorship would be another great way to support the project.

### Before merging WFTNP into master

- [ ] Revisit the `py-wftnp` dependency in both `pythoncode/requirements.txt` and `pythoncode/requirementsNoGUI.txt`. It is currently pinned to commit `af8e46ddedfe9f4cd1e16680676dadd320a77242` (which matched `VUTSHYK/py-wftnp` `master` on 2026-10-27). Decide whether to switch to a stable release/tag or the current `master`, update both files consistently, and rerun WFTNP integration and Python compatibility tests before merging FortiusANT.
