#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <vector>
#include <algorithm>
#include <math.h>
#include <ctype.h>

// Dieu khien ray truot bang ESP32 va BLE.
// ESP32 nhan cau hinh tu Pi4, di chuyen den tung vi tri quet va gui trang thai ve Pi4.

// Chan ket noi driver dong co va cong tac hanh trinh.
#define STEP_PIN      18
#define DIR_PIN       5
#define LIMIT_LEFT    19
#define LIMIT_RIGHT   22
#define ENABLE_PIN    -1   // -1 neu driver khong dung chan EN

// Thong so co khi can hieu chinh theo ray truot thuc te.
static const float STEPS_PER_CM         = 55.0f;
static const uint32_t STEP_PULSE_US     = 1200;
static const long HOME_RELEASE_STEPS    = 55;
static const long LIMIT_RELEASE_MAX_STEPS = 500;
static const float MAX_LENGTH_CM        = 81.0f;
static const float CAM_OFFSET_CM        = 4.0f;
static const uint32_t HOMING_TIMEOUT_MS = 60000;
static const uint32_t NEXT_TIMEOUT_MS   = 0;      // 0 la cho Pi4 gui NEXT, khong tu chay tiep
static const float ARRIVE_EPS_CM        = 0.05f;

// UUID BLE cho kenh nhan lenh va gui trang thai.
static BLEUUID SVC_UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E");
static BLEUUID CMD_UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E");
static BLEUUID STA_UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E");

static BLEServer* g_server = nullptr;
static BLECharacteristic* g_cmdChr = nullptr;
static BLECharacteristic* g_staChr = nullptr;
static bool bleConnected = false;

// Cau hinh lich quet nhan tu Pi4.
struct RailConfig {
  int version = 0;
  int numScans = 1;
  int intervalMinutes = 0;
  char mode = 'S';
  std::vector<float> positions;
};

static RailConfig g_cfg;
static bool cfgReady = false;

// Cac trang thai van hanh cua ray.
enum RailState {
  RS_IDLE = 0,
  RS_READY,
  RS_MOVING,
  RS_WAIT_NEXT,
  RS_WAIT_INTERVAL,
  RS_PAUSED,
  RS_COMPLETE,
  RS_STOPPED,
  RS_ERROR
};

static RailState g_state = RS_IDLE;
static std::vector<float> g_route;
static std::vector<int> g_passEndIndices;
static int g_routeIndex = -1;
static float g_currentTargetCm = 0.0f;
static float g_lastArrivedCm = -9999.0f;
static uint32_t waitNextStartedMs = 0;
static uint32_t waitIntervalStartedMs = 0;
static uint32_t lastStatusRepeatMs = 0;
static bool currentDirPositive = true;

// Bien vi tri hien tai va vi tri dich tinh theo so buoc.
static volatile long currentSteps = 0;
static long targetSteps = 0;
static uint32_t lastStepUs = 0;

// Luu trang thai de tam dung va tiep tuc dung vi tri.
static bool g_pauseLatched = false;
static RailState g_pauseFromState = RS_IDLE;
static uint32_t g_intervalResumeWaitMs = 0;

// Bo dem nhan lenh BLE theo tung dong.
static const size_t MAX_CMD_LINE_LENGTH = 512;
static String rxLine = "";
static bool rxOverflow = false;

static inline void motorEnable(bool en) {
  if (ENABLE_PIN >= 0) digitalWrite(ENABLE_PIN, en ? LOW : HIGH);
}

static inline bool isPressedFast(int pin) {
  return digitalRead(pin) == LOW;
}

// Loc doi cong tac hanh trinh bang cach doc on dinh nhieu lan.
static bool isPressedStable(int pin) {
  if (!isPressedFast(pin)) return false;
  for (int i = 0; i < 50; ++i) {
    if (!isPressedFast(pin)) return false;
    delayMicroseconds(10);
  }
  return true;
}

static void pulseStepOnce() {
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(STEP_PULSE_US);
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(STEP_PULSE_US);
}

static float stepsToCm(long s) {
  return (float)s / STEPS_PER_CM;
}

