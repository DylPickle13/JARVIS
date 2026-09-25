// Read-only metadata inspection; never calls IOHIDDeviceOpen or sends a report.
#include "ak820_lighting.hpp"
#include <cstdlib>
#include <iostream>
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  char* end = nullptr;
  auto id = std::strtoull(argv[1], &end, 10);
  if (!end || *end || !id) return 2;
  auto service = IOServiceGetMatchingService(kIOMainPortDefault, IORegistryEntryIDMatching(id));
  if (!service) return 1;
  auto device = IOHIDDeviceCreate(kCFAllocatorDefault, service);
  IOObjectRelease(service);
  if (!device) return 1;
  std::cout << "interface_one=" << jarvis::ak820::interface_one(device)
            << " rgb_collection=" << IOHIDDeviceConformsTo(device, 0xff1c, 146)
            << " exact_match=" << jarvis::ak820::matches(device) << '\n';
  CFRelease(device);
}
