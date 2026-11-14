/*
 * Settings that are not secret. Each can be overridden from platformio.ini
 * with a -D build flag, which is why they are wrapped in #ifndef.
 */
#ifndef PCD_CONFIG_H
#define PCD_CONFIG_H

/* Time between samples. 1000 ms = 1 Hz. The SHT31 needs about 20 ms per
 * measurement, so do not go below about 50 ms. */
#ifndef PCD_SAMPLE_INTERVAL_MS
#define PCD_SAMPLE_INTERVAL_MS 1000u
#endif

/* The ESP32 dev board's usual I2C pins. */
#ifndef PCD_I2C_SDA_PIN
#define PCD_I2C_SDA_PIN 21
#endif
#ifndef PCD_I2C_SCL_PIN
#define PCD_I2C_SCL_PIN 22
#endif

/* 100 kHz (standard mode) tolerates long jumper wires better than 400 kHz. */
#ifndef PCD_I2C_FREQUENCY_HZ
#define PCD_I2C_FREQUENCY_HZ 100000u
#endif

/* Give up on a stuck I2C bus after this long instead of hanging. */
#ifndef PCD_I2C_TIMEOUT_MS
#define PCD_I2C_TIMEOUT_MS 50u
#endif

#ifndef PCD_UART_BAUD
#define PCD_UART_BAUD 115200u
#endif

/* How long to leave a Wi-Fi connection attempt alone before starting again. */
#ifndef PCD_WIFI_RETRY_INTERVAL_MS
#define PCD_WIFI_RETRY_INTERVAL_MS 10000u
#endif

#endif /* PCD_CONFIG_H */
