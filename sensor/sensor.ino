#include "SR04.h"
#include <LiquidCrystal_I2C.h>
#include <SimpleDHT.h>
#include <Wire.h>


// ******************************
// PIN
// ******************************
#define TRIG_PIN 12
#define ECHO_PIN 11
#define DHT_PIN 2

// ******************************
// Setting
// ******************************
#define DELAY_MILISEC 1000  // 1秒
#define lightDuration 10000 // 10秒
#define DISTANCE_DISPLAY 50 //この距離(cm)以内の場合にdisplayを表示する
#define DISTANCE_MAX 999    //この距離以上のものはMAXに抑える
unsigned long lastDisplayTriggerTime = 0;


// ******************************
// init
// ******************************
LiquidCrystal_I2C lcd(0x27, 16, 2);
SimpleDHT11 dht11;
SR04 sr04 = SR04(ECHO_PIN, TRIG_PIN);



// ******************************
// Humidity and Temperature
// ******************************
byte temperature = 0;
byte humidity = 0;

void check_HT() {
  byte data[40] = {0};
  if (dht11.read(DHT_PIN, &temperature, &humidity, data)) {
    Serial.println("Read DHT11 failed");
    temperature = 0;
    humidity = 0;
    return;
  }
}
/*
String get_checked_HT() {
  return "Temp: " + String((int)temperature) + "C, Humi: " + String((int)humidity) + "%";
}
*/


// ******************************
// Distance
// ******************************
long distance = 0;

void check_distance() {
  distance = sr04.Distance();
  if( distance > DISTANCE_MAX ){
    distance = DISTANCE_MAX;
  }
  // TODO: エラーチェック
}
/*
String get_checked_distance() {
  return "Distance: " + String(distance) + " cm";
}
*/

// ******************************
// LCD 表示
// ******************************
void print_as_lcd() {
  unsigned long currentMillis = millis();

  if (distance < DISTANCE_DISPLAY) {
    lastDisplayTriggerTime = currentMillis;
  }

  if (currentMillis - lastDisplayTriggerTime < lightDuration) {
    lcd.backlight();

    // 1行目：温度・湿度
    lcd.setCursor(0, 0);
    lcd.print("                ");  // 行を消す
    lcd.setCursor(0, 0);
    lcd.print("T:");
    lcd.print(temperature);
    lcd.write((char)223);           //°
    lcd.print("C H:");
    lcd.print(humidity);
    lcd.print("%");

    // 2行目：距離
    lcd.setCursor(0, 1);
    lcd.print("                ");  // 行を消す
    lcd.setCursor(0, 1);
    lcd.print("D:");
    lcd.print(distance);
    lcd.print("cm");
  } else {
    lcd.noBacklight();
  }
}

// ******************************
// Serial 表示
// ******************************
void print_as_serial() {
  /*
  Serial.print("T:");
  Serial.print(temperature);
  Serial.print("C H:");
  Serial.print(humidity);
  Serial.print("% D:");
  Serial.print(distance);
  Serial.println("cm");
  */
  // prometheus textfile exporterでそのまま使えるように。
  Serial.println("# HELP arduino_temperature_celsius Temperature from DHT11 in Celsius");
  Serial.println("# TYPE arduino_temperature_celsius gauge");
  Serial.print("arduino_temperature_celsius ");
  Serial.println(temperature);

  Serial.println("# HELP arduino_humidity_percent Humidity from DHT11");
  Serial.println("# TYPE arduino_humidity_percent gauge");
  Serial.print("arduino_humidity_percent ");
  Serial.println(humidity);

  Serial.println("# HELP arduino_distance_cm Distance from ultrasonic sensor");
  Serial.println("# TYPE arduino_distance_cm gauge");
  Serial.print("arduino_distance_cm ");
  Serial.println(distance);
}

// ******************************
// メイン処理
// ******************************
void check_data() {
  check_HT();
  check_distance();
}

void print_checked_data() {
  print_as_lcd();
  print_as_serial();
}

void setup() {
  lcd.init();
  lcd.noBacklight();
  Serial.begin(9600);
  delay(1000);
}

void loop() {
  check_data();
  print_checked_data();
  delay(DELAY_MILISEC);
}
