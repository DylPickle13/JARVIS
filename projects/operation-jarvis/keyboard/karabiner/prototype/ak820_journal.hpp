#pragma once
#include "ak820_request.hpp"
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <filesystem>
#include <vector>

namespace jarvis::ak820 {
class journal {
public:
  explicit journal(std::filesystem::path directory) : directory_(std::move(directory)) {}
  json load() const {
    check_directory();
    int fd = open((directory_ / "state.json").c_str(), O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) {
      if (errno == ENOENT) return {{"version", 1}, {"pending", false}, {"last_attempt", 0.0}, {"id", ""}, {"succeeded", false}};
      throw std::runtime_error("journal open");
    }
    struct stat st{};
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
        (st.st_mode & 0777) != 0600 || st.st_nlink != 1 || st.st_size > 1024) {
      close(fd); throw std::runtime_error("journal permissions");
    }
    char buffer[1025];
    auto n = read(fd, buffer, sizeof(buffer));
    close(fd);
    if (n < 0 || n > 1024) throw std::runtime_error("journal read");
    auto s = json::parse(buffer, buffer + n);
    if (!s.is_object() || s.size() != 5 || s.at("version") != 1 ||
        !s.at("pending").is_boolean() || !s.at("succeeded").is_boolean() || !s.at("last_attempt").is_number() ||
        !s.at("id").is_string()) throw std::runtime_error("journal state");
    double t = s.at("last_attempt").get<double>();
    auto id = s.at("id").get<std::string>();
    if (!std::isfinite(t) || t < 0 ||
        (!id.empty() && (id.size() != 32 || id.find_first_not_of("0123456789abcdef") != std::string::npos)))
      throw std::runtime_error("journal state");
    return s;
  }
  void save(const json& s) const {
    check_directory();
    auto data = s.dump();
    std::string pattern = (directory_ / ".atomic-XXXXXX").string();
    std::vector<char> name(pattern.begin(), pattern.end()); name.push_back(0);
    int fd = mkstemp(name.data());
    if (fd < 0) throw std::runtime_error("journal temporary file");
    bool ok = fchmod(fd, 0600) == 0 && write(fd, data.data(), data.size()) == static_cast<ssize_t>(data.size()) && fsync(fd) == 0;
    close(fd);
    if (ok) ok = rename(name.data(), (directory_ / "state.json").c_str()) == 0;
    if (!ok) { unlink(name.data()); throw std::runtime_error("journal persist"); }
    int dir = open(directory_.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    if (dir < 0) throw std::runtime_error("journal directory open");
    ok = fsync(dir) == 0;
    close(dir);
    if (!ok) throw std::runtime_error("journal directory sync");
  }
private:
  void check_directory() const {
    if (mkdir(directory_.c_str(), 0700) && errno != EEXIST) throw std::runtime_error("journal mkdir");
    struct stat st{};
    if (lstat(directory_.c_str(), &st) || !S_ISDIR(st.st_mode) ||
        st.st_uid != geteuid() || (st.st_mode & 0777) != 0700)
      throw std::runtime_error("journal directory permissions");
  }
  std::filesystem::path directory_;
};
} // namespace jarvis::ak820
