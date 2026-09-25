#pragma once
// JARVIS feasibility prototype. Not connected to Karabiner IPC or installed.
#include <array>
#include <cstdint>
#include <optional>
#include <IOKit/IOKitLib.h>
#include <IOKit/hid/IOHIDDevice.h>
#include <IOKit/hid/IOHIDKeys.h>

namespace jarvis::ak820 {
struct settings {
  int effect;
  int brightness;
  int speed;
  int direction;
  bool rainbow;
  std::array<uint8_t, 3> rgb;
};
using report = std::array<uint8_t, 65>;

inline std::optional<report> encode(const settings& s) {
  // Selector 6 (unverified static) is deliberately not supported.
  if (s.effect < 1 || s.effect > 18 || s.effect == 6 ||
      s.brightness < 0 || s.brightness > 4 ||
      s.speed < 0 || s.speed > 4 ||
      s.direction < 0 || s.direction > 1) return std::nullopt;
  report r{};
  r[0] = 4; r[1] = 0x2a; r[2] = 0x3d; r[3] = 6; r[4] = 0x1d;
  r[9] = static_cast<uint8_t>(s.effect);
  r[10] = static_cast<uint8_t>(s.brightness);
  r[11] = static_cast<uint8_t>(s.speed);
  r[12] = static_cast<uint8_t>(s.direction);
  if (s.rainbow) r[13] = 1;
  else for (int i = 0; i < 3; ++i) r[14 + i] = s.rgb[i];
  return r;
}

inline bool property_is(IOHIDDeviceRef device, CFStringRef key, int expected) {
  auto value = IOHIDDeviceGetProperty(device, key);
  int actual = 0;
  return value && CFGetTypeID(value) == CFNumberGetTypeID() &&
         CFNumberGetValue(static_cast<CFNumberRef>(value), kCFNumberIntType, &actual) &&
         actual == expected;
}

inline bool interface_one(IOHIDDeviceRef device) {
  if (!device) return false;
  auto service = IOHIDDeviceGetService(device);
  if (!service) return false;
  auto value = IORegistryEntrySearchCFProperty(service, kIOServicePlane,
      CFSTR("bInterfaceNumber"), kCFAllocatorDefault,
      kIORegistryIterateRecursively | kIORegistryIterateParents);
  int number = -1;
  bool valid = value && CFGetTypeID(value) == CFNumberGetTypeID() &&
      CFNumberGetValue(static_cast<CFNumberRef>(value), kCFNumberIntType, &number) && number == 1;
  if (value) CFRelease(value);
  return valid;
}

inline bool matches(IOHIDDeviceRef device) {
  if (!device) return false;
  auto product = IOHIDDeviceGetProperty(device, CFSTR(kIOHIDProductKey));
  return interface_one(device) && product && CFGetTypeID(product) == CFStringGetTypeID() &&
         CFEqual(product, CFSTR("AK820")) &&
         property_is(device, CFSTR(kIOHIDVendorIDKey), 0x320f) &&
         property_is(device, CFSTR(kIOHIDProductIDKey), 0x505b) &&
         IOHIDDeviceConformsTo(device, 0xff1c, 146);
  // Interface 1 is a composite HID device: primary usage is keyboard, while
  // RGB is a separate top-level collection on that SAME owned device handle.
}

enum class outcome { rejected, transport_success, uncertain };
struct result { outcome status; IOReturn code; };

// INTERNAL proof-of-concept only. Caller must hold the existing device lifetime,
// verify seized/open state, enforce authorization and
// cooldown, and serialize with device removal/close. No new device open here.
// Synchronous IOKit call: do NOT wire this into the input dispatcher until a
// bounded, lifetime-safe scheduling design is implemented and tested.
inline result send_on_owned_device(IOHIDDeviceRef device, const settings& s) {
  auto bytes = encode(s);
  if (!bytes || !matches(device)) return {outcome::rejected, kIOReturnBadArgument};
  // Match hidapi 0.15.0: nonzero report ID remains in the full 65-byte buffer.
  auto code = IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput,
                                 (*bytes)[0], bytes->data(), bytes->size());
  return {code == kIOReturnSuccess ? outcome::transport_success : outcome::uncertain, code};
}
} // namespace jarvis::ak820