// Doi toa do quet cua camera sang so buoc cua ray, co bu CAM_OFFSET_CM.
static long cmToSteps(float cm) {
  if (cm < 0.0f) cm = 0.0f;
  if (cm > MAX_LENGTH_CM) cm = MAX_LENGTH_CM;

  float railCm = cm - CAM_OFFSET_CM;
  if (railCm < 0.0f) railCm = 0.0f;
  if (railCm > MAX_LENGTH_CM) railCm = MAX_LENGTH_CM;

  return lroundf(railCm * STEPS_PER_CM);
}

static void setDirectionToTarget(long dst) {
  currentDirPositive = (dst >= currentSteps);
  digitalWrite(DIR_PIN, currentDirPositive ? HIGH : LOW);
}

// Gui trang thai qua Serial va BLE notify de Pi4 theo doi tien trinh.
static void notifyText(const String& s) {
  Serial.println(s);
  if (!bleConnected || !g_staChr) return;
  g_staChr->setValue(s.c_str());
  g_staChr->notify();
}

static void clearPauseLatch() {
  g_pauseLatched = false;
  g_pauseFromState = RS_IDLE;
  g_intervalResumeWaitMs = 0;
}

static void resetRuntimeFlags() {
  g_route.clear();
  g_passEndIndices.clear();
  g_routeIndex = -1;
  g_currentTargetCm = stepsToCm(currentSteps);
  g_lastArrivedCm = stepsToCm(currentSteps);
  waitNextStartedMs = 0;
  waitIntervalStartedMs = 0;
  targetSteps = currentSteps;
  clearPauseLatch();
}

static void pauseAndReport() {
  g_pauseLatched = true;
  g_pauseFromState = g_state;
  if (g_pauseFromState == RS_WAIT_INTERVAL) {
    uint32_t fullWaitMs = (uint32_t)g_cfg.intervalMinutes * 60000UL;
    uint32_t elapsed = millis() - waitIntervalStartedMs;
    g_intervalResumeWaitMs = (elapsed >= fullWaitMs) ? 0 : (fullWaitMs - elapsed);
  } else {
    g_intervalResumeWaitMs = 0;
  }

  g_state = RS_PAUSED;
  motorEnable(false);
  notifyText("PAUSED");
}

static void stopAndReport(const String& reason) {
  g_state = RS_STOPPED;
  resetRuntimeFlags();
  motorEnable(false);
  notifyText(reason);
}

static void handleRightLimit() {
  Serial.println("[SAFE] RIGHT limit");
  digitalWrite(DIR_PIN, LOW);

  long releaseSteps = 0;
  while (digitalRead(LIMIT_RIGHT) == LOW && releaseSteps < LIMIT_RELEASE_MAX_STEPS) {
    pulseStepOnce();
    ++releaseSteps;
  }

  if (digitalRead(LIMIT_RIGHT) == LOW) {
    g_state = RS_ERROR;
    motorEnable(false);
    notifyText("ERROR:RIGHT_LIMIT_STUCK");
    return;
  }

  for (int i = 0; i < 160; ++i) pulseStepOnce();
  currentSteps -= 160;
  targetSteps = currentSteps;
  stopAndReport("ESTOP:RIGHT_LIMIT");
}

static void handleLeftLimit() {
  Serial.println("[SAFE] LEFT limit");
  digitalWrite(DIR_PIN, HIGH);

  long releaseSteps = 0;
  while (digitalRead(LIMIT_LEFT) == LOW && releaseSteps < LIMIT_RELEASE_MAX_STEPS) {
    pulseStepOnce();
    ++releaseSteps;
  }

  if (digitalRead(LIMIT_LEFT) == LOW) {
    g_state = RS_ERROR;
    motorEnable(false);
    notifyText("ERROR:LEFT_LIMIT_STUCK");
    return;
  }

  for (int i = 0; i < HOME_RELEASE_STEPS; ++i) pulseStepOnce();
  currentSteps = 0;
  targetSteps = 0;
  stopAndReport("ESTOP:LEFT_LIMIT");
}

