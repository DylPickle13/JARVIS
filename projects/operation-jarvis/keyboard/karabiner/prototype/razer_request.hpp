#pragma once
#include "razer_protocol.hpp"
#include "ak820_request.hpp"
namespace jarvis::razer {
using ak820::wall_time;
struct request { std::string action; std::string id; settings values{}; };
inline request parse_request(const json& j, double now) {
  if (!j.is_object() || j.size() != 5 || j.at("operation_type") != "jarvis_razer_v1" ||
      !j.at("action").is_string() || !j.at("id").is_string() || !j.at("sent_at").is_number())
    throw std::invalid_argument("request shape");
  request r{j.at("action").get<std::string>(), j.at("id").get<std::string>()};
  if (r.id.size() != 32 || r.id.find_first_not_of("0123456789abcdef") != std::string::npos)
    throw std::invalid_argument("request id");
  auto stamp = j.at("sent_at").get<double>();
  if (!std::isfinite(stamp) || stamp > now || now - stamp > 2)
    throw std::invalid_argument("expired");
  const auto& s = j.at("settings");
  if (r.action == "status" || r.action == "acknowledge") {
    if (!s.is_null()) throw std::invalid_argument("unexpected settings");
    return r;
  }
  if (r.action != "apply" || !s.is_object() || s.size() != 3 ||
      !s.at("operation").is_string()) throw std::invalid_argument("settings shape");
  for (auto key : {"value", "y"}) {
    if (!s.at(key).is_number_integer() || s.at(key) < 0 || s.at(key) > 6400)
      throw std::invalid_argument("integer range");
  }
  r.values = {s.at("operation").get<std::string>(), s.at("value").get<int>(), s.at("y").get<int>()};
  if (!encode(r.values)) throw std::invalid_argument("unsupported command");
  return r;
}
}
