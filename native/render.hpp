#pragma once

#include <filesystem>
#include <nlohmann/json.hpp>
#include <stdexcept>
#include <string>

namespace ksm2sdvx {
using Json = nlohmann::json;

class RenderError : public std::runtime_error {
public:
  const std::string code;
  RenderError(std::string code, std::string message)
      : std::runtime_error(std::move(message)), code(std::move(code)) {}
};

// Inputs have already been resolved and resampled by the application boundary.
Json render(const Json &request, const std::filesystem::path &destination);
} // namespace ksm2sdvx
