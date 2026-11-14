/*
 * PC Doctor case-sensor node (ESP32, Arduino framework).
 *
 * Once per sample interval it:
 *   1. asks the SHT31 for one temperature + humidity measurement over I2C,
 *   2. prints the reading on the serial port (115200 baud) for debugging,
 *   3. sends it as one 22-byte UDP packet to the receiver, if Wi-Fi is up.
 *
 * Rules this file follows:
 *   - Nothing waits forever. I2C has a timeout, Wi-Fi is never waited for,
 *     and the longest pause in the loop is the 20 ms the sensor needs.
 *   - Sampling does not depend on Wi-Fi. The sequence number counts samples
 *     taken, so anything lost while Wi-Fi was down shows up at the receiver
 *     as a gap - an honest loss figure.
 *   - The packet layout and the sensor maths live in lib/pcd_protocol, which
 *     has no Arduino code in it and is unit tested on a PC.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>

#include "config.h"
#include "pcd_protocol.h"
#include "pcd_sht31.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy include/secrets.example.h to include/secrets.h and fill in your Wi-Fi details."
#endif

static WiFiUDP g_udp;
static IPAddress g_receiver_ip;
static bool g_receiver_ip_ok = false;

static uint8_t g_sht31_addr = PCD_SHT31_ADDR_DEFAULT;

static uint32_t g_node_id = 0;
static uint32_t g_seq = 0;
static uint32_t g_next_sample_ms = 0;

static bool g_wifi_was_connected = false;
static uint32_t g_wifi_last_attempt_ms = 0;

/* ---- I2C ---------------------------------------------------------------- */

/* Writes a two-byte command to the sensor. True if the sensor acknowledged. */
static bool sht31_command(uint8_t msb, uint8_t lsb)
{
    Wire.beginTransmission(g_sht31_addr); /* START + address + write bit */
    Wire.write(msb);
    Wire.write(lsb);
    return Wire.endTransmission() == 0; /* sends the bytes, then STOP; 0 = ACKed */
}

/*
 * One single-shot measurement. On success fills both outputs and returns
 * NULL; on failure returns a short description of what went wrong.
 */
static const char *sht31_measure(int16_t *temp_centi_c, uint16_t *humidity_centi_pct)
{
    uint8_t frame[PCD_SHT31_FRAME_SIZE];

    /* Step 1: tell the sensor to measure (high repeatability, no clock
     * stretching, so it lets go of the bus while it works). */
    if (!sht31_command(PCD_SHT31_CMD_MEASURE_MSB, PCD_SHT31_CMD_MEASURE_LSB)) {
        return "no answer from sensor (check wiring)";
    }

    /* Step 2: wait for the measurement. A fixed 20 ms pause is the one place
     * the loop blocks; it is short and bounded. */
    delay(PCD_SHT31_MEASURE_WAIT_MS);

    /* Step 3: read 6 bytes: temp MSB, temp LSB, CRC, hum MSB, hum LSB, CRC. */
    if (Wire.requestFrom(g_sht31_addr, (uint8_t)PCD_SHT31_FRAME_SIZE) != PCD_SHT31_FRAME_SIZE) {
        /* Throw away a partial answer so it cannot leak into the next read. */
        while (Wire.available() > 0) {
            Wire.read();
        }
        return "sensor sent fewer than 6 bytes";
    }
    for (size_t i = 0; i < PCD_SHT31_FRAME_SIZE; i++) {
        frame[i] = (uint8_t)Wire.read();
    }

    /* Step 4: check both checksums and convert (shared, PC-tested code). */
    switch (pcd_sht31_parse_frame(frame, sizeof(frame), temp_centi_c, humidity_centi_pct)) {
    case PCD_SHT31_OK:
        return NULL;
    case PCD_SHT31_BAD_TEMP_CRC:
        return "temperature checksum wrong (noisy bus?)";
    case PCD_SHT31_BAD_HUMIDITY_CRC:
        return "humidity checksum wrong (noisy bus?)";
    default:
        return "internal error";
    }
}

/* Tries every I2C address and prints which ones answer. An address "answers"
 * if a device acknowledges it; no data is exchanged. */
static void scan_i2c_bus()
{
    bool found_default = false;
    bool found_alt = false;
    int found = 0;

    Serial.println("I2C scan:");
    for (uint8_t addr = 0x08; addr <= 0x77; addr++) { /* the valid 7-bit range */
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() != 0) {
            continue;
        }
        found++;
        const char *guess = "";
        if (addr == PCD_SHT31_ADDR_DEFAULT) {
            found_default = true;
            guess = "  <- SHT3x (ADDR pin low)";
        } else if (addr == PCD_SHT31_ADDR_ALT) {
            found_alt = true;
            guess = "  <- SHT3x (ADDR pin high)";
        }
        Serial.printf("  0x%02X answers%s\n", addr, guess);
    }
    if (found == 0) {
        Serial.println("  nothing answered - check 3V3, GND, SDA and SCL");
    }

    /* Use 0x45 only when it is there and 0x44 is not. */
    if (!found_default && found_alt) {
        g_sht31_addr = PCD_SHT31_ADDR_ALT;
    }
    Serial.printf("Using SHT31 at 0x%02X\n", g_sht31_addr);
}

/* ---- Wi-Fi --------------------------------------------------------------- */

static void wifi_start(uint32_t now_ms)
{
    g_wifi_last_attempt_ms = now_ms;
    WiFi.begin(PCD_WIFI_SSID, PCD_WIFI_PASSWORD); /* returns at once */
}

/* Called every loop. Reports changes and restarts a connection attempt that
 * has gone nowhere. Never waits. */
