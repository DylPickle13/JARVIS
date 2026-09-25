#pragma once
#include "ak820_lighting.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <string>

namespace jarvis::ak820 {
using json = nlohmann::json;
inline double wall_time() {
  return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
}
struct request {
  std::string action;
  std::string id;
  settings values{};
};
inline request parse_request(const json& j, double now) {
  if (!j.is_object() || j.size() != 5 || j.at("operation_type") != "jarvis_ak820_v1" ||
      !j.at("action").is_string() || !j.at("id").is_string() || !j.at("sent_at").is_number())
    throw std::invalid_argument("request shape");
  request r;
  r.action = j.at("action").get<std::string>();
  r.id = j.at("id").get<std::string>();
  if (r.id.size() != 32 || r.id.find_first_not_of("0123456789abcdef") != std::string::npos)
    throw std::invalid_argument("request id");
  auto stamp = j.at("sent_at").get<double>();
  if (!std::isfinite(stamp) || stamp > now || now - stamp > 2.0)
    throw std::invalid_argument("expired");
  const auto& s = j.at("settings");
  if (r.action == "status" || r.action == "acknowledge") {
    if (!s.is_null()) throw std::invalid_argument("unexpected settings");
    return r;
  }
  if (r.action != "apply" || !s.is_object() || s.size() != 6 ||
      !s.at("rainbow").is_boolean() || !s.at("rgb").is_array() || s.at("rgb").size() != 3)
    throw std::invalid_argument("settings shape");
  auto integer = [](const json& v, int low, int high) {
    if (!v.is_number_integer()) throw std::invalid_argument("integer required");
    // Compare before conversion to prevent narrowing/overflow accepting hostile input.
    if (v < low || v > high) throw std::invalid_argument("integer range");
    return v.get<int>();
  };
  r.values.effect = integer(s.at("effect"), 1, 18);
  r.values.brightness = integer(s.at("brightness"), 0, 4);
  r.values.speed = integer(s.at("speed"), 0, 4);
  r.values.direction = integer(s.at("direction"), 0, 1);
  r.values.rainbow = s.at("rainbow").get<bool>();
  for (int i = 0; i < 3; ++i) r.values.rgb[i] = static_cast<uint8_t>(integer(s.at("rgb")[i], 0, 255));
  if (!encode(r.values)) throw std::invalid_argument("unsupported effect");
  return r;
}
} // namespace jarvis::ak820