// Dua ray ve cong tac trai de lay moc vi tri 0.
static bool homeToLeft() {
  Serial.println("[HOME] start -> ve cam bien trai");
  motorEnable(true);
  digitalWrite(DIR_PIN, LOW);

  uint32_t t0 = millis();
  while (!isPressedStable(LIMIT_LEFT)) {
    pulseStepOnce();
    if (millis() - t0 > HOMING_TIMEOUT_MS) {
      Serial.println("[HOME] timeout");
      motorEnable(false);
      return false;
    }
  }

  Serial.println("[HOME] touched LEFT");

  digitalWrite(DIR_PIN, HIGH);
  for (long i = 0; i < HOME_RELEASE_STEPS; ++i) pulseStepOnce();

  if (isPressedStable(LIMIT_LEFT)) {
    Serial.println("[HOME] LEFT limit did not release");
    motorEnable(false);
    return false;
  }

  currentSteps = 0;
  targetSteps = 0;
  motorEnable(false);
  Serial.printf("[HOME] done, released LEFT by %ld steps, current=0\n", HOME_RELEASE_STEPS);
  return true;
}

static void applyConfig(const RailConfig& cfg) {
  g_cfg = cfg;
  cfgReady = true;

  Serial.printf("[CFG] version=%d scans=%d interval=%d mode=%c pos=",
                g_cfg.version, g_cfg.numScans, g_cfg.intervalMinutes, g_cfg.mode);
  for (size_t i = 0; i < g_cfg.positions.size(); ++i) {
    Serial.print(g_cfg.positions[i], 1);
    if (i + 1 < g_cfg.positions.size()) Serial.print(",");
  }
  Serial.println();
}

static bool samePositions(const RailConfig& a, const RailConfig& b) {
  if (a.positions.size() != b.positions.size()) return false;
  for (size_t i = 0; i < a.positions.size(); ++i) {
    if (fabsf(a.positions[i] - b.positions[i]) > ARRIVE_EPS_CM) return false;
  }
  return true;
}

static int totalPassCount(const RailConfig& cfg) {
  return cfg.numScans;
}

static int completedPassCount() {
  int done = 0;
  for (size_t i = 0; i < g_passEndIndices.size(); ++i) {
    if (g_passEndIndices[i] <= g_routeIndex) ++done;
  }
  return done;
}

static void appendPath(std::vector<float>& out, bool ascending);

// Phan tich lenh cau hinh dang C:V,so_luot,khoang_nghi,che_do,vi_tri.
static bool parseConfigCmd(const String& payload, RailConfig& out) {
  if (!payload.startsWith("C:")) return false;

  RailConfig tmp;
  String body = payload.substring(2);
  body.trim();
  if (!body.length()) return false;

  std::vector<String> parts;
  int start = 0;
  while (true) {
    int comma = body.indexOf(',', start);
    if (comma < 0) {
      parts.push_back(body.substring(start));
      break;
    }
    parts.push_back(body.substring(start, comma));
    start = comma + 1;
  }

  size_t base = 0;
  tmp.version = 0;

  if (!parts.empty()) {
    String t0 = parts[0];
    t0.trim();
    if (t0.length() >= 2 && (t0[0] == 'V' || t0[0] == 'v')) {
      tmp.version = t0.substring(1).toInt();
      base = 1;
    }
  }

  if (parts.size() < base + 4) return false;

  tmp.numScans = parts[base + 0].toInt();
  tmp.intervalMinutes = parts[base + 1].toInt();
  // Truong mode duoc giu de tuong thich command cu, nhung firmware chi dung quet mot chieu.
  tmp.mode = 'S';
  if (tmp.numScans <= 0) tmp.numScans = 1;
  if (tmp.intervalMinutes < 0) tmp.intervalMinutes = 0;

  tmp.positions.clear();
  for (size_t i = base + 3; i < parts.size(); ++i) {
    String t = parts[i];
    t.trim();
    if (!t.length()) continue;
    float cm = t.toFloat();
    if (cm < 0.0f || cm > MAX_LENGTH_CM) return false;
    tmp.positions.push_back(cm);
  }
  if (tmp.positions.empty()) return false;

  std::sort(tmp.positions.begin(), tmp.positions.end());
  std::vector<float> compact;
  for (float p : tmp.positions) {
    if (compact.empty() || fabsf(p - compact.back()) > ARRIVE_EPS_CM) compact.push_back(p);
  }
  tmp.positions = compact;

  out = tmp;
  return true;
}

