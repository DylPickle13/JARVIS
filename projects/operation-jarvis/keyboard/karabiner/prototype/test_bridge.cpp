#include "ak820_bridge.hpp"
#include <cassert>
#include <future>
#include <fstream>
using namespace jarvis::ak820;
json body(std::string action = "apply") {
  return {{"operation_type", "jarvis_ak820_v1"}, {"action", action},
          {"id", "0123456789abcdef0123456789abcdef"}, {"sent_at", wall_time()},
          {"settings", action == "apply" ? json{{"effect",8},{"brightness",4},{"speed",0},
                                               {"direction",0},{"rainbow",false},{"rgb",{153,51,255}}} : json(nullptr)}};
}
json invoke(json request, bridge::transport send, const std::filesystem::path& path) {
  auto promise = std::make_shared<std::promise<json>>();
  auto future = promise->get_future();
  bridge::handle(request, send, [promise](json result) { promise->set_value(result); }, path);
  assert(future.wait_for(std::chrono::seconds(4)) == std::future_status::ready);
  auto result = future.get();
  std::this_thread::sleep_for(std::chrono::milliseconds(10)); // worker releases global busy guard
  return result;
}
int main() {
  char pattern[] = "/tmp/jarvis-ak820-test-XXXXXX";
  auto parent = mkdtemp(pattern); assert(parent);
  std::filesystem::path dir = std::filesystem::path(parent) / "state";
  journal store(dir);
  auto s = store.load(); assert(!s.at("pending").get<bool>());
  auto valid = body(); assert(parse_request(valid, wall_time()).values.effect == 8);
  for (auto invalid : {json(true), json::array(), json{{"x",1}}}) {
    try { (void)parse_request(invalid, wall_time()); assert(false); } catch (...) {}
  }
  for (auto value : {json(true), json(1.5), json(-1), json(1ULL << 63), json(6)}) {
    auto invalid = body(); invalid["settings"]["effect"] = value;
    assert(invoke(invalid, {}, dir).at("status") == "rejected");
  }
  auto invalid = body(); invalid["extra"] = 1;
  assert(invoke(invalid, {}, dir).at("status") == "rejected");
  invalid = body(); invalid["sent_at"] = wall_time() - 3;
  assert(invoke(invalid, {}, dir).at("status") == "rejected");
  assert(invoke(body(), {}, dir).at("status") == "rejected");
  int writes = 0;
  bridge::transport success = [&](const request& r, auto, auto done) {
    if (r.action == "apply") {
      assert(store.load().at("pending").get<bool>()); // persist-before-send
      ++writes;
    }
    done({outcome::transport_success, kIOReturnSuccess});
  };
  assert(invoke(body(), success, dir).at("status") == "success");
  assert(writes == 1 && !store.load().at("pending").get<bool>());
  assert(invoke(body(), success, dir).at("status") == "rejected"); // duplicate/cooldown
  auto reset = [&] {
    auto state = store.load(); state["last_attempt"] = 0; state["id"] = ""; store.save(state);
  };
  reset();
  bridge::transport uncertain = [&](const request&, auto, auto done) {
    ++writes; done({outcome::uncertain, kIOReturnError});
  };
  assert(invoke(body(), uncertain, dir).at("status") == "uncertain");
  assert(journal(dir).load().at("pending").get<bool>());
  assert(invoke(body(), success, dir).at("status") == "blocked");
  assert(writes == 2);
  assert(invoke(body("acknowledge"), success, dir).at("status") == "acknowledged");
  assert(writes == 2 && !store.load().at("pending").get<bool>());
  assert(invoke(body(), success, dir).at("status") == "rejected"); // acknowledgment cooldown
  reset();
  bridge::transport reject = [](const request&, auto, auto done) { done({outcome::rejected, kIOReturnNotOpen}); };
  assert(invoke(body(), reject, dir).at("status") == "rejected");
  assert(!store.load().at("pending").get<bool>());
  reset();
  async_sender::completion late;
  bridge::transport timeout = [&](const request&, auto, auto done) { ++writes; late = done; };
  assert(invoke(body(), timeout, dir).at("status") == "uncertain");
  late({outcome::transport_success, kIOReturnSuccess});
  assert(store.load().at("pending").get<bool>()); // late success cannot clear marker
  assert(invoke(body("status"), {}, dir).at("pending").get<bool>());
  // Journal symlinks/corruption fail closed and do not send.
  std::filesystem::remove(dir / "state.json");
  std::filesystem::create_symlink("/dev/null", dir / "state.json");
  assert(invoke(body(), success, dir).at("status") == "rejected");
  assert(writes == 3);
  std::filesystem::remove_all(parent);
}
