// Offline-only fake writer. No real IOHIDDevice is opened or written.
#include "ak820_async.hpp"
#include <cassert>
#include <thread>

using namespace jarvis::ak820;
int main() {
  auto fake = reinterpret_cast<IOHIDDeviceRef>(const_cast<void*>(
      static_cast<const void*>(CFSTR("not a device; retain/release test only"))));
  const settings config{8, 4, 0, 0, false, {0x99, 0x33, 0xff}};
  const auto deadline = async_sender::clock::now() + std::chrono::seconds(20);
  IOHIDReportCallback callback = nullptr;
  void* context = nullptr;
  int writes = 0;
  int completions = 0;
  result last{outcome::rejected, 0};
  auto writer = [&](IOHIDDeviceRef, const report& bytes, IOHIDReportCallback cb, void* ctx) {
    ++writes;
    assert(bytes == *encode(config));
    callback = cb; context = ctx;
    return kIOReturnSuccess;
  };
  auto done = [&](result r) { ++completions; last = r; };
  {
    async_sender sender(writer);
    assert(!sender.submit(nullptr, config, true, deadline, done));
    assert(!sender.submit(fake, config, false, deadline, done));
    assert(!sender.submit(fake, config, true, async_sender::clock::now(), done));
    auto invalid = config; invalid.effect = 6;
    assert(!sender.submit(fake, invalid, true, deadline, done));
    assert(writes == 0);
    assert(sender.submit(fake, config, true, deadline, done));
    assert(sender.status() == async_sender::state::pending);
    assert(!sender.submit(fake, config, true, deadline, done));
    auto bytes = *encode(config);
    callback(context, kIOReturnSuccess, nullptr, kIOHIDReportTypeOutput, 4, bytes.data(), bytes.size());
    assert(last.status == outcome::transport_success && completions == 1);
    assert(sender.status() == async_sender::state::ready);
    assert(!sender.submit(fake, config, true, deadline, done)); // cooldown
  }
  {
    async_sender sender(writer);
    assert(sender.submit(fake, config, true, deadline, done));
    sender.mark_uncertain();
    assert(sender.status() == async_sender::state::blocked);
    auto bytes = *encode(config);
    callback(context, kIOReturnSuccess, nullptr, kIOHIDReportTypeOutput, 4, bytes.data(), bytes.size());
    assert(last.status == outcome::uncertain); // late success must not recover
    assert(!sender.submit(fake, config, true, deadline, done));
  }
  {
    async_sender sender(writer);
    assert(sender.submit(fake, config, true, deadline, done));
    auto bytes = *encode(config);
    callback(context, kIOReturnError, nullptr, kIOHIDReportTypeOutput, 4, bytes.data(), bytes.size());
    assert(last.status == outcome::uncertain);
    assert(sender.status() == async_sender::state::blocked);
  }
  {
    async_sender sender([](auto, const auto&, auto, auto) { return kIOReturnError; });
    assert(sender.submit(fake, config, true, deadline, done));
    assert(last.status == outcome::uncertain);
    assert(sender.status() == async_sender::state::blocked);
  }
  {
    auto sender = std::make_unique<async_sender>(writer);
    assert(sender->submit(fake, config, true, deadline, done));
    sender.reset(); // completion remains valid after monitor/sender destruction
    auto bytes = *encode(config);
    callback(context, kIOReturnSuccess, nullptr, kIOHIDReportTypeOutput, 4, bytes.data(), bytes.size());
    assert(last.status == outcome::transport_success);
  }
  assert(writes == 4);
}