static void rebuildRemainingRouteFromWaitingBoundary() {
  int donePasses = completedPassCount();
  int totalPasses = totalPassCount(g_cfg);
  int remainingPasses = totalPasses - donePasses;

  g_route.clear();
  g_passEndIndices.clear();
  g_routeIndex = -1;

  if (remainingPasses <= 0) {
    Serial.printf("[ROUTE] boundary reconfig -> no remaining pass (done=%d total=%d)\n",
                  donePasses, totalPasses);
    return;
  }

  float first = g_cfg.positions.front();
  float last = g_cfg.positions.back();

  bool nextAscending;
  if (fabsf(g_lastArrivedCm - first) <= ARRIVE_EPS_CM) {
    nextAscending = true;
  } else if (fabsf(g_lastArrivedCm - last) <= ARRIVE_EPS_CM) {
    nextAscending = false;
  } else {
    float nowCm = stepsToCm(currentSteps);
    float mid = (first + last) * 0.5f;
    nextAscending = (nowCm <= mid);
  }

  for (int i = 0; i < remainingPasses; ++i) {
    appendPath(g_route, nextAscending);
    g_passEndIndices.push_back((int)g_route.size() - 1);
    nextAscending = !nextAscending;
  }

  Serial.printf("[ROUTE] rebuilt remaining count=%d -> ", (int)g_route.size());
  for (size_t i = 0; i < g_route.size(); ++i) {
    Serial.print(g_route[i], 1);
    if (i + 1 < g_route.size()) Serial.print(" -> ");
  }
  Serial.println();
}

static void appendPath(std::vector<float>& out, bool ascending) {
  if (ascending) {
    for (float p : g_cfg.positions) {
      if (out.empty() || fabsf(out.back() - p) > ARRIVE_EPS_CM) out.push_back(p);
    }
  } else {
    for (int i = (int)g_cfg.positions.size() - 1; i >= 0; --i) {
      float p = g_cfg.positions[i];
      if (out.empty() || fabsf(out.back() - p) > ARRIVE_EPS_CM) out.push_back(p);
    }
  }
}

static bool chooseStartAscending() {
  float currentCm = stepsToCm(currentSteps);
  float first = g_cfg.positions.front();
  float last = g_cfg.positions.back();
  float mid = (first + last) * 0.5f;

  if (currentCm <= first + ARRIVE_EPS_CM) return true;
  if (currentCm >= last - ARRIVE_EPS_CM) return false;
  return currentCm <= mid;
}

// Tao lo trinh quet mot chieu. Moi luot sau dao chieu de bat dau tu dau ray hien tai.
static void buildRoute() {
  g_route.clear();
  g_passEndIndices.clear();
  bool dir = chooseStartAscending();

  for (int i = 0; i < g_cfg.numScans; ++i) {
    appendPath(g_route, dir);
    g_passEndIndices.push_back((int)g_route.size() - 1);
    dir = !dir;
  }

  g_routeIndex = -1;
  Serial.printf("[ROUTE] count=%d -> ", (int)g_route.size());
  for (size_t i = 0; i < g_route.size(); ++i) {
    Serial.print(g_route[i], 1);
    if (i + 1 < g_route.size()) Serial.print(" -> ");
  }
  Serial.println();
}

static bool resumeMovingTarget() {
  if (targetSteps == currentSteps) return false;
  g_state = RS_MOVING;
  setDirectionToTarget(targetSteps);
  motorEnable(true);
  notifyText("MOVING:" + String(g_currentTargetCm, 1));
  return true;
}

