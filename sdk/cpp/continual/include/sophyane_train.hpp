// Sophyane Continual Train Core — pure C++17, hardware-efficient.
// Federated LoRA-style adapter deltas over an existing base LLM (GGUF weights).
// No Python in the hot path: local steps, FedAvg, hashing, serialization.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <map>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace sophyane {
namespace train {

inline constexpr const char* kMagic = "SOPHYANE_ADAPTER_v1";
inline constexpr const char* kCoreVersion = "17.0.0";

struct AdapterMeta {
  std::string magic = kMagic;
  std::string base_model = "local_gguf";
  std::string base_hash;
  std::string peer_id;
  std::uint64_t round = 0;
  int rank = 8;
  int dim = 256;           // adapter width (not full model dim — PEFT-style)
  int layers = 4;          // number of adapter blocks
  std::size_t samples = 0;
  double loss = 0.0;
  std::string algo = "fedavg-lora-digest";
  std::string core = kCoreVersion;
  std::string weights_sha256;
};

// FNV-1a 64-bit (fast, no OpenSSL dep)
inline std::uint64_t fnv1a64(const void* data, std::size_t n, std::uint64_t h = 14695981039346656037ULL) {
  const auto* p = static_cast<const unsigned char*>(data);
  for (std::size_t i = 0; i < n; ++i) {
    h ^= p[i];
    h *= 1099511628211ULL;
  }
  return h;
}

inline std::string hex64(std::uint64_t v) {
  std::ostringstream oss;
  oss << std::hex << std::setfill('0') << std::setw(16) << v;
  return oss.str();
}

// Portable SHA-like fingerprint: multi-pass FNV over chunks (not crypto-grade;
// integrity checksum for mesh packages — upgrade to real SHA256 when OpenSSL linked).
inline std::string fingerprint_bytes(const std::vector<float>& w) {
  std::uint64_t h1 = fnv1a64(w.data(), w.size() * sizeof(float));
  std::uint64_t h2 = 0xcbf29ce484222325ULL;
  for (std::size_t i = 0; i < w.size(); i += 17) {
    float v = w[i];
    h2 = fnv1a64(&v, sizeof(v), h2);
  }
  return hex64(h1) + hex64(h2);
}

inline std::size_t adapter_numel(int layers, int rank, int dim) {
  // Each layer: A[rank x dim] + B[dim x rank]  (LoRA-style)
  return static_cast<std::size_t>(layers) * (static_cast<std::size_t>(rank) * dim + static_cast<std::size_t>(dim) * rank);
}

// Digest free-text into a stable float feature stream (no raw text stored in delta).
inline std::vector<float> text_digest_features(const std::string& text, int dim) {
  std::vector<float> f(static_cast<std::size_t>(dim), 0.f);
  if (text.empty()) return f;
  std::uint64_t h = fnv1a64(text.data(), text.size());
  std::mt19937_64 rng(h);
  std::normal_distribution<float> nd(0.f, 1.f);
  for (int i = 0; i < dim; ++i) f[static_cast<std::size_t>(i)] = nd(rng);
  // Mix character unigram energy into first bins
  for (unsigned char c : text) {
    f[c % dim] += 0.01f;
  }
  float norm = 0.f;
  for (float v : f) norm += v * v;
  norm = std::sqrt(std::max(norm, 1e-12f));
  for (float& v : f) v /= norm;
  return f;
}

// One local continual step from experience digests → adapter delta (C++ only).
// Uses online gradient-style updates on LoRA A/B from hashed experience features.
inline void local_step(
    std::vector<float>& weights,
    AdapterMeta& meta,
    const std::vector<std::string>& experiences,
    float lr = 0.05f,
    std::uint64_t seed = 0) {
  const int L = meta.layers;
  const int R = meta.rank;
  const int D = meta.dim;
  const std::size_t n = adapter_numel(L, R, D);
  if (weights.size() != n) {
    weights.assign(n, 0.f);
    // init small random A, zero B (classic LoRA)
    std::mt19937_64 rng(seed ? seed : fnv1a64(meta.base_hash.data(), meta.base_hash.size()));
    std::normal_distribution<float> nd(0.f, 0.02f);
    std::size_t off = 0;
    for (int layer = 0; layer < L; ++layer) {
      for (int i = 0; i < R * D; ++i) weights[off++] = nd(rng);
      off += static_cast<std::size_t>(D * R); // B stays 0
    }
  }

  double total_loss = 0.0;
  for (const auto& exp : experiences) {
    auto feat = text_digest_features(exp, D);
    std::size_t off = 0;
    for (int layer = 0; layer < L; ++layer) {
      // A: R x D, B: D x R
      float* A = weights.data() + off;
      off += static_cast<std::size_t>(R * D);
      float* B = weights.data() + off;
      off += static_cast<std::size_t>(D * R);

      // h = A * feat  (R)
      std::vector<float> h(static_cast<std::size_t>(R), 0.f);
      for (int r = 0; r < R; ++r) {
        float s = 0.f;
        for (int d = 0; d < D; ++d) s += A[r * D + d] * feat[static_cast<std::size_t>(d)];
        h[static_cast<std::size_t>(r)] = s;
      }
      // out = B * h  (D)
      std::vector<float> out(static_cast<std::size_t>(D), 0.f);
      for (int d = 0; d < D; ++d) {
        float s = 0.f;
        for (int r = 0; r < R; ++r) s += B[d * R + r] * h[static_cast<std::size_t>(r)];
        out[static_cast<std::size_t>(d)] = s;
      }
      // target ≈ feat (reconstruct digest) — proxy continual objective
      float loss = 0.f;
      std::vector<float> grad_out(static_cast<std::size_t>(D));
      for (int d = 0; d < D; ++d) {
        float err = out[static_cast<std::size_t>(d)] - feat[static_cast<std::size_t>(d)];
        loss += err * err;
        grad_out[static_cast<std::size_t>(d)] = 2.f * err / static_cast<float>(D);
      }
      total_loss += loss / D;

      // dB = grad_out * h^T
      for (int d = 0; d < D; ++d) {
        for (int r = 0; r < R; ++r) {
          B[d * R + r] -= lr * grad_out[static_cast<std::size_t>(d)] * h[static_cast<std::size_t>(r)];
        }
      }
      // dh = B^T * grad_out
      std::vector<float> dh(static_cast<std::size_t>(R), 0.f);
      for (int r = 0; r < R; ++r) {
        float s = 0.f;
        for (int d = 0; d < D; ++d) s += B[d * R + r] * grad_out[static_cast<std::size_t>(d)];
        dh[static_cast<std::size_t>(r)] = s;
      }
      // dA = dh * feat^T
      for (int r = 0; r < R; ++r) {
        for (int d = 0; d < D; ++d) {
          A[r * D + d] -= lr * dh[static_cast<std::size_t>(r)] * feat[static_cast<std::size_t>(d)];
        }
      }
    }
  }
  meta.samples = experiences.size();
  meta.loss = experiences.empty() ? 0.0 : total_loss / static_cast<double>(experiences.size());
  meta.weights_sha256 = fingerprint_bytes(weights);
}

// Federated averaging of same-shaped adapter tensors.
inline bool fedavg(
    const std::vector<std::vector<float>>& deltas,
    const std::vector<double>& sample_weights,
    std::vector<float>& out) {
  if (deltas.empty()) return false;
  const std::size_t n = deltas[0].size();
  for (const auto& d : deltas) if (d.size() != n) return false;
  out.assign(n, 0.f);
  double wsum = 0.0;
  for (std::size_t i = 0; i < deltas.size(); ++i) {
    double w = (i < sample_weights.size() && sample_weights[i] > 0) ? sample_weights[i] : 1.0;
    wsum += w;
    for (std::size_t j = 0; j < n; ++j) out[j] += static_cast<float>(w * deltas[i][j]);
  }
  if (wsum <= 0) return false;
  for (float& v : out) v = static_cast<float>(v / wsum);
  return true;
}

inline bool write_bin(const std::string& path, const std::vector<float>& w) {
  std::ofstream f(path, std::ios::binary);
  if (!f) return false;
  f.write(reinterpret_cast<const char*>(w.data()), static_cast<std::streamsize>(w.size() * sizeof(float)));
  return static_cast<bool>(f);
}

inline bool read_bin(const std::string& path, std::vector<float>& w) {
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  if (!f) return false;
  auto sz = f.tellg();
  if (sz <= 0 || (sz % sizeof(float)) != 0) return false;
  w.resize(static_cast<std::size_t>(sz) / sizeof(float));
  f.seekg(0);
  f.read(reinterpret_cast<char*>(w.data()), sz);
  return static_cast<bool>(f);
}

inline std::string meta_to_json(const AdapterMeta& m) {
  std::ostringstream o;
  o << "{\n"
    << "  \"magic\": \"" << m.magic << "\",\n"
    << "  \"base_model\": \"" << m.base_model << "\",\n"
    << "  \"base_hash\": \"" << m.base_hash << "\",\n"
    << "  \"peer_id\": \"" << m.peer_id << "\",\n"
    << "  \"round\": " << m.round << ",\n"
    << "  \"rank\": " << m.rank << ",\n"
    << "  \"dim\": " << m.dim << ",\n"
    << "  \"layers\": " << m.layers << ",\n"
    << "  \"samples\": " << m.samples << ",\n"
    << "  \"loss\": " << std::setprecision(8) << m.loss << ",\n"
    << "  \"algo\": \"" << m.algo << "\",\n"
    << "  \"core\": \"" << m.core << "\",\n"
    << "  \"weights_sha256\": \"" << m.weights_sha256 << "\"\n"
    << "}\n";
  return o.str();
}

}  // namespace train
}  // namespace sophyane
