// sophyane-train-core — pure C++ continual / federated adapter engine.
// Usage:
//   sophyane-train-core status
//   sophyane-train-core local-step --experience FILE --out DIR [--rank 8] [--base-hash H] [--peer ID]
//   sophyane-train-core aggregate --deltas DIR --out DIR
//   sophyane-train-core verify --dir DIR

#include "sophyane_train.hpp"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using namespace sophyane::train;

static void usage() {
  std::cerr
      << "sophyane-train-core " << kCoreVersion << " (C++ continual federated core)\n"
      << "  status\n"
      << "  local-step --experience FILE --out DIR [--rank N] [--dim N] [--layers N]\n"
      << "             [--base-hash H] [--peer ID] [--round N] [--lr F] [--seed N]\n"
      << "  aggregate --deltas DIR --out DIR\n"
      << "  verify --dir DIR\n";
}

static std::vector<std::string> read_experience_lines(const std::string& path) {
  std::ifstream in(path);
  if (!in) throw std::runtime_error("cannot open experience file: " + path);
  std::vector<std::string> lines;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    // Accept raw text or JSON lines; use whole line as experience digest source.
    lines.push_back(line);
  }
  return lines;
}

static int cmd_status() {
  std::cout << "{\n"
            << "  \"ok\": true,\n"
            << "  \"core\": \"" << kCoreVersion << "\",\n"
            << "  \"magic\": \"" << kMagic << "\",\n"
            << "  \"language\": \"C++17\",\n"
            << "  \"algo\": \"fedavg-lora-digest\",\n"
            << "  \"note\": \"Hardware-efficient PEFT deltas over existing base LLM weights\"\n"
            << "}\n";
  return 0;
}

static int cmd_local_step(const std::vector<std::string>& args) {
  std::string exp, outdir, base_hash = "unknown", peer = "local";
  int rank = 8, dim = 256, layers = 4;
  std::uint64_t round = 0, seed = 0;
  float lr = 0.05f;
  for (std::size_t i = 0; i < args.size(); ++i) {
    auto need = [&](const char* flag) -> std::string {
      if (i + 1 >= args.size()) throw std::runtime_error(std::string("missing value for ") + flag);
      return args[++i];
    };
    if (args[i] == "--experience") exp = need("--experience");
    else if (args[i] == "--out") outdir = need("--out");
    else if (args[i] == "--rank") rank = std::stoi(need("--rank"));
    else if (args[i] == "--dim") dim = std::stoi(need("--dim"));
    else if (args[i] == "--layers") layers = std::stoi(need("--layers"));
    else if (args[i] == "--base-hash") base_hash = need("--base-hash");
    else if (args[i] == "--peer") peer = need("--peer");
    else if (args[i] == "--round") round = std::stoull(need("--round"));
    else if (args[i] == "--lr") lr = std::stof(need("--lr"));
    else if (args[i] == "--seed") seed = std::stoull(need("--seed"));
  }
  if (exp.empty() || outdir.empty()) {
    usage();
    return 2;
  }
  auto experiences = read_experience_lines(exp);
  AdapterMeta meta;
  meta.base_hash = base_hash;
  meta.peer_id = peer;
  meta.round = round;
  meta.rank = rank;
  meta.dim = dim;
  meta.layers = layers;
  std::vector<float> w;
  local_step(w, meta, experiences, lr, seed);
  fs::create_directories(outdir);
  const std::string bin = (fs::path(outdir) / "adapter.bin").string();
  const std::string json = (fs::path(outdir) / "adapter.json").string();
  if (!write_bin(bin, w)) throw std::runtime_error("write adapter.bin failed");
  {
    std::ofstream jf(json);
    jf << meta_to_json(meta);
  }
  std::cout << meta_to_json(meta);
  return 0;
}

