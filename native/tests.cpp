#include "render.hpp"

#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <numbers>
#include <vector>

namespace {
using ksm2sdvx::Json;
void require(bool condition, const char *message) {
  if (!condition)
    throw std::runtime_error(message);
}
void u16(std::ostream &out, unsigned value) {
  const char data[]{static_cast<char>(value), static_cast<char>(value >> 8)};
  out.write(data, 2);
}
void u32(std::ostream &out, unsigned value) {
  const char data[]{static_cast<char>(value), static_cast<char>(value >> 8),
                    static_cast<char>(value >> 16), static_cast<char>(value >> 24)};
  out.write(data, 4);
}
void input_wave(const std::filesystem::path &path, const std::vector<float> &values) {
  std::ofstream out(path, std::ios::binary);
  const auto size = static_cast<unsigned>(values.size() * sizeof(float));
  out.write("RIFF", 4);
  u32(out, size + 36);
  out.write("WAVEfmt ", 8);
  u32(out, 16);
  u16(out, 3);
  u16(out, 2);
  u32(out, 44100);
  u32(out, 352800);
  u16(out, 8);
  u16(out, 32);
  out.write("data", 4);
  u32(out, size);
  out.write(reinterpret_cast<const char *>(values.data()), size);
}
std::vector<float> output_wave(const std::filesystem::path &path, std::size_t frames) {
  std::ifstream input(path, std::ios::binary);
  input.seekg(56);
  std::vector<float> values(frames * 2);
  input.read(reinterpret_cast<char *>(values.data()),
             static_cast<std::streamsize>(values.size() * sizeof(float)));
  require(static_cast<bool>(input), "Cannot read rendered PCM");
  return values;
}
std::string utf8(const std::filesystem::path &path) {
  const auto value = path.u8string();
  return {reinterpret_cast<const char *>(value.data()), value.size()};
}
Json request(const std::filesystem::path &source) {
  return {{"protocol_version", 1},
          {"sample_rate", 44100},
          {"duration_frames", 1024},
          {"offset_frames", 0},
          {"bgm_volume", 1},
          {"tracks", {{{"id", "main"}, {"path", utf8(source)}}}},
          {"samples", Json::array()},
          {"program",
           {{"tempos", {{{"frame", 0}, {"pulse", 0}, {"bpm", 120}}}},
            {"effects", Json::array()},
            {"changes", Json::array()},
            {"fx", Json::array()},
            {"fx_holds", Json::array()},
            {"laser_events", Json::array()},
            {"lasers", Json::array()},
            {"keysounds", Json::array()},
            {"peaking_filter_delay_frames", 0}}}};
}
Json effect(std::string type, Json parameters = Json::object()) {
  return {{"name", type},         {"type", type},    {"bus", "fx"}, {"parameters", parameters},
          {"triggers", {0, 512}}, {"builtin", false}};
}
void activate(Json &data, const std::string &name, int start = 0, int end = 1024) {
  data["program"]["fx_holds"].push_back({{"start_frame", start}, {"end_frame", end}, {"lane", 0}});
  data["program"]["fx"].push_back({{"start_frame", start},
                                   {"end_frame", end},
                                   {"lane", 0},
                                   {"hold_start_frame", start},
                                   {"effect", name},
                                   {"parameters", Json::object()}});
}
} // namespace

