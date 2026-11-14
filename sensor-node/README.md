# sensor-node

A small case-temperature node for PC Doctor (Phase 7). An ESP32 reads an
SHT31 temperature/humidity sensor over I2C once a second, prints each reading
on its USB serial port, and sends it over Wi-Fi as one 22-byte UDP packet. A
Python receiver on the PC writes the readings to CSV and reports how many
packets were lost and the real sample rate.

```
firmware/                 ESP32 code (PlatformIO, Arduino framework)
  src/main.cpp            I2C, Wi-Fi, the sample loop
  lib/pcd_protocol/src/   packet format and SHT31 maths - plain C, no Arduino
  include/config.h        pins, sample interval, timeouts
  include/secrets.example.h   copy to secrets.h for your Wi-Fi details
  test_host/              tests for lib/pcd_protocol that run on a PC (make)
receiver/                 Python receiver, standard library only
  case_sensor/            python -m case_sensor
  tests/                  pytest
```

> **Not verified.** The firmware has never been compiled for the ESP32 and
> nothing here has run on real hardware. See [Not verified](#not-verified).

## Safety first

- **Low-voltage parts only.** Everything here runs on 5 V USB and 3.3 V. No
  mains, no PSU cables, no modding the power supply.
- **USB powered, from outside the PC.** Power the ESP32 from a USB phone
  charger, a power bank, or an external USB port on the back of the PC.
- **Never wire it to the PC's internal headers** - not the fan headers, not
  the internal USB headers, not RGB or front-panel pins. A wrong wire there
  can damage the motherboard. The node only *sits* in the case; the only
  thing that goes inside is the small sensor board on its four wires.
- Keep the wires clear of every fan and tie them down. Make sure the sensor
  board cannot touch anything metal on the motherboard or graphics card
  (a bit of tape on the back of the board, or a small plastic bag with holes,
  is enough).

## Parts

| Part | Notes |
|---|---|
| ESP32 dev board | Any "ESP32 DevKit" / `esp32dev` board with a USB port. Must be ESP32 (2.4 GHz Wi-Fi), not ESP8266. |
| SHT31 breakout board | SHT31-D / SHT3x on a small board with pull-up resistors (most have them). Address 0x44 or 0x45. |
| 4 jumper wires | Female-female for a dev board with header pins. 30-50 cm lets the ESP32 stay outside the case. |
| USB cable | A **data** cable (some charge-only cables have no data wires and cannot flash). |
| USB power | Charger, power bank, or an external USB port on the PC. |

## Wiring

| SHT31 board | ESP32 dev board | |
|---|---|---|
| VIN (or VCC) | 3V3 | Use 3.3 V, not 5 V, so the I2C lines stay at the ESP32's 3.3 V level. |
| GND | GND | |
| SDA | GPIO 21 | I2C data |
| SCL | GPIO 22 | I2C clock |
| ADDR (if present) | leave unconnected | 0x44. Tie to 3V3 for 0x45; the firmware finds either. |

Pins are set in `firmware/include/config.h` (`PCD_I2C_SDA_PIN`,
`PCD_I2C_SCL_PIN`). The I2C bus runs at 100 kHz, which copes better with
long jumper wires than 400 kHz.

Put the sensor where you want to know the air temperature (for example near
the graphics card intake), away from the direct exhaust of any one part.

## Build and flash (PlatformIO)

1. Install PlatformIO: `pip install platformio`, or the PlatformIO extension
   for VS Code.
2. Copy the secrets file and fill in your Wi-Fi name, password, and the IPv4
   address of the computer that will run the receiver (`ipconfig` on Windows,
   `ip addr` on Linux):

   ```
   cd sensor-node/firmware
   cp include/secrets.example.h include/secrets.h
   ```

   `secrets.h` is git-ignored. Never commit it. The ESP32 can only join a
   2.4 GHz network.
3. Build, flash and watch the serial output:

   ```
   pio run                  # build
   pio run -t upload        # flash over USB
   pio device monitor       # serial output at 115200 baud (Ctrl+C to quit)
   ```

At start-up the node prints an I2C scan (it should list 0x44 or 0x45), its
random node id, and then one line per sample with the sequence number,
temperature, humidity and whether the UDP send worked. To sample at a
different rate, add for example `-DPCD_SAMPLE_INTERVAL_MS=500` to
`build_flags` in `platformio.ini` (do not go below about 50 ms).

## Host tests (no ESP32 needed)

The packet code and the SHT31 maths have no Arduino code in them, so they are
tested on a PC with a C and a C++ compiler:

```
cd sensor-node/firmware/test_host
make            # builds and runs the 24 tests
make tool       # optional: pcd_tool, to encode/decode packets by hand
```

## The receiver

Python 3.11 or newer, nothing to install. From `sensor-node/receiver`:

```
python -m case_sensor --csv case.csv                 # listen until Ctrl+C
python -m case_sensor --csv case.csv --duration 600  # listen for 10 minutes
python -m case_sensor --help
```

It listens on UDP port 9750 on every network interface. On Windows, allow
Python through the firewall for private networks when asked (or add an
inbound rule for UDP 9750), or nothing will arrive.

Each packet is checked (length, the `PD` magic bytes, the version, and a
CRC-16) before it is used; anything else is counted as rejected. The CSV
has one row per sample:

```
elapsed_s,case_temp_c,case_humidity_pct
0.482,32.10,38.05
```

`elapsed_s` is seconds since the receiver started, by the PC's clock. If the
sensor read failed on the node, the packet still arrives (so you know the
node is alive) and that value is left empty in the CSV rather than written
as 0. Duplicates are not written.

### Measuring loss and sample rate

Run the receiver for a fixed time with the node powered and in place, then
read the summary it prints at the end:

```
python -m case_sensor --csv case.csv --duration 600 --quiet
```

| Line | Meaning |
|---|---|
| packets | Valid packets received, and how many distinct samples that was. |
| expected samples | How many samples the node took between the first and last one received, from the sequence numbers. |
| lost | expected - received. The node counts samples *taken*, so a sample missed while Wi-Fi was down counts as lost too. |
| loss | lost / expected, in %. |
| duplicates, reordered | Packets the network delivered twice or out of order. Reordered ones are not lost. |
| rejected | Datagrams that failed the length, magic, version or CRC check. |
| node boots seen | The node picks a new id at each power-on; more than 1 means it restarted (or there is more than one node). |
| sample rate | Samples per second by the **node's** clock (`uptime_ms` and sequence numbers), so Wi-Fi delays do not affect it. Should be close to 1.000 Hz. |
| receive rate | Packets that arrived per second by the PC's clock, first to last packet - about sample rate x (1 - loss). |

Samples taken before the receiver started, and after the last packet it got,
cannot be known, so they are not counted either way. Sequence numbers that
wrap from 4294967295 to 0 are handled.

For a meaningful loss figure, run for at least 10 minutes and write down
where the node was, the Wi-Fi signal (the node prints it when it connects),
and what the PC was doing.

### Trying it without hardware

`--simulate` pretends to be a node. It can drop a fraction of its packets on
purpose (its sequence numbers still go up, like the firmware's), so you can
check the receiver reports the loss you asked for. In one terminal:

```
python -m case_sensor --csv test.csv
```

and in a second one:

```
python -m case_sensor --simulate --loss 0.05 --rate 5 --count 300
python -m case_sensor --simulate --start-seq 4294967290 --count 20   # crosses the wrap
```

Use `--host` to send to another computer and `--seed` for a repeatable run.

### Receiver tests

```
cd sensor-node/receiver
pip install pytest
pytest
```

One test compiles a small C program with the firmware's own encoder
(`pcd_protocol.c`) and checks that the Python parser reads its packets as the
same values (and the other way round). It is skipped if no C compiler is
installed.

## Packet format

22 bytes, little-endian. The authoritative description is the comment at the
top of `firmware/lib/pcd_protocol/src/pcd_protocol.h`, and
`receiver/case_sensor/packet.py` mirrors it.

| Offset | Size | Field |
|---|---|---|
| 0 | 2 | magic `PD` (0x50 0x44) |
| 2 | 1 | version, 1 |
| 3 | 1 | flags: bit 0 temperature valid, bit 1 humidity valid |
| 4 | 4 | node id, random at each boot |
| 8 | 4 | sequence number, +1 per sample taken |
| 12 | 4 | uptime in ms when sampled |
| 16 | 2 | temperature, 0.01 degC, signed |
| 18 | 2 | humidity, 0.01 %, unsigned |
| 20 | 2 | CRC-16/CCITT-FALSE of bytes 0-19 |

## Not verified

Be clear about what has and has not been checked:

- **The firmware has never been compiled for the ESP32.** PlatformIO (and so
  the ESP32 toolchain and the Arduino core) could not be reached from the
  environment this was written in, so `pio run` has never been run.
  `src/main.cpp` may not even compile yet.
- **Nothing has run on real hardware.** No ESP32, no SHT31, no Wi-Fi. The
  wiring above is from the boards' usual pinouts and the SHT3x datasheet, not
  from a tested build.
- **There are no measured numbers yet** - no loss figure, no real sample
  rate, no temperatures. Any numbers in this README are examples of the
  output format, not measurements.

What *has* been checked, on a PC: the packet encoder/decoder and the SHT31
checksum and conversion (24 host tests in `firmware/test_host`, built with
the same C code the firmware uses), and the receiver, including a test that
decodes packets made by the compiled C encoder and a UDP round trip with the
simulator on localhost.
