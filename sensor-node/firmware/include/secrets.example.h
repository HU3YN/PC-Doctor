/*
 * Copy this file to secrets.h (same folder) and fill in your own values.
 * secrets.h is git-ignored (see sensor-node/.gitignore) - never commit it.
 * The values below are placeholders, not real credentials.
 */
#ifndef PCD_SECRETS_H
#define PCD_SECRETS_H

/* The 2.4 GHz Wi-Fi network the node joins (the ESP32 cannot use 5 GHz). */
#define PCD_WIFI_SSID "your-wifi-name"
#define PCD_WIFI_PASSWORD "your-wifi-password"

/* The computer running the receiver. An IPv4 address, not a host name: a DNS
 * lookup can stall the loop for seconds when the network is flaky.
 * 192.0.2.10 is a documentation-only address and will not reach anything. */
#define PCD_RECEIVER_IP "192.0.2.10"
#define PCD_RECEIVER_PORT 9750

#endif /* PCD_SECRETS_H */
