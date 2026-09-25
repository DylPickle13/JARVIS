#pragma once
#include "ak820_lighting.hpp"
#include <chrono>
#include <functional>
#include <memory>
#include <mutex>

namespace jarvis::ak820 {
// Internal transport primitive. All submit calls must originate on the monitor's
// device run loop. Context owns device + bytes until IOKit completion, even when
// the monitor disappears. Never captures the monitor or an IPC receiver.
// No install/IPC route exists yet. Never call this from arbitrary user requests.
class async_sender {
public:
  enum class state { ready, pending, blocked };
  using clock = std::chrono::steady_clock;
  using completion = std::function<void(result)>;
  using writer = std::function<IOReturn(IOHIDDeviceRef, const report&, IOHIDReportCallback, void*)>;

  explicit async_sender(writer write = [](IOHIDDeviceRef device, const report& bytes,
                                         IOHIDReportCallback callback, void* context) {
    return IOHIDDeviceSetReportWithCallback(device, kIOHIDReportTypeOutput, bytes[0],
                                           bytes.data(), bytes.size(), 500,
                                           callback, context);
  }) : shared_(std::make_shared<shared_state>()), write_(std::move(write)) {}

  // Caller performs exact device/interface and seized/open checks. Returning
  // rejected here never implies that an earlier pending report was cancelled.
  bool submit(IOHIDDeviceRef device, const settings& config, bool eligible,
              clock::time_point deadline, completion done) {
    auto bytes = encode(config);
    auto now = clock::now();
    if (!device || !eligible || !bytes || now >= deadline) return false;
    {
      std::lock_guard lock(shared_->mutex);
      if (shared_->current != state::ready || now < shared_->next_allowed) return false;
      shared_->current = state::pending;
      shared_->outstanding = true;
      shared_->next_allowed = now + std::chrono::seconds(3);
    }
    // At most one context can be outstanding. If the OS never calls back, retain
    // it rather than free memory the kernel may still reference. A timeout blocks
    // this sender for the remainder of its lifetime; no retry/recovery write.
    auto context = new operation{shared_, device, *bytes, std::move(done)};
    CFRetain(device);
    auto code = write_(device, context->bytes, &completed, context);
    if (code != kIOReturnSuccess) {
      // API did not accept async submission: conservatively uncertain, not safe
      // to replay. Apple API failure is assumed not to schedule a callback.
      finish(context, code);
    }
    return true;
  }

  void mark_uncertain() {
    std::lock_guard lock(shared_->mutex);
    if (shared_->current == state::pending) shared_->current = state::blocked;
  }

  bool acknowledge() {
    std::lock_guard lock(shared_->mutex);
    if (shared_->outstanding) return false;
    shared_->current = state::ready;
    return true;
  }

  state status() const {
    std::lock_guard lock(shared_->mutex);
    return shared_->current;
  }

private:
  struct shared_state {
    std::mutex mutex;
    state current = state::ready;
    bool outstanding = false;
    clock::time_point next_allowed{};
  };
  struct operation {
    std::shared_ptr<shared_state> shared;
    IOHIDDeviceRef device;
    report bytes;
    completion done;
  };
  static void completed(void* raw, IOReturn code, void*, IOHIDReportType, uint32_t,
                        uint8_t*, CFIndex) {
    finish(static_cast<operation*>(raw), code);
  }
  static void finish(operation* raw, IOReturn code) {
    std::unique_ptr<operation> context(raw);
    bool success;
    {
      std::lock_guard lock(context->shared->mutex);
      // A late successful callback never erases a timeout/disconnect safety block.
      context->shared->outstanding = false;
      success = code == kIOReturnSuccess && context->shared->current == state::pending;
      context->shared->current = success ? state::ready : state::blocked;
    }
    CFRelease(context->device);
    try {
      context->done({success ? outcome::transport_success : outcome::uncertain, code});
    } catch (...) {
      // Never let caller exceptions cross the C callback boundary into IOKit.
      std::lock_guard lock(context->shared->mutex);
      context->shared->current = state::blocked;
    }
  }
  std::shared_ptr<shared_state> shared_;
  writer write_;
};
} // namespace jarvis::ak820