static bool resumePausedState() {
  if (!g_pauseLatched) return false;

  RailState from = g_pauseFromState;
  uint32_t savedWaitMs = g_intervalResumeWaitMs;
  clearPauseLatch();

  if (from == RS_MOVING) {
    if (resumeMovingTarget()) {
      Serial.println("[RESUME] continue moving to current target");
      return true;
    }
    from = RS_WAIT_NEXT;
  }

  if (from == RS_WAIT_NEXT) {
    g_state = RS_WAIT_NEXT;
    motorEnable(false);
    waitNextStartedMs = millis();
    g_lastArrivedCm = g_currentTargetCm;
    notifyText("ARRIVED:" + String(g_currentTargetCm, 1));
    Serial.println("[RESUME] back to WAIT_NEXT");
    return true;
  }

  if (from == RS_WAIT_INTERVAL) {
    g_state = RS_WAIT_INTERVAL;
    motorEnable(false);
    g_intervalResumeWaitMs = savedWaitMs;
    if (g_intervalResumeWaitMs == 0) {
      g_intervalResumeWaitMs = (uint32_t)g_cfg.intervalMinutes * 60000UL;
    }
    waitIntervalStartedMs = millis();
    notifyText("INTERVAL_WAIT");
    Serial.println("[RESUME] back to WAIT_INTERVAL");
    return true;
  }

  return false;
}

static bool isEndOfPassIndex(int idx) {
  for (size_t i = 0; i < g_passEndIndices.size(); ++i) {
    if (g_passEndIndices[i] == idx) return true;
  }
  return false;
}

static bool hasMoreAfterIndex(int idx) {
  return idx + 1 < (int)g_route.size();
}

static void beginMoveTo(float cm) {
  g_currentTargetCm = cm;
  targetSteps = cmToSteps(cm);
  setDirectionToTarget(targetSteps);
  g_state = RS_MOVING;
  motorEnable(true);

  Serial.printf("[MOVE] %.1f -> targetSteps=%ld current=%ld\n", cm, targetSteps, currentSteps);
  notifyText("MOVING:" + String(cm, 1));

  if (targetSteps == currentSteps) {
    motorEnable(false);
    g_state = RS_WAIT_NEXT;
    g_lastArrivedCm = cm;
    waitNextStartedMs = millis();
    notifyText("ARRIVED:" + String(cm, 1));
  }
}

static void advanceRoute() {
  if (g_routeIndex + 1 >= (int)g_route.size()) {
    g_state = RS_COMPLETE;
    motorEnable(false);
    notifyText("COMPLETE");
    return;
  }

  ++g_routeIndex;
  beginMoveTo(g_route[g_routeIndex]);
}

static void startRun() {
  if (!cfgReady) {
    notifyText("ERROR:CFG_MISSING");
    return;
  }

  clearPauseLatch();
  buildRoute();
  if (g_route.empty()) {
    notifyText("ERROR:ROUTE_EMPTY");
    return;
  }

  Serial.println("[CMD] START");
  advanceRoute();
}

static void beginIntervalWaitIfNeeded() {
  if (!hasMoreAfterIndex(g_routeIndex)) {
    g_state = RS_COMPLETE;
    motorEnable(false);
    notifyText("COMPLETE");
    return;
  }

  if (g_cfg.intervalMinutes > 0 && isEndOfPassIndex(g_routeIndex)) {
    g_state = RS_WAIT_INTERVAL;
    waitIntervalStartedMs = millis();
    motorEnable(false);
    Serial.printf("[WAIT_INTERVAL] %d minute(s)\n", g_cfg.intervalMinutes);
    notifyText("INTERVAL_WAIT");
    return;
  }

  advanceRoute();
}