int main() {
  const auto directory =
      std::filesystem::temp_directory_path() /
      ("ksm2sdvx-native-tests-" +
       std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
  try {
    std::filesystem::create_directories(directory);
    const auto source = directory / "source.wav";
    const auto output = directory / "output.wav";
    std::vector<float> original(2048);
    for (std::size_t i = 0; i < original.size() / 2; ++i)
      original[i * 2] = original[i * 2 + 1] = static_cast<float>(.25 * std::sin(i * .061));
    input_wave(source, original);
    const auto base = request(source);
    const auto receipt = ksm2sdvx::render(base, output);
    require(receipt.at("frames") == 1024, "Wrong duration");
    require(output_wave(output, 1024) == original, "Dry rendering changes PCM");

    auto offset = base;
    offset["offset_frames"] = -13;
    offset["bgm_volume"] = .5;
    ksm2sdvx::render(offset, output);
    const auto shifted = output_wave(output, 1037);
    for (int i = 0; i < 26; ++i)
      require(shifted[i] == 0, "Negative offset did not insert silence");
    require(shifted[76] == original[50] * .5f, "Offset or relative BGM volume is incorrect");

    auto crusher = base;
    crusher["program"]["effects"].push_back(
        effect("bitcrusher", {{"reduction", "16samples"}, {"mix", "100%"}}));
    activate(crusher, "bitcrusher", 127, 899);
    ksm2sdvx::render(crusher, output);
    const auto crushed = output_wave(output, 1024);
    require(crushed != original, "Bitcrusher did not process audio");
    require(std::equal(original.begin(), original.begin() + 254, crushed.begin()),
            "FX started before its exact frame");
    require(std::equal(original.begin() + 1798, original.end(), crushed.begin() + 1798),
            "FX continued beyond its exact frame");
    ksm2sdvx::render(crusher, output);
    require(output_wave(output, 1024) == crushed, "Rendering is not deterministic");

    auto phaser = base;
    phaser["program"]["effects"].push_back(
        effect("phaser", {{"mix", "100%"}, {"feedback", "50%"}}));
    activate(phaser, "phaser");
    ksm2sdvx::render(phaser, output);
    const auto full_phaser = output_wave(output, 1024);
    phaser["bgm_volume"] = .37;
    ksm2sdvx::render(phaser, output);
    const auto quiet_phaser = output_wave(output, 1024);
    for (std::size_t i = 0; i < full_phaser.size(); ++i)
      require(quiet_phaser[i] == full_phaser[i] * .37f,
              "Relative BGM gain was applied before effect processing");

    auto precedence = crusher;
    precedence["program"]["fx"][0]["start_frame"] = 0;
    precedence["program"]["fx"][0]["hold_start_frame"] = 0;
    precedence["program"]["fx"][0]["end_frame"] = 1024;
    precedence["program"]["fx"][0]["parameters"] = {{"mix", "0%"}};
    precedence["program"]["fx_holds"] = {{{"start_frame", 0}, {"end_frame", 1024}, {"lane", 0}}};
    precedence["program"]["fx"].push_back({{"start_frame", 401},
                                           {"end_frame", 801},
                                           {"lane", 1},
                                           {"hold_start_frame", 401},
                                           {"effect", "bitcrusher"},
                                           {"parameters", {{"mix", "100%"}}}});
    precedence["program"]["changes"].push_back({{"frame", 211},
                                                {"bus", "fx"},
                                                {"effect", "bitcrusher"},
                                                {"parameter", "mix"},
                                                {"value", "100%"}});
    ksm2sdvx::render(precedence, output);
    const auto overridden = output_wave(output, 1024);
    require(std::equal(original.begin(), original.begin() + 802, overridden.begin()),
            "Persistent parameters overrode note parameters");
    require(!std::equal(original.begin() + 802, original.begin() + 1602, overridden.begin() + 802),
            "Later FX hold did not take precedence");
    require(std::equal(original.begin() + 1602, original.end(), overridden.begin() + 1602),
            "Earlier hold did not regain its override");

    auto laser = base;
    auto laser_effect =
        effect("bitcrusher", {{"reduction", "1samples-32samples"}, {"mix", "100%"}});
    laser_effect["bus"] = "laser";
    laser["program"]["effects"].push_back(laser_effect);
    laser["program"]["laser_events"].push_back({{"frame", 0}, {"effect", "bitcrusher"}});
    laser["program"]["lasers"].push_back({{"start_frame", 129},
                                          {"end_frame", 899},
                                          {"lane", 0},
                                          {"points",
                                           {{{"frame", 129},
                                             {"pulse", 129.0 * 480 / 44100},
                                             {"incoming", 0},
                                             {"outgoing", 0},
                                             {"curve_x", .5},
                                             {"curve_y", .5}},
                                            {{"frame", 401},
                                             {"pulse", 401.0 * 480 / 44100},
                                             {"incoming", 0},
                                             {"outgoing", 1},
                                             {"curve_x", .5},
                                             {"curve_y", .5}},
                                            {{"frame", 899},
                                             {"pulse", 899.0 * 480 / 44100},
                                             {"incoming", 1},
                                             {"outgoing", 1},
                                             {"curve_x", .5},
                                             {"curve_y", .5}}}}});
    ksm2sdvx::render(laser, output);
    const auto filtered = output_wave(output, 1024);
    require(std::equal(original.begin(), original.begin() + 258, filtered.begin()),
            "Laser DSP began outside the section");
    require(!std::equal(original.begin() + 802, original.begin() + 1798, filtered.begin() + 802),
            "Laser jump did not update its effect value");
    require(std::equal(original.begin() + 1798, original.end(), filtered.begin() + 1798),
            "Laser DSP continued outside the section");

    auto invalid = crusher;
    invalid["program"]["effects"][0]["parameters"]["reduction"] = "16garbagesamples";
    bool rejected = false;
    try {
      ksm2sdvx::render(invalid, output);
    } catch (const ksm2sdvx::RenderError &error) {
      rejected = error.code == "audio.parameter";
    }
    require(rejected, "Invalid effect parameter was accepted");

    const auto sample = directory / "chip.wav";
    input_wave(sample, std::vector<float>(200, .1f));
    auto keys = base;
    keys["bgm_volume"] = 0;
    keys["samples"].push_back({{"id", "chip"}, {"path", utf8(sample)}});
    keys["program"]["keysounds"] = {
        {{"frame", 101}, {"lane", 0}, {"resource_id", "chip"}, {"volume", 1}},
        {{"frame", 151}, {"lane", 1}, {"resource_id", "chip"}, {"volume", .5}}};
    ksm2sdvx::render(keys, output);
    const auto mixed = output_wave(output, 1024);
    require(mixed[200] == 0 && mixed[202] == .1f, "Keysound boundary is incorrect");
    require(mixed[302] == .05f, "Keysound retrigger did not replace the existing voice");
    require(mixed[502] == 0, "Keysound tail did not end");

    auto polyphonic = keys;
    polyphonic["program"]["key_sound_polyphony"] = 10;
    ksm2sdvx::render(polyphonic, output);
    const auto overlap = output_wave(output, 1024);
    require(std::abs(overlap[302] - .15f) < 1e-6f,
            "Legacy keysounds did not retain overlapping voices");
    polyphonic["program"]["keysounds"] = Json::array();
    for (int i = 0; i < 11; ++i)
      polyphonic["program"]["keysounds"].push_back(
          {{"frame", 101 + i * 5},
           {"lane", i % 2},
           {"resource_id", "chip"},
           {"volume", i == 0 ? 1.0 : (i == 10 ? .25 : .5)}});
    ksm2sdvx::render(polyphonic, output);
    const auto limited = output_wave(output, 1024);
    require(std::abs(limited[302] - .475f) < 1e-6f,
            "Full keysound voice pool did not replace its longest-playing voice");
    require(limited[400] == limited[402], "The replaced keysound voice remained audible");

    const auto alternate = directory / "alternate.wav";
    input_wave(alternate, std::vector<float>(2048, .125f));
    auto switched = base;
    switched["tracks"].push_back({{"id", "alternate"}, {"path", utf8(alternate)}});
    switched["program"]["effects"].push_back(effect("switch_audio", {{"filename", "alternate"}}));
    activate(switched, "switch_audio", 129, 301);
    auto right_switch = effect("switch_audio", {{"filename", "main"}});
    right_switch["name"] = "right_switch";
    switched["program"]["effects"].push_back(right_switch);
    switched["program"]["fx"].push_back({{"start_frame", 0},
                                         {"end_frame", 1024},
                                         {"lane", 1},
                                         {"hold_start_frame", 0},
                                         {"effect", "right_switch"},
                                         {"parameters", Json::object()}});
    ksm2sdvx::render(switched, output);
    const auto routed = output_wave(output, 1024);
    require(routed[256] == original[256] && routed[258] == .125f && routed[600] == .125f &&
                routed[602] == original[602],
            "switch_audio routing is not frame-aligned");

    // Construct and process every DSP family, including effects with delay buffers.
    for (const auto *type : {"retrigger", "gate", "flanger", "bitcrusher", "phaser", "pitch_shift",
                             "wobble", "tapestop", "echo", "sidechain", "peaking_filter",
                             "high_pass_filter", "low_pass_filter"}) {
      auto data = base;
      data["program"]["effects"].push_back(effect(type));
      activate(data, type);
      ksm2sdvx::render(data, output);
      const auto values = output_wave(output, 1024);
      require(std::all_of(values.begin(), values.end(),
                          [](float value) { return std::isfinite(value); }),
              "DSP generated nonfinite output");
    }
    auto signed_range = base;
    signed_range["program"]["effects"].push_back(effect("pitch_shift", {{"pitch", "-12--7"}}));
    activate(signed_range, "pitch_shift");
    ksm2sdvx::render(signed_range, output);
    for (const auto &file : {source, output, sample, alternate})
      std::filesystem::remove(file);
    std::filesystem::remove(directory);
    std::cout << "Native renderer tests passed.\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
