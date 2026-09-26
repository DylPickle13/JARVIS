// Metadata only: no device open, input capture, or USB reports.
#include "razer_protocol.hpp"
#include <cstdlib>
#include <iostream>
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  char* end = nullptr; auto id = std::strtoull(argv[1], &end, 10);
  if (!end || *end || !id) return 2;
  auto service = IOServiceGetMatchingService(kIOMainPortDefault, IORegistryEntryIDMatching(id));
  if (!service) return 1;
  auto device = IOHIDDeviceCreate(kCFAllocatorDefault, service); IOObjectRelease(service);
  if (!device) return 1;
  std::cout << "mouse_collection=" << IOHIDDeviceConformsTo(device, 1, 2)
            << " exact_razer_match=" << jarvis::razer::matches(device) << '\n';
  CFRelease(device);
}
