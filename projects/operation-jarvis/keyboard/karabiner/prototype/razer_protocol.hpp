#pragma once
// DeathAdder Essential 2021 only (1532:0098). Protocol: OpenRazer.
#include "ak820_lighting.hpp"
#include <nlohmann/json.hpp>
#include <string>

namespace jarvis::razer {
using json = nlohmann::json;
using outcome = ak820::outcome;
using report = std::array<uint8_t, 90>;
struct settings { std::string operation; int value = 0; int y = 0; };
struct result { outcome status; IOReturn code; json data = nullptr; };
inline uint8_t crc(const report& r) {
  uint8_t c = 0; for (size_t i = 2; i < 88; ++i) c ^= r[i]; return c;
}
inline std::optional<report> encode(const settings& s) {
  report r{};
  r[1] = 0x3f;
  if (s.operation == "effect") {
    if (s.value < 0 || s.value > 2 || s.y) return std::nullopt;
    r[5] = s.value ? 9 : 6; r[6] = 0x0f; r[7] = 2;
    r[8] = 1; r[9] = 4; r[10] = s.value;
    if (s.value) { r[13] = 1; r[14] = r[15] = r[16] = 255; }
    if (s.value == 2) r[11] = 1;
  } else if (s.operation == "brightness" || s.operation == "get-brightness") {
    if (s.value < 0 || s.value > 100 || s.y || (s.operation == "get-brightness" && s.value)) return std::nullopt;
    r[5] = 3; r[6] = 0x0f; r[7] = s.operation == "brightness" ? 4 : 0x84;
    r[8] = 1; r[9] = 4; r[10] = (s.value * 255 + 50) / 100;
  } else if (s.operation == "dpi" || s.operation == "get-dpi") {
    if (s.operation == "dpi" && (s.value < 100 || s.value > 6400 || s.y < 100 || s.y > 6400)) return std::nullopt;
    if (s.operation == "get-dpi" && (s.value || s.y)) return std::nullopt;
    r[1] = 0xff; r[5] = 7; r[6] = 4; r[7] = s.operation == "dpi" ? 5 : 0x85;
    r[8] = s.operation == "dpi" ? 1 : 0;
    r[9] = s.value >> 8; r[10] = s.value & 255;
    r[11] = s.y >> 8; r[12] = s.y & 255;
  } else if (s.operation == "poll" || s.operation == "get-poll") {
    if (s.y) return std::nullopt;
    if (s.operation == "poll" && s.value != 125 && s.value != 500 && s.value != 1000) return std::nullopt;
    if (s.operation == "get-poll" && s.value) return std::nullopt;
    r[1] = 0xff; r[5] = 1; r[7] = s.operation == "poll" ? 5 : 0x85;
    if (s.operation == "poll") r[8] = 1000 / s.value;
  } else return std::nullopt;
  r[88] = crc(r); return r;
}
inline std::optional<json> decode(const report& request, const report& response, CFIndex size) {
  if (size != 90 || response[0] != 2 || response[1] != request[1] ||
      response[2] || response[3] || response[4] || response[5] != request[5] ||
      response[6] != request[6] || response[7] != request[7] ||
      response[88] != crc(response) || response[89]) return std::nullopt;
  json data = json::object();
  if (request[6] == 15 && request[7] == 0x84) {
    if (response[9] != 4) return std::nullopt;
    data["brightness_raw"] = response[10];
    data["brightness_percent"] = (response[10] * 100 + 127) / 255;
  } else if (request[6] == 4 && request[7] == 0x85) {
    int x = response[9] * 256 + response[10], y = response[11] * 256 + response[12];
    if (x < 100 || x > 6400 || y < 100 || y > 6400) return std::nullopt;
    data["dpi_x"] = x; data["dpi_y"] = y;
  } else if (request[6] == 0 && request[7] == 0x85) {
    if (response[8] != 1 && response[8] != 2 && response[8] != 8) return std::nullopt;
    data["poll_hz"] = 1000 / response[8];
  }
  return data;
}
inline bool matches(IOHIDDeviceRef device) {
  if (!device || !ak820::property_is(device, CFSTR(kIOHIDVendorIDKey), 0x1532) ||
      !ak820::property_is(device, CFSTR(kIOHIDProductIDKey), 0x0098) ||
      !IOHIDDeviceConformsTo(device, 1, 2)) return false;
  auto product = IOHIDDeviceGetProperty(device, CFSTR(kIOHIDProductKey));
  if (!product || CFGetTypeID(product) != CFStringGetTypeID() ||
      !CFEqual(product, CFSTR("Razer DeathAdder Essential"))) return false;
  auto service = IOHIDDeviceGetService(device);
  if (!service) return false;
  auto value = IORegistryEntrySearchCFProperty(service, kIOServicePlane,
      CFSTR("bInterfaceNumber"), kCFAllocatorDefault,
      kIORegistryIterateRecursively | kIORegistryIterateParents);
  int number = -1;
  bool ok = value && CFGetTypeID(value) == CFNumberGetTypeID() &&
      CFNumberGetValue(static_cast<CFNumberRef>(value), kCFNumberIntType, &number) && number == 0;
  if (value) CFRelease(value);
  return ok;
}
} // namespace jarvis::razer
