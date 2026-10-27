# FortiusANT connectivity in this fork

This fork retains the original ANT+/USB trainer communication and the native
Python Bless BLE server. It also introduces an **experimental WFTNP FTMS TCP
server** (see [README](../README.md)).

## Bluetooth LE (Bless)

The old Node.js/Bleno BLE server is not used by this fork. BLE FTMS is served
by `pythoncode/bleBless.py` and `pythoncode/bleBlessClass.py`, using the
Python `bless` package. Do not install Node.js or run `npm install` for
FortiusANT. Hardware and OS support depend on Bless and the host BLE adapter.

The existing Bless selection remains available in the graphical settings.
Older startup scripts may refer to `-b` or `-bb`; consult the application's
current `--help` for the supported command-line options.

## WFTNP over TCP (experimental)

The `--wftnp` option starts a WFTNP server using the separately installed
[VUTSHYK/py-wftnp](https://github.com/VUTSHYK/py-wftnp) library. Its default
TCP port is `36866`. Configure the bind address with `--wftnp-host`
(`127.0.0.1` for local-only, `0.0.0.0` for trusted LAN access).

The WFTNP server is not a Bluetooth peripheral; it does not require Node.js
or a BLE adapter. GitHub CI has exercised the local TCP transport, but
compatibility with Zwift and real Tacx Vortex hardware has **not** been
validated yet.
