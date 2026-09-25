#pragma once
#include "core_service_daemon_client.hpp"
#include "ak820_request.hpp"
#include <atomic>
#include <condition_variable>
#include <iostream>
#include <mutex>

namespace jarvis::ak820 {
inline int cli(const std::string& text) {
  if (text.size() > 2048) return 2;
  json request;
  try { request = json::parse(text); (void)parse_request(request, wall_time()); }
  catch (...) { std::cout << json({{"status", "rejected"}, {"reason", "invalid_request"}}).dump() << '\n'; return 2; }
  struct state {
    std::mutex mutex;
    std::condition_variable cv;
    bool finished = false;
    std::atomic<bool> dispatched{false};
    json response{{"status", "uncertain"}, {"reason", "timeout"}};
  };
  auto s = std::make_shared<state>();
  auto finish = [s](json response) {
    std::lock_guard lock(s->mutex);
    if (s->finished) return;
    s->response = std::move(response); s->finished = true; s->cv.notify_one();
  };
  krbn::core_service_daemon_client client;
  client.connected.connect([&client, request, finish, s] {
    if (!s->dispatched.exchange(true)) client.async_jarvis_ak820(request, finish);
  });
  client.connect_failed.connect([finish, s](auto&&) {
    if (!s->dispatched.load()) finish({{"status", "rejected"}, {"reason", "not_connected"}});
  });
  client.closed.connect([finish, s] {
    finish({{"status", s->dispatched.load() ? "uncertain" : "rejected"}, {"reason", "connection_closed"}});
  });
  client.async_start();
  std::unique_lock lock(s->mutex);
  s->cv.wait_for(lock, std::chrono::seconds(4), [&] { return s->finished; });
  s->finished = true;
  auto response = s->response;
  lock.unlock();
  client.unregister_callbacks_and_detach();
  std::cout << response.dump() << '\n';
  auto status = response.value("status", "uncertain");
  return status == "success" || status == "ok" || status == "acknowledged" ? 0 : status == "rejected" ? 2 : 3;
}
} // namespace jarvis::ak820
