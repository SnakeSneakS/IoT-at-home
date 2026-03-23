#include <Arduino.h>
#include <IRremote.hpp>

#define RAW_BUFFER_LENGTH 800

const uint8_t RECV_PIN = 11;
const uint8_t IR_SEND_PIN = 8;

void setup() {
  Serial.begin(9200);
  Serial.println("IR BRIDGE READY");

  IrReceiver.begin(RECV_PIN, false);
  IrSender.begin(IR_SEND_PIN, false);
}

void loop() {

  // ===== 受信 =====
  if (IrReceiver.decode()) {

    uint16_t len = IrReceiver.decodedIRData.rawlen;
    Serial.println("RECV_IR ");
    Serial.println("===RAW_START===");

    Serial.print("LEN:");
    Serial.println(len);

    Serial.print("DATA:");

    for (uint16_t i = 0; i < len; i++) {
      uint16_t val = IrReceiver.irparams.rawbuf[i] * MICROS_PER_TICK;
      Serial.print(val);

      if (i != len - 1) {
        Serial.print(",");
      }
    }

    Serial.println();
    Serial.println("===RAW_END===");

    IrReceiver.resume();
  }

  // ===== 送信 =====
  if (Serial.available()) {

    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.startsWith("SEND_IR ")) {

      String dataStr = line.substring(8);

      uint16_t raw[RAW_BUFFER_LENGTH];
      uint16_t index = 0;

      char buffer[2000];
      dataStr.toCharArray(buffer, sizeof(buffer));

      char *token = strtok(buffer, ",");

      while (token != NULL && index < RAW_BUFFER_LENGTH) {
        raw[index++] = atoi(token);
        token = strtok(NULL, ",");
      }

      Serial.println("SENDING...");
      IrSender.sendRaw(raw, index, 38);
      Serial.println("DONE");
    }
  }
}