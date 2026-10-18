#---------------------------------------------------------------------------
# Version info
#---------------------------------------------------------------------------
__version__ = "2026-10-18"

from   constants import mode_Power, mode_Grade, UseBluetooth

import debug
import lib_programname
import logfile
import os
import sys
import time
import atexit
import threading
import asyncio
import logging

import FortiusAntCommand    as cmd

# Attempt to import our DirconServer (must be available in pythoncode directory)
try:
    import dircon_server
except Exception:
    dircon_server = None

logger = logging.getLogger("Fortiusant.ble")

#---------------------------------------------------------------------------
# c l s B l e I n t e r f a c e
#---------------------------------------------------------------------------
# This implementation replaces the old Node.js bridge with a pure-Python
# DirconServer (asyncio + zeroconf). The class keeps the old interface:
#   Open(), Write(data), Read(), Close()
# so that FortiusAntBody can continue to use it unchanged.
#---------------------------------------------------------------------------
class clsBleInterface():
    def __init__(self, clv, host = '127.0.0.1', port = 9999):
        self.OK        = False
        self.host      = host
        self.port      = port
        self.interface = None
        self.jsondata  = None
        self.steering  = clv.Steering is not None
        self._clv = clv

        # Dircon related
        self.dircon = None
        self._loop = None
        self._thread = None
        self._stop_event = threading.Event()

        atexit.register(self.Close)

        if debug.on(debug.Ble): logfile.Write('clsBleInterface initialized')

    def __del__(self):
        pass

    #-------------------------------------------------------------------
    # O p e n
    #-------------------------------------------------------------------
    def Open(self):
        """
        Start DirconServer in background thread (asyncio loop).
        """
        self.OK = False
        self.Message = ", Bluetooth interface cannot be opened"
        if debug.on(debug.Ble): logfile.Write ("BleInterface.Open() ...")

        if dircon_server is None:
            self.Message += "; dircon_server module not found"
            if debug.on(debug.Ble): logfile.Write('dircon_server module not available')
            return False

        if self.dircon is None:
            # create server instance
            serial = getattr(self._clv, 'DeviceSerial', 'FortiusANT-0001')
            mac = getattr(self._clv, 'DeviceMac', 'AA:BB:CC:DD:EE:FF')
            self.dircon = dircon_server.DirconServer(
                name = "FortiusANT Trainer",
                serial = serial,
                mac = mac,
                host = self.host,
                port = self.port,
            )

            def _run_loop():
                loop = asyncio.new_event_loop()
                self._loop = loop
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.dircon.start())
                    # keep loop running until stop requested
                    while not self._stop_event.is_set():
                        loop.run_until_complete(asyncio.sleep(0.25))
                except Exception as e:
                    logger.exception('Dircon loop exception: %s', e)
                finally:
                    try:
                        loop.run_until_complete(self.dircon.stop())
                    except Exception:
                        pass
                    try:
                        loop.close()
                    except Exception:
                        pass

            self._thread = threading.Thread(target=_run_loop, daemon=True)
            self._thread.start()

            # give server a short time to start
            timeout = 2.0
            t0 = time.time()
            while self._loop is None and (time.time() - t0) < timeout:
                time.sleep(0.01)

            if self._loop is None:
                self.Message += "; Dircon loop failed to start"
                if debug.on(debug.Ble): logfile.Write(self.Message)
                return False

            self.Message = ", Bluetooth interface open (DirCon)"
            self.OK = True
        else:
            if debug.on(debug.Ble): logfile.Write('... already open')

        if self.OK: logfile.Console("FortiusANT exchanges data with a bluetooth Cycling Training Program (DirCon)")
        return self.OK

    #-------------------------------------------------------------------
    # W r i t e
    #-------------------------------------------------------------------
    def Write(self, data):
        """
        Notify connected DirCon clients with FTMS Indoor Bike Data.
        data is expected as dict: {'watts': , 'cadence': , 'heart_rate': , 'speed_kmh': }
        """
        if not self.OK or self.dircon is None or self._loop is None:
            return False

        try:
            fut = asyncio.run_coroutine_threadsafe(self.dircon.notify_data(data), self._loop)
            fut.result(timeout=1.0)
            return True
        except Exception as e:
            logfile.Console(f"... dircon notify error {e}")
            return False

    #-------------------------------------------------------------------
    # R e a d
    #-------------------------------------------------------------------
    def Read(self):
        """
        Poll control command queue from DirCon server and translate to
        self.jsondata similar to the old HTTP/node implementation.
        Returns True when jsondata filled.
        """
        self.jsondata = None
        if not self.OK or self.dircon is None or self._loop is None:
            return False

        try:
            fut = asyncio.run_coroutine_threadsafe(self.dircon.get_control_command(timeout=0.01), self._loop)
            cmd = fut.result(timeout=1.0)
        except Exception:
            return False

        if not cmd:
            return False

        char_uuid, payload, client_info = cmd
        self.jsondata = self._parse_control_payload(char_uuid, payload)
        return bool(self.jsondata)

    #-------------------------------------------------------------------
    # C l o s e
    #-------------------------------------------------------------------
    def Close(self):
        if self.dircon is None:
            return

        try:
            if self._loop is not None:
                try:
                    fut = asyncio.run_coroutine_threadsafe(self.dircon.stop(), self._loop)
                    fut.result(timeout=2.0)
                except Exception:
                    pass

                self._stop_event.set()
                try:
                    # stop loop
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except Exception:
                    pass

            if self._thread is not None:
                self._thread.join(timeout=1.0)
        except Exception:
            logger.exception('Error closing Dircon')
        finally:
            self.dircon = None
            self._loop = None
            self._thread = None
            self.OK = False
            self.Message = ", Bluetooth interface closed"

    #-------------------------------------------------------------------
    # Payload parser for control commands coming from DIRCON (FTMS Control Point)
    #-------------------------------------------------------------------
    def _parse_control_payload(self, char_uuid: str, payload: bytes):
        """
        Very small parser that maps a couple of common FTMS control opcodes
        to a JSON-like dict used by the rest of FortiusANT.

        Known/guessed opcodes (implementation may require adaptation):
            0x01: Set Target Resistance/Grade  -> payload [0x01, LSB, MSB]
            0x02: Set Target Power            -> payload [0x02, LSB, MSB]
        """
        try:
            if char_uuid.upper() == '2AD9' or char_uuid.upper() == '2AD2':
                if len(payload) < 1:
                    return None
                opcode = payload[0]
                if opcode == 0x02 and len(payload) >= 3:
                    # target power (watts)
                    target = int.from_bytes(payload[1:3], 'little')
                    return {"target_power": target}
                if opcode == 0x01 and len(payload) >= 3:
                    target = int.from_bytes(payload[1:3], 'little')
                    # Treat as grade (percentage*100?) -- here pass raw
                    return {"grade": target}
        except Exception:
            logger.exception('Error parsing control payload')
        return None


