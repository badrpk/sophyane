// Sophyane C++ client (header-only HTTP JSON bridge)
// Talks to Sophyane Hardware API (default http://127.0.0.1:8770)
// Requires: libcurl (or define SOPHYANE_NO_CURL and provide transport).
#pragma once

#include <cstdlib>
#include <sstream>
#include <stdexcept>
#include <string>

#if !defined(SOPHYANE_NO_CURL)
#include <curl/curl.h>
#endif

namespace sophyane {

inline std::string default_base_url() {
  const char* env = std::getenv("SOPHYANE_API");
  return env && *env ? std::string(env) : "http://127.0.0.1:8770";
}

#if !defined(SOPHYANE_NO_CURL)
inline size_t _write_cb(char* ptr, size_t size, size_t nmemb, void* userdata) {
  auto* out = static_cast<std::string*>(userdata);
  out->append(ptr, size * nmemb);
  return size * nmemb;
}

inline std::string http_get(const std::string& url) {
  CURL* curl = curl_easy_init();
  if (!curl) throw std::runtime_error("curl_easy_init failed");
  std::string body;
  curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, _write_cb);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);
  CURLcode rc = curl_easy_perform(curl);
  curl_easy_cleanup(curl);
  if (rc != CURLE_OK) throw std::runtime_error(curl_easy_strerror(rc));
  return body;
}

inline std::string http_post_json(const std::string& url, const std::string& json) {
  CURL* curl = curl_easy_init();
  if (!curl) throw std::runtime_error("curl_easy_init failed");
  std::string body;
  struct curl_slist* headers = nullptr;
  headers = curl_slist_append(headers, "Content-Type: application/json");
  curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json.c_str());
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, _write_cb);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 120L);
  CURLcode rc = curl_easy_perform(curl);
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);
  if (rc != CURLE_OK) throw std::runtime_error(curl_easy_strerror(rc));
  return body;
}
#endif

class Client {
 public:
  explicit Client(std::string base = default_base_url()) : base_(std::move(base)) {
    if (!base_.empty() && base_.back() == '/') base_.pop_back();
  }

  std::string health() const { return get("/v1/hardware/health"); }
  std::string platform() const { return get("/v1/hardware/platform"); }
  std::string compatibility() const { return get("/v1/hardware/compat"); }
  std::string backends() const { return get("/v1/hardware/backends"); }
  std::string software() const { return get("/v1/hardware/software"); }

  std::string chat(const std::string& message, bool edge = false) const {
    std::ostringstream oss;
    oss << "{\"message\":" << json_escape(message)
        << ",\"edge\":" << (edge ? "true" : "false") << "}";
    return post("/v1/hardware/chat", oss.str());
  }

 private:
  std::string base_;

  static std::string json_escape(const std::string& s) {
    std::string o = "\"";
    for (char c : s) {
      switch (c) {
        case '\\': o += "\\\\"; break;
        case '"': o += "\\\""; break;
        case '\n': o += "\\n"; break;
        case '\r': o += "\\r"; break;
        case '\t': o += "\\t"; break;
        default: o += c;
      }
    }
    o += "\"";
    return o;
  }

  std::string get(const std::string& path) const {
#if defined(SOPHYANE_NO_CURL)
    throw std::runtime_error("Build without SOPHYANE_NO_CURL and link libcurl");
#else
    return http_get(base_ + path);
#endif
  }

  std::string post(const std::string& path, const std::string& json) const {
#if defined(SOPHYANE_NO_CURL)
    (void)json;
    throw std::runtime_error("Build without SOPHYANE_NO_CURL and link libcurl");
#else
    return http_post_json(base_ + path, json);
#endif
  }
};

}  // namespace sophyane
