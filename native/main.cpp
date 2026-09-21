#include "render.hpp"

#include <fstream>
#include <iostream>
#include <string_view>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {
int run(const std::filesystem::path &request, const std::filesystem::path &output) {
  try {
    std::ifstream input(request, std::ios::binary);
    if (!input)
      throw ksm2sdvx::RenderError("audio.request_read", "Cannot read the render request.");
    const auto result = ksm2sdvx::render(ksm2sdvx::Json::parse(input), output);
    std::cout << result.dump() << '\n';
    return 0;
  } catch (const ksm2sdvx::RenderError &error) {
    std::cout << ksm2sdvx::Json{{"protocol_version", 1},
                                {"error", {{"code", error.code}, {"message", error.what()}}}}
                     .dump()
              << '\n';
  } catch (const ksm2sdvx::Json::exception &error) {
    std::cout << ksm2sdvx::Json{{"protocol_version", 1},
                                {"error",
                                 {{"code", "audio.invalid_request"}, {"message", error.what()}}}}
                     .dump()
              << '\n';
  } catch (const std::exception &error) {
    std::cout << ksm2sdvx::Json{{"protocol_version", 1},
                                {"error",
                                 {{"code", "audio.render_failed"}, {"message", error.what()}}}}
                     .dump()
              << '\n';
  }
  return 1;
}
} // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) {
  // Dependencies sit beside this executable; exclude the working directory.
  SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_APPLICATION_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
  if (argc != 5 || std::wstring_view(argv[1]) != L"--request" ||
      std::wstring_view(argv[3]) != L"--output") {
    std::cerr << "Usage: ksm2sdvx-render --request REQUEST.json --output OUTPUT.wav\n";
    return 2;
  }
  std::wstring executable(32768, L'\0');
  const auto length =
      GetModuleFileNameW(nullptr, executable.data(), static_cast<DWORD>(executable.size()));
  if (length == 0 || length >= executable.size())
    return 1;
  executable.resize(length);
  const auto directory = std::filesystem::path(executable).parent_path();
  for (const auto *library : {L"bass.dll", L"bass_fx.dll"}) {
    if (!LoadLibraryExW((directory / library).c_str(), nullptr,
                        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32)) {
      std::cout << ksm2sdvx::Json{{"protocol_version", 1},
                                  {"error",
                                   {{"code", "audio.runtime_missing"},
                                    {"message", "Cannot load a bundled BASS runtime."}}}}
                       .dump()
                << '\n';
      return 1;
    }
  }
  return run(argv[2], argv[4]);
}
#else
int main(int argc, char **argv) {
  if (argc != 5 || std::string_view(argv[1]) != "--request" ||
      std::string_view(argv[3]) != "--output")
    return 2;
  return run(argv[2], argv[4]);
}
#endif