static void wifi_maintain(uint32_t now_ms)
{
    bool connected = (WiFi.status() == WL_CONNECTED);

    if (connected && !g_wifi_was_connected) {
        Serial.printf("Wi-Fi connected, address %s, signal %d dBm\n",
                      WiFi.localIP().toString().c_str(), (int)WiFi.RSSI());
    } else if (!connected && g_wifi_was_connected) {
        Serial.println("Wi-Fi lost - still sampling, will reconnect");
        g_wifi_last_attempt_ms = now_ms; /* give the built-in reconnect a chance first */
    }
    g_wifi_was_connected = connected;

    /* The ESP32 core reconnects by itself most of the time, but it can get
     * stuck. Starting over every few seconds is the backstop. Unsigned
     * subtraction keeps this right when millis() wraps after 49 days. */
    if (!connected && (uint32_t)(now_ms - g_wifi_last_attempt_ms) >= PCD_WIFI_RETRY_INTERVAL_MS) {
        Serial.println("Wi-Fi: trying to connect again");
        WiFi.disconnect();
        wifi_start(now_ms);
    }
}

/* ---- One sample ---------------------------------------------------------- */

/* Prints 2345 as "23.45" without floating point. */
static void print_centi(int32_t value)
{
    int32_t whole = value / 100;
    int32_t frac = value % 100;
    if (frac < 0) {
        frac = -frac;
    }
    Serial.printf("%s%ld.%02ld", (value < 0 && whole == 0) ? "-" : "", (long)whole, (long)frac);
}

static void take_sample(uint32_t now_ms)
{
    pcd_reading_t reading;
    uint8_t packet[PCD_PACKET_SIZE];
    int16_t temp = 0;
    uint16_t humidity = 0;
    const char *error = sht31_measure(&temp, &humidity);
    const char *net = "no Wi-Fi";

    reading.flags = 0;
    reading.node_id = g_node_id;
    reading.seq = g_seq++; /* counts samples, whether or not they get sent */
    reading.uptime_ms = now_ms;
    reading.temp_centi_c = 0;
    reading.humidity_centi_pct = 0;
    if (error == NULL) {
        reading.flags = PCD_FLAG_TEMP_VALID | PCD_FLAG_HUMIDITY_VALID;
        reading.temp_centi_c = temp;
        reading.humidity_centi_pct = humidity;
    }

    /* A failed read is still sent, with both "valid" flags clear, so the
     * receiver can tell "node alive, sensor broken" from "node gone". */
    if (!g_receiver_ip_ok) {
        net = "bad receiver address";
    } else if (WiFi.status() == WL_CONNECTED) {
        pcd_packet_encode(&reading, packet, sizeof(packet));
        bool sent = g_udp.beginPacket(g_receiver_ip, (uint16_t)PCD_RECEIVER_PORT) == 1 &&
                    g_udp.write(packet, sizeof(packet)) == sizeof(packet) &&
                    g_udp.endPacket() == 1;
        net = sent ? "sent" : "send failed";
    }

    Serial.printf("seq=%lu t_ms=%lu ", (unsigned long)reading.seq, (unsigned long)now_ms);
    if (error == NULL) {
        Serial.print("temp=");
        print_centi(temp);
        Serial.print("C rh=");
        print_centi(humidity);
        Serial.print("%");
    } else {
        Serial.printf("sensor error: %s", error);
    }
    Serial.printf(" udp=%s\n", net);
}

/* ---- Arduino entry points ------------------------------------------------ */

void setup()
{
    Serial.begin(PCD_UART_BAUD);
    Serial.println();
    Serial.println("PC Doctor case-sensor node, packet version 1");

    Wire.begin(PCD_I2C_SDA_PIN, PCD_I2C_SCL_PIN);
    Wire.setClock(PCD_I2C_FREQUENCY_HZ);
    Wire.setTimeOut(PCD_I2C_TIMEOUT_MS); /* a stuck bus must not hang the loop */
    scan_i2c_bus();
    if (sht31_command(PCD_SHT31_CMD_RESET_MSB, PCD_SHT31_CMD_RESET_LSB)) {
        delay(2); /* soft reset takes at most 1.5 ms */
    }

    g_receiver_ip_ok = g_receiver_ip.fromString(PCD_RECEIVER_IP);
    if (!g_receiver_ip_ok) {
        Serial.println("PCD_RECEIVER_IP in secrets.h is not an IPv4 address - nothing will be sent");
    }

    WiFi.mode(WIFI_STA); /* join a network; do not create one */
    WiFi.setAutoReconnect(true);
    wifi_start(millis());

    /* Pick the per-boot id after the radio is on: esp_random() is only a true
     * random source while Wi-Fi or Bluetooth is running. */
    g_node_id = esp_random();

    Serial.printf("Node id %08lX, sending to %s:%u every %lu ms\n", (unsigned long)g_node_id,
                  PCD_RECEIVER_IP, (unsigned)PCD_RECEIVER_PORT,
                  (unsigned long)PCD_SAMPLE_INTERVAL_MS);

    g_next_sample_ms = millis();
}

void loop()
{
    uint32_t now_ms = millis();

    wifi_maintain(now_ms);

    /* Signed difference so the comparison survives millis() wrapping. */
    if ((int32_t)(now_ms - g_next_sample_ms) < 0) {
        delay(1); /* lets the Wi-Fi task run; nothing to do yet */
        return;
    }

    /* Schedule from the previous deadline, not from "now", so the 20 ms spent
     * measuring does not make the rate drift. If we have fallen a whole
     * interval behind (a long stall), start afresh instead of bursting. */
    g_next_sample_ms += PCD_SAMPLE_INTERVAL_MS;
    if ((int32_t)(now_ms - g_next_sample_ms) >= 0) {
        g_next_sample_ms = now_ms + PCD_SAMPLE_INTERVAL_MS;
    }

    take_sample(now_ms);
}
