// g++ -std=c++17 hello_sophyane.cpp -lcurl -o hello_sophyane
#include <iostream>
#include "../include/sophyane_client.hpp"

int main() {
  try {
    sophyane::Client client;
    std::cout << "health: " << client.health() << "\n";
    std::cout << "backends: " << client.backends() << "\n";
    std::cout << "chat: " << client.chat("Say hi in three words", true) << "\n";
  } catch (const std::exception& ex) {
    std::cerr << "error: " << ex.what() << "\n";
    return 1;
  }
  return 0;
}
