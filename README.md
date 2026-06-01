# Kiprim-DC6505-Pro-SCPI-Driver
A Python driver for the Kiprim DC6505 Pro power supply + multimeter. Compatible with Kiprim DC605Pro, DC310Pro, DC310S, and OWON SPE3103, communicating over USB-serial using the device's SCPI-like command set.

## Compatible hardware

| Model | Voltage | Current |
|---|---|---|
| Kiprim DC605Pro | 0–60 V | 0–5 A |
| Kiprim DC310Pro | 0–30 V | 0–10 A |
| Kiprim DC310S | 0–30 V | 0–10 A |
| OWON SPE3103 / SPP3103 | 0–30 V | 0–3 A |

The DC310S and OWON units share the same firmware and serial protocol. The DC605Pro and DC310Pro are the same design at different voltage/current ratings.

## Requirements

Python 3.10+ and [pyserial](https://pypi.org/project/pyserial/):

```
pip install pyserial
```

No other dependencies. Copy `kiprim_dc605pro.py` into your project.

## Finding the serial port

**Linux:** plug in the USB cable, then run `ls /dev/ttyUSB*`. It will usually be `/dev/ttyUSB0`. If you get a permission error, add yourself to the `dialout` group:

```bash
sudo usermod -aG dialout $USER   # log out and back in after this
```

**Windows:** open Device Manager → Ports (COM & LPT). Look for a CH340 or CP2102 entry. The port will be something like `COM3`.

**macOS:** run `ls /dev/tty.usbserial-*` or `ls /dev/tty.wchusbserial*`.

## Quick start

```python
from kiprim_dc605pro import DC605Pro

with DC605Pro("/dev/ttyUSB0") as psu:
    print(psu.identify())          # KIPRIM DC605Pro | S/N: ... | FW: V1.2.3
    psu.set_voltage(12.0)
    psu.set_current(1.5)
    psu.output_on()
    print(psu.measure_all())       # 11.998 V  1.234 A  14.801 W
    psu.output_off()
```

The `with` statement handles `connect()` and `disconnect()` automatically. You can also manage the connection manually:

```python
psu = DC605Pro("/dev/ttyUSB0")
psu.connect()
# ... do things ...
psu.disconnect()
```

## API reference

### Constructor

```python
DC605Pro(port, timeout=3.0, voltage_max=60.0, current_max=5.0)
```

`voltage_max` and `current_max` are soft limits enforced in software before any command is sent. Set them to match your hardware model if you're using a DC310Pro or DC310S, or to a lower value if you want to restrict the range for a particular test rig.

### Connection

| Method | Description |
|---|---|
| `connect()` | Open the serial port. Called automatically by `__enter__`. |
| `disconnect()` | Close the serial port. Called automatically by `__exit__`. |
| `is_connected()` | Returns `True` if the port is open. |

### Identification

```python
info = psu.identify()
# info.manufacturer  → "KIPRIM"
# info.model         → "DC605Pro"
# info.serial_number → "..."
# info.firmware      → "FV:V1.2.3"
print(info)            # KIPRIM DC605Pro | S/N: ... | FW: FV:V1.2.3
```

### Output control

```python
psu.output_on()            # enable output
psu.output_off()           # disable output
psu.set_output(True/False) # enable or disable
psu.get_output()           # → True if output is ON
```

### Voltage and current set-points

```python
psu.set_voltage(12.0)            # set output to 12.000 V
psu.set_current(1.5)             # set current limit to 1.500 A
psu.get_voltage_setpoint()       # → 12.0
psu.get_current_setpoint()       # → 1.5
```

### Live measurements

```python
psu.measure_voltage()   # → actual output voltage in V
psu.measure_current()   # → actual output current in A
psu.measure_power()     # → actual power in W (V × I, or measure:power? if supported)

m = psu.measure_all()   # → Measurement(voltage, current, power)
print(m)                # 11.998 V  1.234 A  14.801 W
```

### Protection limits

```python
psu.set_voltage_limit(13.0)   # OVP threshold in V
psu.set_current_limit(2.0)    # OCP threshold in A
psu.get_voltage_limit()       # → 13.0
psu.get_current_limit()       # → 2.0
```

Set OVP ~1 V above your target and OCP ~1 A above your expected peak draw. The device will cut the output if either threshold is exceeded.

### Reset

```python
psu.reset()   # sends *RST, restores factory defaults, turns output off
```

### Convenience helpers

**`configure(voltage, current, ovp=None, ocp=None)`** — set everything in one call, with a built-in 300 ms settle delay so subsequent queries don't time out:

```python
psu.configure(28.0, 5.0, ovp=29.0, ocp=6.0)
```

**`powered(voltage, current)`** — context manager that turns the output on for the duration of the block and guarantees it turns off on exit, even if an exception is raised:

```python
with psu.powered(5.0, 0.5):
    time.sleep(2)
    print(psu.measure_all())
# output is off here
```

**`ramp_voltage(start, stop, duration, steps=100, output_on=True)`** — linearly ramp the voltage over `duration` seconds:

```python
psu.set_current(1.0)
psu.ramp_voltage(0.0, 60.0, duration=10.0, steps=200)
# ramps from 0 V to 60 V over 10 seconds
```

**`list_mode(steps, repeat=1)`** — run a sequence of voltage/current steps, each held for a given duration. Output turns on at the start and off at the end:

```python
psu.list_mode([
    {"voltage": 5.0,  "current": 1.0, "duration": 2.0},
    {"voltage": 12.0, "current": 0.5, "duration": 3.0},
    {"voltage": 24.0, "current": 0.2, "duration": 1.0},
], repeat=3)
```

## Error handling

Three exception classes, all inheriting from `DC605ProError`:

```python
from kiprim_dc605pro import DC605ProError, CommunicationError, RangeError

try:
    psu.set_voltage(100.0)          # raises RangeError — over voltage_max
except RangeError as e:
    print(e)                         # voltage 100.0 is out of range [0.0, 60.0]

try:
    psu.measure_voltage()           # raises CommunicationError if device times out
except CommunicationError as e:
    print(e)
```

`CommunicationError` is raised on timeout, no response, or the device returning `ERR`. `RangeError` is raised before any command is sent, so the device state is never changed by an out-of-range call.

## Timing notes

The device's USB-serial chip (CH340 or CP2102) needs time to settle after the port is opened. The driver waits 500 ms on `connect()` and 50 ms between consecutive set commands. If you see timeout errors immediately after `connect()`, try increasing the timeout:

```python
psu = DC605Pro("/dev/ttyUSB0", timeout=5.0)
```

If you're sending many set commands in a loop and seeing `ERR` responses, add a short sleep between them — the firmware processes one command at a time.

## Running the built-in self-test

The module can be run directly to verify communication:

```bash
python kiprim_dc605pro.py /dev/ttyUSB0   # Linux/macOS
python kiprim_dc605pro.py COM3           # Windows
```

This will identify the device and print the current set-points and live measurements without changing any settings or enabling the output.

## Protocol notes

The device uses a plain ASCII serial protocol at 115200 8N1. Commands are newline-terminated (`\n`). Responses are CR LF-terminated. Unknown commands return `ERR`. The protocol is documented in the [OWON SP series programming manual](http://files.owon.com.cn/software/Application/SP&P_Series_Single_Channel_DC_Power_Supply_Programming_Manual.pdf), which covers the full command set including list mode and calibration commands not implemented in this driver.

| Setting | Value |
|---|---|
| Baud rate | 115200 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Command terminator | `\n` (0x0A) |
| Response terminator | CR LF (0x0D 0x0A) |

## License

MIT