// Xu ly cac lenh BLE gom CONFIG, START, NEXT, PAUSE, RESUME va STOP.
static void processCommand(const String& raw) {
  String cmd = raw;
  cmd.trim();
  if (!cmd.length()) return;

  Serial.println("[BLE RX] " + cmd);

  if (cmd == "PAUSE") {
    if (g_state == RS_MOVING || g_state == RS_WAIT_NEXT || g_state == RS_WAIT_INTERVAL) {
      pauseAndReport();
    } else if (g_state == RS_PAUSED) {
      notifyText("PAUSED");
    } else {
      notifyText("ERROR:PAUSE_WHEN_NOT_RUNNING");
    }
    return;
  }

  if (cmd == "STOP") {
    stopAndReport("STOPPED");
    return;
  }

  if (cmd.startsWith("C:")) {
    RailConfig incoming;
    if (!parseConfigCmd(cmd, incoming)) {
      notifyText("ERROR:BAD_CONFIG");
      return;
    }

    if (cfgReady && incoming.version == g_cfg.version) {
      Serial.printf("[CFG] duplicate version=%d -> ignore\n", incoming.version);
      notifyText("CONFIG_OK");
      return;
    }

    if (g_state == RS_WAIT_INTERVAL) {
      if (cfgReady && !samePositions(incoming, g_cfg)) {
        Serial.println("[CFG] positions changed during WAIT_INTERVAL -> reject");
        notifyText("ERROR:POS_CHANGE_DURING_WAIT");
        return;
      }

      applyConfig(incoming);
      rebuildRemainingRouteFromWaitingBoundary();
      notifyText("CONFIG_OK");
      return;
    }

    if (g_state == RS_MOVING || g_state == RS_WAIT_NEXT || g_state == RS_PAUSED) {
      stopAndReport("ESTOP:RECONFIG");
      return;
    }

    applyConfig(incoming);
    g_state = RS_READY;
    notifyText("CONFIG_OK");
    return;
  }

  if (cmd == "START") {
    if (g_state == RS_ERROR) {
      notifyText("ERROR:HOMING_REQUIRED");
      return;
    }

    if (!cfgReady) {
      notifyText("ERROR:NO_CONFIG");
      return;
    }

    startRun();
    return;
  }

  if (cmd == "RESUME") {
    if (!cfgReady) {
      notifyText("ERROR:NO_CONFIG");
      return;
    }
    if (!resumePausedState()) {
      notifyText("ERROR:NOT_PAUSED");
    }
    return;
  }

  if (cmd == "NEXT") {
    if (g_state == RS_WAIT_NEXT) {
      Serial.println("[CMD] NEXT -> continue");
      beginIntervalWaitIfNeeded();
    } else if (g_state == RS_WAIT_INTERVAL) {
      Serial.println("[CMD] NEXT -> skip interval and continue");
      advanceRoute();
    } else {
      notifyText("ERROR:NEXT_WHEN_NOT_WAITING");
    }
    return;
  }

  notifyText("ERROR:UNKNOWN_CMD");
}

class ServerCB : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    bleConnected = true;
    lastStatusRepeatMs = 0;
    Serial.println("[BLE] client connected");
  }

  void onDisconnect(BLEServer* pServer) override {
    bleConnected = false;
    lastStatusRepeatMs = 0;
    Serial.println("[BLE] client disconnected -> advertising again");
    pServer->getAdvertising()->start();
  }
};

class CmdCB : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pChr) override {
    String v = pChr->getValue();
    if (v.length() == 0) return;

    for (size_t i = 0; i < v.length(); ++i) {
      char c = v[i];
      if (c == '\r') continue;
      if (c == '\n') {
        if (!rxOverflow) processCommand(rxLine);
        rxLine = "";
        rxOverflow = false;
      } else if (!rxOverflow) {
        rxLine += c;
        if (rxLine.length() > MAX_CMD_LINE_LENGTH) {
          rxLine = "";
          rxOverflow = true;
          notifyText("ERROR:CMD_TOO_LONG");
        }
      }
    }
  }
};

// Khoi tao BLE service, characteristic nhan lenh va characteristic gui trang thai.
static void initBLE() {
  BLEDevice::init("TomatoRail-ESP32");
  g_server = BLEDevice::createServer();
  g_server->setCallbacks(new ServerCB());

  BLEService* svc = g_server->createService(SVC_UUID);

  g_cmdChr = svc->createCharacteristic(
    CMD_UUID,
    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR
  );
  g_cmdChr->setCallbacks(new CmdCB());

  g_staChr = svc->createCharacteristic(
    STA_UUID,
    BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
  );
  g_staChr->addDescriptor(new BLE2902());
  g_staChr->setValue("BOOTING");

  svc->start();
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SVC_UUID);
  adv->setScanResponse(true);
  adv->start();

  Serial.println("[BLE] advertising as TomatoRail-ESP32");
}

