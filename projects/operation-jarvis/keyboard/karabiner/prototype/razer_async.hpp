#pragma once
#include "razer_protocol.hpp"
#include <chrono>
#include <functional>
#include <memory>
#include <mutex>

namespace jarvis::razer {
// All submissions and IOKit callbacks run on the owning monitor's run loop.
// No device open, driver detach, or input capture. One set/get exchange maximum.
class async_sender {
public:
  enum class state { ready, pending, blocked };
  using clock = std::chrono::steady_clock;
  using completion = std::function<void(result)>;
  using writer = std::function<IOReturn(IOHIDDeviceRef, const report&, IOHIDReportCallback, void*)>;
  using reader = std::function<IOReturn(IOHIDDeviceRef, report&, CFIndex*, IOHIDReportCallback, void*)>;
  using scheduler = std::function<void(std::function<void()>)>;
  explicit async_sender(
      writer write = [](auto device, const auto& bytes, auto cb, auto context) {
        // Native IOKit: no synthetic HIDAPI report-ID prefix for report ID 0.
        return IOHIDDeviceSetReportWithCallback(device, kIOHIDReportTypeFeature, 0,
                                                bytes.data(), bytes.size(), 500, cb, context);
      },
      reader read = [](auto device, auto& bytes, auto length, auto cb, auto context) {
        return IOHIDDeviceGetReportWithCallback(device, kIOHIDReportTypeFeature, 0,
                                                bytes.data(), length, 500, cb, context);
      },
      scheduler delay = [](std::function<void()> task) {
        auto timer = CFRunLoopTimerCreateWithHandler(kCFAllocatorDefault,
            CFAbsoluteTimeGetCurrent() + 0.05, 0, 0, 0, ^(CFRunLoopTimerRef) { task(); });
        if (!timer) throw std::runtime_error("timer allocation");
        CFRunLoopAddTimer(CFRunLoopGetCurrent(), timer, kCFRunLoopDefaultMode);
        CFRelease(timer);
      }) : shared_(std::make_shared<shared_state>()), write_(std::move(write)),
           read_(std::move(read)), delay_(std::move(delay)) {}

  bool submit(IOHIDDeviceRef device, const settings& values, bool eligible,
              clock::time_point deadline, completion done) {
    auto bytes = encode(values);
    auto now = clock::now();
    if (!device || !eligible || !bytes || now >= deadline) return false;
    {
      std::lock_guard lock(shared_->mutex);
      if (shared_->current != state::ready || now < shared_->next_allowed) return false;
      shared_->current = state::pending; shared_->outstanding = true;
      shared_->next_allowed = now + std::chrono::seconds(3);
    }
    auto op = new operation{shared_, device, *bytes, {}, 90, deadline,
                            std::move(done), read_, delay_};
    CFRetain(device);
    auto code = write_(device, op->request, &written, op);
    if (code != kIOReturnSuccess) finish(op, code, std::nullopt);
    return true;
  }
  void mark_uncertain() {
    std::lock_guard lock(shared_->mutex);
    if (shared_->current == state::pending) shared_->current = state::blocked;
  }
  bool acknowledge() {
    std::lock_guard lock(shared_->mutex);
    if (shared_->outstanding) return false;
    shared_->current = state::ready; return true;
  }
  state status() const { std::lock_guard lock(shared_->mutex); return shared_->current; }
private:
  struct shared_state {
    std::mutex mutex; state current = state::ready; bool outstanding = false;
    clock::time_point next_allowed{};
  };
  struct operation {
    std::shared_ptr<shared_state> shared;
    IOHIDDeviceRef device;
    report request, response;
    CFIndex length;
    clock::time_point deadline;
    completion done;
    reader read;
    scheduler delay;
  };
  static bool live(operation* op) {
    std::lock_guard lock(op->shared->mutex);
    return op->shared->current == state::pending && clock::now() < op->deadline;
  }
  static void written(void* raw, IOReturn code, void*, IOHIDReportType, uint32_t, uint8_t*, CFIndex) {
    auto op = static_cast<operation*>(raw);
    if (code != kIOReturnSuccess || !live(op)) { finish(op, code, std::nullopt); return; }
    try {
      op->delay([op] {
        if (!live(op)) { finish(op, kIOReturnTimeout, std::nullopt); return; }
        auto code = op->read(op->device, op->response, &op->length, &received, op);
        if (code != kIOReturnSuccess) finish(op, code, std::nullopt);
      });
    } catch (...) { finish(op, kIOReturnError, std::nullopt); }
  }
  static void received(void* raw, IOReturn code, void*, IOHIDReportType, uint32_t, uint8_t*, CFIndex length) {
    auto op = static_cast<operation*>(raw);
    try {
      auto data = code == kIOReturnSuccess && live(op) ? decode(op->request, op->response, length) : std::nullopt;
      finish(op, code, std::move(data));
    } catch (...) { finish(op, kIOReturnError, std::nullopt); }
  }
  static void finish(operation* raw, IOReturn code, std::optional<json> data) {
    std::unique_ptr<operation> op(raw);
    bool success;
    {
      std::lock_guard lock(op->shared->mutex);
      op->shared->outstanding = false;
      success = code == kIOReturnSuccess && data.has_value() && op->shared->current == state::pending;
      op->shared->current = success ? state::ready : state::blocked;
    }
    CFRelease(op->device);
    try { op->done({success ? outcome::transport_success : outcome::uncertain,
                    code, success ? *data : json(nullptr)}); }
    catch (...) { std::lock_guard lock(op->shared->mutex); op->shared->current = state::blocked; }
  }
  // If IOKit never completes, retain at most one operation instead of freeing a
  // buffer still owned by IOKit. Outstanding acknowledgement is refused.
  std::shared_ptr<shared_state> shared_;
  writer write_; reader read_; scheduler delay_;
};
}
