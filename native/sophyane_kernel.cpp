#include <algorithm>
#include <cctype>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return std::tolower(c); });
    return s;
}

static bool contains_any(const std::string& s, const std::vector<std::string>& words) {
    for (const auto& w : words) if (s.find(w) != std::string::npos) return true;
    return false;
}

static std::string json_escape(const std::string& s) {
    std::ostringstream out;
    for (unsigned char c : s) {
        switch (c) {
            case '\\': out << "\\\\"; break;
            case '"': out << "\\\""; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default: if (c >= 32) out << c;
        }
    }
    return out.str();
}

static int classify(const std::string& input) {
    const std::string s = lower(input);
    const std::vector<std::string> build = {
        "build", "make", "create", "implement", "develop", "write", "fix", "repair",
        "compile", "run", "test", "deploy", "open", "game", "app", "website", "script",
        "dashboard", "daemon", "kernel", "harness", "integrate", "optimize", "audit"
    };
    const std::vector<std::string> chat = {
        "what is", "explain", "suggest", "recommend", "how are you", "hello", " hi"
    };
    bool execute = contains_any(s, build) && !contains_any(s, chat);
    std::cout << "{\"mode\":\"" << (execute ? "execution" : "chat")
              << "\",\"engine\":\"native-cpp\"}\n";
    return 0;
}

static int workspace_status(const fs::path& root) {
    std::error_code ec;
    fs::path resolved = fs::weakly_canonical(root, ec);
    if (ec || !fs::exists(resolved)) {
        std::cout << "{\"ok\":false,\"error\":\"workspace not found\"}\n";
        return 2;
    }
    std::cout << "{\"ok\":true,\"workspace\":\"" << json_escape(resolved.string()) << "\",\"files\":[";
    bool first = true;
    size_t count = 0;
    for (const auto& entry : fs::recursive_directory_iterator(resolved, fs::directory_options::skip_permission_denied, ec)) {
        if (ec || count >= 100) break;
        if (!entry.is_regular_file(ec)) continue;
        if (!first) std::cout << ',';
        first = false;
        auto rel = fs::relative(entry.path(), resolved, ec);
        std::cout << "{\"path\":\"" << json_escape(rel.string()) << "\",\"bytes\":" << entry.file_size(ec) << "}";
        ++count;
    }
    std::cout << "]}\n";
    return 0;
}

int main(int argc, char** argv) {
    if (argc >= 3 && std::string(argv[1]) == "--classify") return classify(argv[2]);
    if (argc >= 3 && std::string(argv[1]) == "--workspace-status") return workspace_status(argv[2]);
    if (argc >= 2 && std::string(argv[1]) == "--version") {
        std::cout << "sophyane-kernel 0.1\n";
        return 0;
    }
    std::cerr << "usage: sophyane-kernel --classify TEXT | --workspace-status PATH | --version\n";
    return 64;
}