#---------------------------------------------------------------------------
# c l s B l e C T P (Cycling Training Program)
#---------------------------------------------------------------------------
class clsBleCTP(clsBleInterface):
    HeartRate           = 0
    CurrentSpeed        = 0
    Cadence             = 0
    CurrentPower        = 0
    SteeringAngle       = 0

    TargetMode          = None
    TargetGrade         = 0
    TargetPower         = 0

    WindResistance      = None
    WindSpeed           = None
    DraftingFactor      = 1
    RollingResistance   = None

    def SetAthleteData(self, HeartRate):
        self.HeartRate      = HeartRate

    def SetTrainerData(self, CurrentSpeed, Cadence, CurrentPower):
        self.CurrentSpeed   = CurrentSpeed
        self.Cadence        = Cadence
        self.CurrentPower   = CurrentPower

    def SetSteeringAngle(self, SteeringAngle):
        self.SteeringAngle  = SteeringAngle

    def Refresh(self):
        """
        Keep old contract: send current data to CTP and collect potential
        commands. Returns True if a command (target power/grade/etc.) is found.
        """
        rtn = False
        if self.OK:
            if self.steering:
                # Inform clients about steering; treat as separate notify
                try:
                    _ = asyncio.run_coroutine_threadsafe(
                        self.dircon.notify_data({"steering_angle": self.SteeringAngle}),
                        self._loop
                    )
                    _ .result(timeout=0.5)
                except Exception:
                    pass

            data = {}
            data['heart_rate'] = self.HeartRate
            data['watts'] = self.CurrentPower
            data['cadence'] = self.Cadence

            # send notification
            if self.Write(data):
                # try to read commands (non-blocking)
                if self.Read():
                    try:
                        self.TargetPower = self.jsondata.get("target_power", self.TargetPower)
                        self.TargetMode = mode_Power
                        rtn = True
                    except Exception:
                        pass
                    try:
                        self.TargetGrade = self.jsondata.get("grade", self.TargetGrade)
                        self.TargetMode = mode_Grade
                        rtn = True
                    except Exception:
                        pass
                    try:
                        self.WindResistance = self.jsondata.get("wind_resistance_coefficient", self.WindResistance)
                        rtn = True
                    except Exception:
                        pass
        return rtn


# ==============================================================================
# Main program (for standalone testing)
# ==============================================================================
if __name__ == "__main__":
    # quick test harness
    debug.deactivate()
    clv = cmd.CommandLineVariables()
    debug.activate(clv.debug)

    if debug.on(debug.Ble):
        logfile.Open()
        logfile.Console("bleDongle started (DirCon)")
        clv.print()
        logfile.Console("------------------")

    if clv.ble:
        bleCTP = clsBleCTP(clv)
        if bleCTP.Open():
            print(bleCTP.Message)
            try:
                import random
                while True:
                    bleCTP.SetAthleteData(135)
                    bleCTP.SetTrainerData(34.5, 123, 246)

                    if bleCTP.Refresh():
                        print('Target Mode=%s, Power=%s, Grade=%s' % (bleCTP.TargetMode, bleCTP.TargetPower, bleCTP.TargetGrade) )
                    else:
                        print('No data')
                    time.sleep(0.25)
            except KeyboardInterrupt:
                logfile.Console ("Stopped (keyboard interrupt)")
            except Exception as e:
                print (str(e))
            bleCTP.Close()
        else:
            print(bleCTP.Message)

    if debug.on(debug.Ble):
        logfile.Console("bleDongle ended")
