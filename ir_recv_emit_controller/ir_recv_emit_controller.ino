#define DATA_BUFF 600
#define DECODE_NEC
#define RAW_BUFFER_LENGTH DATA_BUFF
// エアコンなど情報量が多いものはいっぱい(750以上)必要。デフォルトは200。
#define ENABLE_LED_FEEDBACK false
// #define DECODE_DENON

#include <Arduino.h>
#include <ArduinoJson.h>
#include <IRremote.hpp> // IRremote v4.4.2
// IRremoteと呼ばれるライブラリが存在しているためそれを使うのが定石ですが,
// ある一定の長さ以上の信号を解析できない制約があり,
// 以下に解析した家電の中ではエアコンの信号は解析できません.。らしい。https://qiita.com/awawaInu/items/25c6e17fcc2e655d5d42

const uint8_t RECV_PIN = 11;                  // IR受信ピン
const uint8_t IR_SEND_PIN = 8;                // IR送信ピン
const uint8_t LED_FEEDBACK_PIN = LED_BUILTIN; // フィードバック用LED
const int IR_SEND_REPEAT_NUM = 10;

IRData last_ir_data; // 最後に受信したIRデータ

void setup() {
  Serial.begin(9600);
  Serial.println("IR Receiver & Sender Ready (IRremote v4.x)");

  // 受信初期化
  IrReceiver.begin(RECV_PIN, ENABLE_LED_FEEDBACK);
  IrSender.begin(IR_SEND_PIN, ENABLE_LED_FEEDBACK, LED_FEEDBACK_PIN);

  // Pin初期化
  pinMode(RECV_PIN, INPUT);
  pinMode(IR_SEND_PIN, OUTPUT);
  digitalWrite(RECV_PIN, HIGH);
  digitalWrite(IR_SEND_PIN, HIGH);
}

unsigned long loopCount = 0;

void loop() {
  delay(10);
  loopCount++;
  if (loopCount % 500 == 0) {
    IRData testData;

    /*
    // Debug用
    // if
    //
    (json2IRData("{\"protocol\":8,\"address\":57152,\"command\":20,\"extra\":0,\"bits\":32,\"flags\":0,\"raw\":3944013632}",
    //  testData)) { 電源削除
      if(
        // TV電源を消す
        //
      json2IRData("{\"protocol\":8,\"address\":57152,\"command\":12,\"extra\":0,\"bits\":32,\"flags\":0,\"raw\":4077707072}",testData)
        // プロジェクター電源
        json2IRData("{\"protocol\":8,\"address\":0,\"command\":168,\"extra\":0,\"bits\":32,\"flags\":0,\"raw\":1470693120}",
      testData)
      ){
        //sendIrData(testData);
        //IrSender.sendNEC(0x0, 0xA8, IR_SEND_REPEAT_NUM);
      } else {
        Serial.println("Failed to parse JSON IR data.");
      }

      //testData.protocol = NEC;  // NECプロトコル (decode_type_t の列挙値)
      //testData.address = 57152; // 例: アドレス 0xDF60
      //testData.command = 12;    // 例: コマンド 0x0C
      //testData.extra = 0;       // 使わない場合は 0
      //testData.decodedRawData =
      //    0xF30C0C00; // NEC用の32ビットデータ
      (例、適切な値に変更してください)
      //testData.numberOfBits = 32; // NECの標準ビット長
      //testData.flags = 0;         // フラグなし
      //testData.rawlen = 0;        //
      受信に関係するので送信には不要（安全に0でOK）
      //testData.initialGapTicks = 0;  // 同上
      //testData.rawDataPtr = nullptr; // 送信には使わないので nullでOK
      sendIrData(testData);
    */
  }
  // IrSender.sendNEC(0x20DF10EF, 32); // 例：NECフォーマット、パワーボタン

  // 赤外線受信チェック
  if (IrReceiver.decode()) {
    IrReceiver.resume();

    if (!(IrReceiver.decodedIRData.flags & IRDATA_FLAGS_IS_REPEAT) &&
        !(IrReceiver.decodedIRData.address == 0 &&
          IrReceiver.decodedIRData.command == 0)) {
      // if (true) {
      last_ir_data = IrReceiver.decodedIRData;

      // Serial.print("Received IR Code: 0x");
      // printProtocol(last_ir_data.protocol);
      // Serial.println("Received: ");
      // Serial.println(last_ir_data.decodedRawData, HEX);
      // Serial.println("Received: " + irData2Json(last_ir_data));
      Serial.println("IR Receive: " + irData2Json(last_ir_data));
      // printIRResultShort(&Serial, &last_ir_data, false);
      // IrReceiver.printIRSendUsage(&Serial);

      // IrReceiver.printIRSendUsage(&Serial);
      // IrReceiver.printIRResultRawFormatted(&Serial, true); //
      // RAWフォーマットで結果を表示
      // IrReceiver.compensateAndPrintIRResultAsCArray(&Serial, true);
    }
  }

  // シリアルから送信要求
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (input.startsWith("SEND ")) {
      String jsonStr = input.substring(5);
      IRData irDataSend;
      bool ok = json2IRData(jsonStr, irDataSend);
      if (ok) {
        sendIrData(irDataSend);
      } else {
        Serial.println("Failed to parse IR JSON: " + jsonStr);
      }
    }
  }
}

void sendIrData(IRData irDataSend) {
  // IrReceiver.stop();
  Serial.println("IR Sending:: " + irData2Json(irDataSend));
  // IrSender.write(&irDataSend);
  // IrSender.sendNEC(irDataSend.address, irDataSend.command, 3);

  switch (irDataSend.protocol) {
  case NEC:
    IrSender.sendNEC(irDataSend.address, irDataSend.command,
                     IR_SEND_REPEAT_NUM); // 本体信号のみ
    break;
  case SONY:
    IrSender.sendSony(irDataSend.command, irDataSend.numberOfBits);
    break;
  // 他のプロトコルも必要に応じて追加
  default:
    Serial.println("Unsupported protocol for direct send.");
  }
  return;
}

String irData2Json(const IRData &data) {
  StaticJsonDocument<600> doc;

  doc["protocol"] = (uint8_t)data.protocol; //(uint8_t)data.protocol;
  doc["address"] = data.address;
  doc["command"] = data.command;
  doc["extra"] = data.extra;
  doc["bits"] = data.numberOfBits;
  doc["flags"] = data.flags;
  doc["raw"] = data.decodedRawData;

  String jsonStr;
  serializeJson(doc, jsonStr);
  return jsonStr;
}
bool json2IRData(const String &jsonStr, IRData &data) {
  StaticJsonDocument<DATA_BUFF> doc;
  DeserializationError error = deserializeJson(doc, jsonStr);
  if (error) {
    Serial.print("deserializeJson failed: ");
    Serial.println(error.f_str());
    return false;
  }

  data.protocol = (decode_type_t)doc["protocol"];
  data.address = doc["address"];
  data.command = doc["command"];
  data.extra = doc["extra"];
  data.numberOfBits = doc["bits"];
  data.flags = doc["flags"];
  data.decodedRawData = doc["raw"];

  return true;
}