// Tao xung STEP theo tung vong loop va dung khi toi vi tri dich.
static void handleMotion() {
  if (g_state != RS_MOVING) return;

  if (currentDirPositive && isPressedStable(LIMIT_RIGHT)) {
    handleRightLimit();
    return;
  }
  if (!currentDirPositive && isPressedStable(LIMIT_LEFT)) {
    handleLeftLimit();
    return;
  }

  uint32_t nowUs = micros();
  if ((uint32_t)(nowUs - lastStepUs) < (STEP_PULSE_US * 2)) return;
  lastStepUs = nowUs;

  digitalWrite(DIR_PIN, currentDirPositive ? HIGH : LOW);
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(STEP_PULSE_US);
  digitalWrite(STEP_PIN, LOW);

  currentSteps += currentDirPositive ? 1 : -1;

  if (currentSteps == targetSteps) {
    motorEnable(false);
    g_state = RS_WAIT_NEXT;
    g_lastArrivedCm = g_currentTargetCm;
    waitNextStartedMs = millis();
    notifyText("ARRIVED:" + String(g_currentTargetCm, 1));
  }
}

// Xu ly khoang nghi giua cac luot quet neu co cau hinh intervalMinutes.
static void handleIntervalWait() {
  if (g_state != RS_WAIT_INTERVAL) return;
  uint32_t waitMs = g_intervalResumeWaitMs ? g_intervalResumeWaitMs : ((uint32_t)g_cfg.intervalMinutes * 60000UL);
  if (waitMs == 0 || millis() - waitIntervalStartedMs >= waitMs) {
    g_intervalResumeWaitMs = 0;
    Serial.println("[WAIT_INTERVAL] done -> continue");
    advanceRoute();
  }
}

static void repeatStatusIfNeeded() {
  if (!bleConnected) return;
  if (millis() - lastStatusRepeatMs < 1000) return;
  lastStatusRepeatMs = millis();

  if (g_state == RS_IDLE || g_state == RS_READY) {
    notifyText("READY");
  } else if (g_state == RS_PAUSED) {
    notifyText("PAUSED");
  } else if (g_state == RS_STOPPED) {
    notifyText("STOPPED");
  } else if (g_state == RS_WAIT_NEXT) {
    notifyText("ARRIVED:" + String(g_lastArrivedCm, 1));
  } else if (g_state == RS_WAIT_INTERVAL) {
    notifyText("INTERVAL_WAIT");
  } else if (g_state == RS_COMPLETE) {
    notifyText("COMPLETE");
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(LIMIT_LEFT, INPUT_PULLUP);
  pinMode(LIMIT_RIGHT, INPUT_PULLUP);
  if (ENABLE_PIN >= 0) pinMode(ENABLE_PIN, OUTPUT);

  digitalWrite(STEP_PIN, LOW);
  digitalWrite(DIR_PIN, LOW);
  motorEnable(false);

  bool homeOk = homeToLeft();
  initBLE();

  if (homeOk) {
    g_state = RS_IDLE;
    notifyText("READY");
  } else {
    g_state = RS_ERROR;
    notifyText("ERROR:HOMING_FAILED");
  }
}

void loop() {
  handleMotion();
  handleIntervalWait();

  if (NEXT_TIMEOUT_MS > 0 &&
      g_state == RS_WAIT_NEXT &&
      millis() - waitNextStartedMs >= NEXT_TIMEOUT_MS) {
    Serial.println("[WAIT_NEXT] timeout -> continue");
    beginIntervalWaitIfNeeded();
  }

  if (g_state == RS_MOVING) {
    if (isPressedStable(LIMIT_RIGHT)) handleRightLimit();
    if (isPressedStable(LIMIT_LEFT))  handleLeftLimit();
  }

  repeatStatusIfNeeded();
  delay(1);
}