static int cmd_aggregate(const std::vector<std::string>& args) {
  std::string deltas_dir, outdir;
  for (std::size_t i = 0; i < args.size(); ++i) {
    if (args[i] == "--deltas" && i + 1 < args.size()) deltas_dir = args[++i];
    else if (args[i] == "--out" && i + 1 < args.size()) outdir = args[++i];
  }
  if (deltas_dir.empty() || outdir.empty()) {
    usage();
    return 2;
  }
  std::vector<std::vector<float>> all;
  std::vector<double> weights;
  AdapterMeta template_meta;
  bool have_meta = false;
  for (const auto& ent : fs::directory_iterator(deltas_dir)) {
    if (!ent.is_directory()) continue;
    auto bin = ent.path() / "adapter.bin";
    auto meta_path = ent.path() / "adapter.json";
    if (!fs::exists(bin)) continue;
    std::vector<float> w;
    if (!read_bin(bin.string(), w)) continue;
    double samples = 1.0;
    if (fs::exists(meta_path)) {
      std::ifstream mf(meta_path);
      std::string content((std::istreambuf_iterator<char>(mf)), std::istreambuf_iterator<char>());
      auto pos = content.find("\"samples\"");
      if (pos != std::string::npos) {
        auto colon = content.find(':', pos);
        if (colon != std::string::npos) samples = std::max(1.0, std::stod(content.substr(colon + 1)));
      }
      if (!have_meta) {
        // pull rank/dim/layers from first meta roughly
        auto geti = [&](const char* key, int defv) {
          auto p = content.find(std::string("\"") + key + "\"");
          if (p == std::string::npos) return defv;
          auto c = content.find(':', p);
          if (c == std::string::npos) return defv;
          return std::stoi(content.substr(c + 1));
        };
        template_meta.rank = geti("rank", 8);
        template_meta.dim = geti("dim", 256);
        template_meta.layers = geti("layers", 4);
        auto p = content.find("\"base_hash\"");
        if (p != std::string::npos) {
          auto q1 = content.find('"', content.find(':', p) + 1);
          auto q2 = content.find('"', q1 + 1);
          if (q1 != std::string::npos && q2 != std::string::npos)
            template_meta.base_hash = content.substr(q1 + 1, q2 - q1 - 1);
        }
        have_meta = true;
      }
    }
    all.push_back(std::move(w));
    weights.push_back(samples);
  }
  if (all.empty()) throw std::runtime_error("no peer deltas found under " + deltas_dir);
  std::vector<float> global_w;
  if (!fedavg(all, weights, global_w)) throw std::runtime_error("fedavg failed");
  template_meta.peer_id = "global";
  template_meta.samples = 0;
  for (double s : weights) template_meta.samples += static_cast<std::size_t>(s);
  template_meta.algo = "fedavg-lora-digest";
  template_meta.weights_sha256 = fingerprint_bytes(global_w);
  template_meta.round += 1;
  fs::create_directories(outdir);
  write_bin((fs::path(outdir) / "adapter.bin").string(), global_w);
  {
    std::ofstream jf((fs::path(outdir) / "adapter.json").string());
    jf << meta_to_json(template_meta);
  }
  std::cout << meta_to_json(template_meta);
  return 0;
}

static int cmd_verify(const std::vector<std::string>& args) {
  std::string dir;
  for (std::size_t i = 0; i < args.size(); ++i) {
    if (args[i] == "--dir" && i + 1 < args.size()) dir = args[++i];
  }
  if (dir.empty()) {
    usage();
    return 2;
  }
  std::vector<float> w;
  if (!read_bin((fs::path(dir) / "adapter.bin").string(), w))
    throw std::runtime_error("missing adapter.bin");
  auto fp = fingerprint_bytes(w);
  std::ifstream mf((fs::path(dir) / "adapter.json").string());
  std::string content((std::istreambuf_iterator<char>(mf)), std::istreambuf_iterator<char>());
  bool ok = content.find(fp) != std::string::npos;
  std::cout << "{\n  \"ok\": " << (ok ? "true" : "false")
            << ",\n  \"fingerprint\": \"" << fp << "\",\n  \"floats\": " << w.size() << "\n}\n";
  return ok ? 0 : 1;
}

int main(int argc, char** argv) {
  try {
    if (argc < 2) {
      usage();
      return 2;
    }
    std::string cmd = argv[1];
    std::vector<std::string> rest;
    for (int i = 2; i < argc; ++i) rest.emplace_back(argv[i]);
    if (cmd == "status") return cmd_status();
    if (cmd == "local-step") return cmd_local_step(rest);
    if (cmd == "aggregate") return cmd_aggregate(rest);
    if (cmd == "verify") return cmd_verify(rest);
    usage();
    return 2;
  } catch (const std::exception& ex) {
    std::cerr << "{\"ok\": false, \"error\": \"" << ex.what() << "\"}\n";
    return 1;
  }
}
