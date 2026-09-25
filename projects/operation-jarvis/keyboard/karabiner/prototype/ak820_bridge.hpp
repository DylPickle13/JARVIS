#pragma once
#include "ak820_async.hpp"
#include "ak820_journal.hpp"
#include <atomic>
#include <condition_variable>
#include <thread>

namespace jarvis::ak820 {
// Existing authenticated Karabiner socket is the only caller. One detached worker
// maximum across receiver lifetimes; never block the input dispatcher on disk/HID.
// No worker captures a receiver, device_grabber, or raw monitor pointer.
class bridge {
public:
  using transport = std::function<void(const request&, async_sender::clock::time_point,
                                       async_sender::completion)>;
  using reply = std::function<void(json)>;
  static void handle(json body, transport send, reply respond,
                     std::filesystem::path directory = "/Library/Application Support/org.pqrs/Karabiner-Elements/jarvis-ak820") {
    respond = [original = std::move(respond)](json response) {
      try { original(std::move(response)); } catch (...) { /* Disconnected caller: never replay. */ }
    };
    request req;
    try { req = parse_request(body, wall_time()); }
    catch (...) { respond({{"status", "rejected"}, {"reason", "invalid_request"}}); return; }
    bool expected = false;
    if (!busy_.compare_exchange_strong(expected, true)) {
      respond({{"status", "rejected"}, {"reason", "busy"}}); return;
    }
    try {
      std::thread([body, req, send, respond, directory] {
        struct release { ~release() { busy_ = false; } } guard;
        bool attempted = false;
        try {
          journal store(directory);
          auto state = store.load();
          if (req.action == "status") {
            respond({{"status", "ok"}, {"pending", state.at("pending")},
                     {"device_available", static_cast<bool>(send)}, {"lighting_readback", false}});
            return;
          }
          auto now = wall_time();
          if (now - body.at("sent_at").get<double>() > 2.0 || now < body.at("sent_at").get<double>()) {
            respond({{"status", "rejected"}, {"reason", "expired"}}); return;
          }
          if (!send) { respond({{"status", "rejected"}, {"reason", "device_unavailable"}}); return; }
          if (req.action == "apply") {
            if (state.at("pending").get<bool>()) {
              respond({{"status", "blocked"}, {"reason", "acknowledgment_required"}}); return;
            }
            auto age = now - state.at("last_attempt").get<double>();
            double cooldown = state.at("succeeded").get<bool>() ? 3.0 : 60.0;
            if (age < cooldown || state.at("id") == req.id) {
              respond({{"status", "rejected"}, {"reason", "cooldown_or_duplicate"}}); return;
            }
            state["pending"] = true;
            state["last_attempt"] = now;
            state["succeeded"] = false;
            state["id"] = req.id;
            store.save(state); // Must be durable before queuing any HID call.
          }
          struct completion_state {
            std::mutex mutex;
            std::condition_variable cv;
            bool finished = false;
            result value{outcome::uncertain, kIOReturnError};
          };
          auto completion = std::make_shared<completion_state>();
          auto remaining = std::max(0.0, 2.0 - (wall_time() - body.at("sent_at").get<double>()));
          auto deadline = async_sender::clock::now() + std::chrono::duration_cast<async_sender::clock::duration>(std::chrono::duration<double>(remaining));
          attempted = req.action == "apply";
          send(req, deadline, [completion](result value) {
            std::lock_guard lock(completion->mutex);
            completion->value = value;
            completion->finished = true;
            completion->cv.notify_one();
          });
          std::unique_lock lock(completion->mutex);
          if (!completion->cv.wait_for(lock, std::chrono::seconds(2), [&] { return completion->finished; })) {
            respond({{"status", "uncertain"}, {"reason", "timeout"}});
            return; // Persisted marker remains; late callback cannot clear it.
          }
          auto result = completion->value.status;
          lock.unlock();
          if (req.action == "acknowledge") {
            if (result != outcome::transport_success) {
              respond({{"status", "blocked"}, {"reason", "operation_still_outstanding"}}); return;
            }
            state["pending"] = false;
            state["last_attempt"] = wall_time();
            state["succeeded"] = false;
            store.save(state);
            respond({{"status", "acknowledged"}, {"hardware_write", false}}); return;
          }
          if (result == outcome::uncertain) {
            respond({{"status", "uncertain"}, {"reason", "transport"}}); return;
          }
          state["pending"] = false;
          state["succeeded"] = result == outcome::transport_success;
          store.save(state);
          respond({{"status", result == outcome::transport_success ? "success" : "rejected"},
                   {"reason", result == outcome::transport_success ? "transport_only" : "prewrite"}});
        } catch (...) {
          respond({{"status", attempted ? "uncertain" : "rejected"}, {"reason", "state_or_transport_error"}});
        }
      }).detach();
    } catch (...) {
      busy_ = false;
      respond({{"status", "rejected"}, {"reason", "worker_unavailable"}});
    }
  }
private:
  inline static std::atomic<bool> busy_{false};
};
} // namespace jarvis::ak820
