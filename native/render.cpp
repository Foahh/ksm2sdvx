#include "render.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <ksmaudio/AudioEffect/AudioEffectParamValidator.hpp>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <span>
#include <unordered_map>
#include <vector>

#include <ksmaudio/AudioEffect/All.hpp>
#include <ksmaudio/Stream.hpp>

namespace ksm2sdvx {
namespace {
namespace ae = ksmaudio::AudioEffect;
using Frame = std::int64_t;
constexpr Frame rate = 44100;
constexpr Frame block_frames = 64;
using Parameters = ae::ParamValueSetDict;

[[noreturn]] void invalid(const std::string &message) {
  throw RenderError("audio.invalid_request", message);
}

Frame integer(const Json &value, const std::string &field, bool negative = false) {
  if (!value.is_number_integer())
    invalid(field + " must be an integer.");
  const auto result = value.get<Frame>();
  if ((!negative && result < 0) || std::abs(static_cast<double>(result)) > rate * 60 * 60 * 6)
    invalid(field + " is outside the supported frame range.");
  return result;
}

double number(const Json &value, const std::string &field) {
  if (!value.is_number())
    invalid(field + " must be numeric.");
  const auto result = value.get<double>();
  if (!std::isfinite(result))
    invalid(field + " must be finite.");
  return result;
}

std::filesystem::path path_from_utf8(const std::string &value) {
  return std::filesystem::path(
      std::u8string_view(reinterpret_cast<const char8_t *>(value.data()), value.size()));
}

struct Bass {
  Bass() {
    if (BASS_GetVersion() != 0x02041203 || BASS_FX_GetVersion() != 0x02040c06)
      throw RenderError("audio.runtime_version",
                        "The bundled BASS libraries do not match the tested versions.");
    if (!BASS_Init(0, rate, 0, nullptr, nullptr))
      throw RenderError("audio.runtime_init", "Cannot initialize the offline audio device.");
    BASS_SetConfig(BASS_CONFIG_FLOATDSP, TRUE);
  }
  ~Bass() { BASS_Free(); }
};

class MusicStream {
  ksmaudio::Stream stream;

public:
  const Frame frames;

  MusicStream(const std::filesystem::path &path, double volume)
      : stream(path_utf8(path), volume, true, true, false, 1.0, true),
        frames(static_cast<Frame>(std::llround(stream.duration().count() * rate))) {
    if (stream.sampleRate() != rate || stream.numChannels() != 2)
      throw RenderError("audio.input_format", "Renderer inputs must be stereo 44100 Hz audio.");
  }

  static std::string path_utf8(const std::filesystem::path &path) {
    const auto value = path.u8string();
    return {reinterpret_cast<const char *>(value.data()), value.size()};
  }

  void attach(ae::IAudioEffect *effect, int priority) {
    if (!stream.addAudioEffect(effect, priority))
      throw RenderError("audio.runtime_effect", "Cannot attach an audio effect to the music stream.");
  }

  void read(Frame frame, Frame offset, std::span<float> output) {
    std::fill(output.begin(), output.end(), 0.0f);
    const auto source_frame = frame + offset;
    if (source_frame < 0 || source_frame >= frames)
      return;
    if (frame == 0 && offset > 0)
      stream.seekPosSec(ksmaudio::SecondsF{static_cast<double>(offset) / rate});
    const auto count = stream.getData(output.data(), static_cast<DWORD>(output.size_bytes()));
    if (count == static_cast<DWORD>(-1))
      throw RenderError("audio.decode", "Cannot read the effected music stream.");
    if (count % (2 * sizeof(float)) != 0)
      throw RenderError("audio.decode", "Incomplete stereo PCM frame.");
  }
};

std::vector<float> decode(const std::filesystem::path &path) {
  const auto stream = BASS_StreamCreateFile(FALSE, path.c_str(), 0, 0,
                                            BASS_STREAM_DECODE | BASS_SAMPLE_FLOAT | BASS_UNICODE);
  if (!stream)
    throw RenderError("audio.decode", "Cannot decode audio: " + path.filename().string());
  struct StreamGuard {
    HSTREAM value;
    ~StreamGuard() { BASS_StreamFree(value); }
  } guard{stream};
  BASS_CHANNELINFO info{};
  if (!BASS_ChannelGetInfo(stream, &info) || info.freq != rate || info.chans != 2)
    throw RenderError("audio.input_format", "Renderer inputs must be stereo 44100 Hz audio.");
  std::vector<float> result;
  std::array<float, 16384> buffer{};
  for (;;) {
    const DWORD count =
        BASS_ChannelGetData(stream, buffer.data(), static_cast<DWORD>(sizeof(buffer)));
    if (count == static_cast<DWORD>(-1)) {
      if (BASS_ErrorGetCode() == BASS_ERROR_ENDED)
        break;
      throw RenderError("audio.decode", "An audio stream could not be fully decoded.");
    }
    if (count == 0)
      break;
    if (count % (2 * sizeof(float)) != 0)
      throw RenderError("audio.decode", "Incomplete stereo PCM frame.");
    const auto samples = count / sizeof(float);
    for (std::size_t i = 0; i < samples; ++i)
      if (!std::isfinite(buffer[i]))
        throw RenderError("audio.nonfinite", "Input audio contains non-finite samples.");
    result.insert(result.end(), buffer.begin(), buffer.begin() + samples);
    if (result.size() > static_cast<std::size_t>(rate * 60 * 60 * 6 * 2))
      throw RenderError("audio.too_long", "Audio exceeds the six-hour render limit.");
  }
  return result;
}

void write_u16(std::ostream &out, std::uint16_t value) {
  const char data[]{static_cast<char>(value), static_cast<char>(value >> 8)};
  out.write(data, 2);
}
void write_u32(std::ostream &out, std::uint32_t value) {
  const char data[]{static_cast<char>(value), static_cast<char>(value >> 8),
                    static_cast<char>(value >> 16), static_cast<char>(value >> 24)};
  out.write(data, 4);
}

class WaveWriter {
  std::ofstream out;

public:
  WaveWriter(const std::filesystem::path &path, Frame frames) : out(path, std::ios::binary) {
    if (!out)
      throw RenderError("audio.output", "Cannot open the rendered WAV destination.");
    if (frames > (std::numeric_limits<std::uint32_t>::max() - 48) / 8)
      throw RenderError("audio.too_long", "Rendered audio exceeds the WAV size limit.");
    const auto bytes = static_cast<std::uint32_t>(frames * 8);
    out.write("RIFF", 4);
    write_u32(out, bytes + 48);
    out.write("WAVEfmt ", 8);
    write_u32(out, 16);
    write_u16(out, 3);
    write_u16(out, 2);
    write_u32(out, rate);
    write_u32(out, rate * 8);
    write_u16(out, 8);
    write_u16(out, 32);
    out.write("fact", 4);
    write_u32(out, 4);
    write_u32(out, static_cast<std::uint32_t>(frames));
    out.write("data", 4);
    write_u32(out, bytes);
  }
  void append(std::span<const float> data) {
    for (const auto value : data)
      if (!std::isfinite(value))
        throw RenderError("audio.nonfinite", "An effect produced non-finite audio.");
    out.write(reinterpret_cast<const char *>(data.data()),
              static_cast<std::streamsize>(data.size_bytes()));
    if (!out)
      throw RenderError("audio.output", "Cannot write the rendered WAV.");
  }
  void close() {
    out.close();
    if (!out)
      throw RenderError("audio.output", "Cannot finish the rendered WAV.");
  }
};

ae::ParamID parameter_id(const std::string &name) {
  if (name == "bandwidth")
    return ae::ParamID::kBandwidth;
  const auto it = ae::kStrToParamID.find(name);
  if (it == ae::kStrToParamID.end())
    throw RenderError("audio.parameter", "Unknown effect parameter: " + name);
  return it->second;
}

ae::ValueSet parse_value(ae::ParamID id, const std::string &raw) {
  const auto type = ae::kParamIDType.at(id);
  // Use the runtime parser's split rule so signed ranges such as -12--7
  // validate as two scalar values, rather than as a malformed negative number.
  const auto arrow = raw.find('>');
  const auto dash = raw.find('-', (arrow == std::string::npos ? 0 : arrow + 1) + 1);
  const auto off = arrow == std::string::npos ? raw.substr(0, dash) : raw.substr(0, arrow);
  const auto on_min =
      arrow == std::string::npos
          ? off
          : raw.substr(arrow + 1, dash == std::string::npos ? dash : dash - arrow - 1);
  const auto on_max = dash == std::string::npos ? on_min : raw.substr(dash + 1);
  for (const auto &scalar : {off, on_min, on_max}) {
    const auto validation = ae::ValidateParamValue(type, scalar);
    if (!validation.isValid || scalar.empty())
      throw RenderError("audio.parameter",
                        "Invalid effect parameter: " + raw + " (" + validation.errorMessage + ")");
  }
  bool success = false;
  const auto result = ae::StrToValueSet(type, raw, &success);
  if (!success || !std::isfinite(result.off) || !std::isfinite(result.onMin) ||
      !std::isfinite(result.onMax))
    throw RenderError("audio.parameter", "Cannot parse effect parameter: " + raw);
  return result;
}

struct Effect {
  std::string name;
  std::string type;
  bool laser;
  bool builtin;
  int priority = 0;
  std::string switch_track;
  std::unique_ptr<ae::IAudioEffect> dsp;
  Parameters defaults;
  std::map<Frame, Parameters> changes;
};

template <class T> void create_dsp(Effect &effect, const std::set<float> &triggers) {
  if constexpr (T::kIsWithTrigger)
    effect.dsp = std::make_unique<T>(rate, 2, effect.laser, triggers);
  else
    effect.dsp = std::make_unique<T>(rate, 2, effect.laser);
  effect.priority = T::kPriority;
  effect.defaults = effect.dsp->paramValueSetDict();
}

Parameters parse_parameters(const Json &values, const Effect &effect) {
  if (!values.is_object())
    invalid("Effect parameters must be an object.");
  Parameters result;
  for (auto it = values.begin(); it != values.end(); ++it) {
    const auto id = parameter_id(it.key());
    const auto value = parse_value(id, it.value().get<std::string>());
    if (id == ae::ParamID::kUpdatePeriod && (effect.type == "retrigger" || effect.type == "echo"))
      continue;
    if (!effect.defaults.contains(id))
      throw RenderError("audio.parameter",
                        "Parameter " + it.key() + " is not supported by " + effect.type + '.');
    result[id] = value;
  }
  return result;
}

Effect make_effect(const Json &definition) {
  Effect effect;
  effect.name = definition.at("name").get<std::string>();
  effect.type = definition.at("type").get<std::string>();
  const auto bus = definition.at("bus").get<std::string>();
  if (bus != "fx" && bus != "laser")
    invalid("Effect bus must be fx or laser.");
  effect.laser = bus == "laser";
  effect.builtin = definition.value("builtin", false);
  std::set<float> triggers;
  for (const auto &frame : definition.at("triggers"))
    triggers.insert(static_cast<float>(integer(frame, "trigger frame")) / rate);
  if (effect.type == "switch_audio") {
    const auto &params = definition.at("parameters");
    if (params.size() != 1 || !params.contains("filename"))
      throw RenderError("audio.parameter", "switch_audio requires only a filename parameter.");
    effect.switch_track = params.at("filename").get<std::string>();
    return effect;
  }
#define EFFECT_CASE(name, cpp_type)                                                                \
  if (effect.type == name)                                                                         \
    create_dsp<ksmaudio::cpp_type>(effect, triggers);                                              \
  else
  EFFECT_CASE("retrigger", Retrigger)
  EFFECT_CASE("gate", Gate)
  EFFECT_CASE("flanger", Flanger)
  EFFECT_CASE("bitcrusher", Bitcrusher)
  EFFECT_CASE("phaser", Phaser)
  EFFECT_CASE("pitch_shift", PitchShift)
  EFFECT_CASE("wobble", Wobble)
  EFFECT_CASE("tapestop", Tapestop)
  EFFECT_CASE("echo", Echo)
  EFFECT_CASE("sidechain", Sidechain)
  EFFECT_CASE("peaking_filter", PeakingFilter)
  EFFECT_CASE("high_pass_filter", HighPassFilter)
  EFFECT_CASE("low_pass_filter", LowPassFilter)
  throw RenderError("audio.effect_type", "Unknown effect type: " + effect.type);
#undef EFFECT_CASE
  for (const auto &[id, value] : parse_parameters(definition.at("parameters"), effect))
    effect.defaults[id] = value;
  return effect;
}

struct Tempo {
  Frame frame;
  double pulse;
  double bpm;
};
struct Point {
  Frame frame;
  double pulse;
  double incoming;
  double outgoing;
  double x;
  double y;
};
struct Laser {
  Frame start;
  Frame end;
  int lane;
  std::vector<Point> points;
};
struct Hold {
  Frame start;
  Frame end;
  int lane;
};
struct Invocation {
  Hold span;
  Frame hold_start;
  std::size_t effect;
  Parameters parameters;
};
struct KeySound {
  Frame frame;
  std::string id;
  float volume;
};

int lane_value(const Json &value) {
  const auto lane = integer(value, "lane");
  if (lane > 1)
    invalid("Lane must be 0 or 1.");
  return static_cast<int>(lane);
}
Hold hold(const Json &value) {
  Hold result{integer(value.at("start_frame"), "start_frame"),
              integer(value.at("end_frame"), "end_frame"), lane_value(value.at("lane"))};
  if (result.end < result.start)
    invalid("An interval ends before it starts.");
  return result;
}

double curve(double ratio, double x, double y) {
  if (ratio <= 0)
    return 0;
  if (ratio >= 1)
    return 1;
  const auto denominator = x + std::sqrt(x * x + (1 - 2 * x) * ratio);
  const auto t = denominator == 0 ? 0 : ratio / denominator;
  return 2 * y * t * (1 - t) + t * t;
}

double laser_value(const Laser &laser, Frame frame, double pulse) {
  const auto it = std::upper_bound(laser.points.begin(), laser.points.end(), frame,
                                   [](Frame f, const Point &point) { return f < point.frame; });
  if (it == laser.points.begin())
    return it->incoming;
  const auto &previous = *std::prev(it);
  if (it == laser.points.end() || previous.frame == frame)
    return previous.outgoing;
  const auto ratio = (pulse - previous.pulse) / (it->pulse - previous.pulse);
  return std::lerp(previous.outgoing, it->incoming,
                   curve(std::clamp(ratio, 0., 1.), previous.x, previous.y));
}

struct Program {
  std::vector<Tempo> tempos;
  std::vector<Effect> effects;
  std::vector<Hold> holds;
  std::vector<Invocation> invocations;
  std::vector<Laser> lasers;
  std::map<Frame, std::optional<std::size_t>> laser_events;
  std::vector<KeySound> keysounds;
  std::set<Frame> boundaries{0};
  Frame peak_delay = 0;
  std::size_t key_sound_polyphony = 1;

  std::size_t effect_index(const std::string &name, bool laser) const {
    for (std::size_t i = 0; i < effects.size(); ++i)
      if (effects[i].name == name && effects[i].laser == laser)
        return i;
    throw RenderError("audio.effect_name", "Undefined effect: " + name);
  }
  const Tempo &tempo_at(Frame frame) const {
    auto it = std::upper_bound(tempos.begin(), tempos.end(), frame,
                               [](Frame value, const Tempo &tempo) { return value < tempo.frame; });
    return it == tempos.begin() ? tempos.front() : *std::prev(it);
  }
  double pulse_at(Frame frame) const {
    const auto &tempo = tempo_at(frame);
    return tempo.pulse + static_cast<double>(frame - tempo.frame) * tempo.bpm * 240 / (rate * 60);
  }
};

Program parse_program(const Json &data) {
  Program program;
  const auto polyphony = integer(data.value("key_sound_polyphony", Json(1)), "key_sound_polyphony");
  if (polyphony < 1 || polyphony > 65535)
    invalid("Keysound polyphony must be within 1–65535.");
  program.key_sound_polyphony = static_cast<std::size_t>(polyphony);
  program.peak_delay = integer(data.value("peaking_filter_delay_frames", Json(0)),
                               "peaking_filter_delay_frames", true);
  for (const auto &item : data.at("tempos")) {
    const auto frame = integer(item.at("frame"), "tempo frame");
    const auto bpm = number(item.at("bpm"), "bpm");
    if (bpm <= 0 || (!program.tempos.empty() && frame <= program.tempos.back().frame))
      invalid("Tempos must be positive and strictly ordered.");
    program.tempos.push_back({frame, number(item.at("pulse"), "tempo pulse"), bpm});
    program.boundaries.insert(frame);
    if (frame + program.peak_delay >= 0)
      program.boundaries.insert(frame + program.peak_delay);
  }
  if (program.tempos.empty() || program.tempos.front().frame != 0)
    invalid("A tempo is required at frame zero.");
  for (const auto &item : data.at("effects")) {
    auto effect = make_effect(item);
    for (const auto &previous : program.effects)
      if (previous.laser == effect.laser && previous.name == effect.name)
        invalid("Duplicate effect definition.");
    for (const auto &frame : item.at("triggers"))
      program.boundaries.insert(integer(frame, "trigger frame"));
    program.effects.push_back(std::move(effect));
  }
  for (const auto &item : data.at("changes")) {
    auto &effect = program.effects.at(
        program.effect_index(item.at("effect").get<std::string>(), item.at("bus") == "laser"));
    const auto frame = integer(item.at("frame"), "parameter frame");
    if (!effect.dsp)
      throw RenderError("audio.parameter",
                        "switch_audio parameters cannot change during a render.");
    const auto values =
        parse_parameters(Json{{item.at("parameter").get<std::string>(), item.at("value")}}, effect);
    for (const auto &[id, value] : values)
      effect.changes[frame][id] = value;
    program.boundaries.insert(frame);
  }
  for (const auto &item : data.at("fx_holds")) {
    const auto span = hold(item);
    program.holds.push_back(span);
    program.boundaries.insert(span.start);
    program.boundaries.insert(span.end);
  }
  for (const auto &item : data.at("fx")) {
    const auto span = hold(item);
    const auto index = program.effect_index(item.at("effect").get<std::string>(), false);
    const auto &effect = program.effects[index];
    if (!effect.dsp && !item.at("parameters").empty())
      throw RenderError("audio.parameter", "switch_audio note overrides are not supported by KSM.");
    program.invocations.push_back(
        {span, integer(item.at("hold_start_frame"), "hold_start_frame"), index,
         effect.dsp ? parse_parameters(item.at("parameters"), effect) : Parameters{}});
    program.boundaries.insert(span.start);
    program.boundaries.insert(span.end);
  }
  for (const auto &item : data.at("laser_events")) {
    const auto frame = integer(item.at("frame"), "laser event frame");
    const auto index =
        item.at("effect").is_null()
            ? std::nullopt
            : std::make_optional(program.effect_index(item.at("effect").get<std::string>(), true));
    program.laser_events[frame] = index;
    program.boundaries.insert(frame);
  }
  for (const auto &item : data.at("lasers")) {
    const auto span = hold(item);
    Laser laser{span.start, span.end, span.lane, {}};
    for (const auto &point : item.at("points")) {
      Point value{
          integer(point.at("frame"), "laser point frame"), number(point.at("pulse"), "laser pulse"),
          number(point.at("incoming"), "incoming"),        number(point.at("outgoing"), "outgoing"),
          number(point.at("curve_x"), "curve_x"),          number(point.at("curve_y"), "curve_y")};
      if (value.x < 0 || value.x > 1 || value.y < 0 || value.y > 1 || value.incoming < 0 ||
          value.incoming > 1 || value.outgoing < 0 || value.outgoing > 1)
        invalid("Laser graph coordinates must be within zero and one.");
      if (!laser.points.empty() &&
          (value.frame < laser.points.back().frame || value.pulse <= laser.points.back().pulse))
        invalid("Laser points must be ordered.");
      laser.points.push_back(value);
      program.boundaries.insert(value.frame);
      if (value.frame + program.peak_delay >= 0)
        program.boundaries.insert(value.frame + program.peak_delay);
    }
    if (laser.points.empty())
      invalid("Laser sections require points.");
    program.lasers.push_back(std::move(laser));
    program.boundaries.insert(span.start);
    program.boundaries.insert(span.end);
    if (span.start + program.peak_delay >= 0)
      program.boundaries.insert(span.start + program.peak_delay);
    if (span.end + program.peak_delay >= 0)
      program.boundaries.insert(span.end + program.peak_delay);
  }
  Frame last_key = -1;
  for (const auto &item : data.at("keysounds")) {
    const auto frame = integer(item.at("frame"), "keysound frame");
    if (frame < last_key)
      invalid("Keysounds must be ordered.");
    const auto volume = number(item.at("volume"), "keysound volume");
    if (volume < 0)
      invalid("Keysound volume must be nonnegative.");
    program.keysounds.push_back(
        {frame, item.at("resource_id").get<std::string>(), static_cast<float>(volume)});
    program.boundaries.insert(frame);
    last_key = frame;
  }
  return program;
}

void apply_parameters(Effect &effect, Frame frame, const Invocation *invocation) {
  auto parameters = effect.defaults;
  for (auto it = effect.changes.begin(); it != effect.changes.end() && it->first <= frame; ++it)
    for (const auto &[id, value] : it->second)
      parameters[id] = value;
  if (invocation)
    for (const auto &[id, value] : invocation->parameters)
      parameters[id] = value;
  for (const auto &[id, value] : parameters)
    effect.dsp->setParamValueSet(id, value);
}

std::string version_string(DWORD value) {
  return std::to_string(value >> 24) + "." + std::to_string((value >> 16) & 255) + "." +
         std::to_string((value >> 8) & 255) + "." + std::to_string(value & 255);
}
} // namespace

Json render(const Json &request, const std::filesystem::path &destination) {
  if (request.at("protocol_version") != 1 || request.at("sample_rate") != rate)
    invalid("Unsupported render protocol or sample rate.");
  Bass runtime;
  auto program = parse_program(request.at("program"));
  const auto offset = integer(request.at("offset_frames"), "offset_frames", true);
  const auto volume = number(request.at("bgm_volume"), "bgm_volume");
  if (volume < 0)
    invalid("BGM volume must be nonnegative.");
  std::map<std::string, std::filesystem::path> tracks;
  std::map<std::string, std::vector<float>> samples;
  for (const auto &item : request.at("tracks")) {
    const auto id = item.at("id").get<std::string>();
    if (!tracks.emplace(id, path_from_utf8(item.at("path").get<std::string>())).second)
      invalid("Duplicate audio resource identifier.");
  }
  for (const auto &item : request.at("samples")) {
    const auto id = item.at("id").get<std::string>();
    if (samples.contains(id))
      invalid("Duplicate audio resource identifier.");
    samples.emplace(id, decode(path_from_utf8(item.at("path").get<std::string>())));
  }
  if (!tracks.contains("main"))
    invalid("A main audio track is required.");
  for (const auto &effect : program.effects)
    if (!effect.dsp && !tracks.contains(effect.switch_track))
      throw RenderError("audio.missing_resource",
                        "Missing switch_audio source: " + effect.switch_track);

  MusicStream main_stream(tracks.at("main"), volume);
  for (auto &effect : program.effects)
    if (effect.dsp)
      main_stream.attach(effect.dsp.get(), effect.priority);

  Frame duration = std::max(integer(request.at("duration_frames"), "duration_frames"),
                            main_stream.frames - offset);
  for (const auto &event : program.keysounds) {
    if (!samples.contains(event.id))
      throw RenderError("audio.missing_resource", "Missing keysound: " + event.id);
    duration =
        std::max(duration, event.frame + static_cast<Frame>(samples.at(event.id).size() / 2));
  }
  program.boundaries.insert(duration);
  if (offset < 0)
    program.boundaries.insert(-offset);

  // Switched sources keep independent filter and compressor histories while inaudible.
  std::map<std::string, std::vector<Effect>> switched_filters;
  std::map<std::pair<std::string, bool>, std::unique_ptr<MusicStream>> switched_streams;
  for (const auto &effect : program.effects) {
    if (effect.dsp)
      continue;
    const auto key = std::pair(effect.switch_track, effect.laser);
    if (switched_streams.contains(key))
      continue;
    auto &stream = switched_streams[key];
    stream = std::make_unique<MusicStream>(tracks.at(effect.switch_track), volume);
    if (effect.laser)
      continue;
    auto &filters = switched_filters[effect.switch_track];
    for (const auto &definition : request.at("program").at("effects")) {
      if (definition.at("bus") != "laser" || !definition.value("builtin", false) ||
          definition.at("type") == "switch_audio")
        continue;
      auto filter = make_effect(definition);
      filter.changes = program.effects[program.effect_index(filter.name, true)].changes;
      filters.push_back(std::move(filter));
    }
    for (auto &filter : filters)
      stream->attach(filter.dsp.get(), filter.priority);
  }
  struct Voice {
    Frame start;
    float volume;
  };
  std::map<std::string, std::vector<Voice>> voices;
  std::size_t key_cursor = 0;
  std::uint64_t saturated_samples = 0;
  std::array<bool, 2> previous_holds{};
  int last_pressed_lane = 0;
  WaveWriter output(destination, duration);
  std::array<float, block_frames * 2> main_buffer{}, switch_buffer{}, selected_buffer{};
  for (Frame frame = 0; frame < duration;) {
    const auto next_boundary = *program.boundaries.upper_bound(frame);
    const auto count = std::min({block_frames, duration - frame, next_boundary - frame});
    const auto size = static_cast<std::size_t>(count * 2);
    auto main = std::span(main_buffer).first(size);
    auto selected = std::span(selected_buffer).first(size);
    std::unordered_map<std::size_t, const Invocation *> active;
    const Invocation *switch_fx = nullptr;
    std::array<bool, 2> held{};
    for (const auto &value : program.holds)
      held[value.lane] |= value.start <= frame && frame < value.end;
    for (int lane = 0; lane < 2; ++lane)
      if (held[lane] && !previous_holds[lane])
        last_pressed_lane = lane;
    previous_holds = held;
    const bool hold_active = held[0] || held[1];
    for (const auto &invocation : program.invocations) {
      if (frame < invocation.span.start || frame >= invocation.span.end)
        continue;
      auto it = active.find(invocation.effect);
      if (it == active.end() || invocation.span.lane == last_pressed_lane)
        active[invocation.effect] = &invocation;
      if (!program.effects[invocation.effect].dsp &&
          (!switch_fx || invocation.span.lane < switch_fx->span.lane))
        switch_fx = &invocation;
    }
    std::optional<std::size_t> laser_index;
    if (const auto it = program.laser_events.upper_bound(frame); it != program.laser_events.begin())
      laser_index = std::prev(it)->second;
    const bool peak = laser_index && program.effects[*laser_index].type == "peaking_filter";
    const auto laser_frame = frame - (peak ? program.peak_delay : 0);
    bool laser_active = false;
    float laser_v = 0;
    for (const auto &laser : program.lasers) {
      if (laser_frame < laser.start || laser_frame >= laser.end)
        continue;
      const auto value = laser_value(laser, laser_frame, program.pulse_at(laser_frame));
      laser_v = std::max(laser_v, static_cast<float>(laser.lane == 0 ? value : 1 - value));
      laser_active = true;
    }
    const auto &tempo = program.tempo_at(frame);
    const ae::Status status{.v = laser_v,
                            .bpm = static_cast<float>(tempo.bpm),
                            .sec = static_cast<float>(frame) / rate,
                            .playbackSpeed = 1};
    for (std::size_t index = 0; index < program.effects.size(); ++index) {
      auto &effect = program.effects[index];
      if (!effect.dsp)
        continue;
      const auto invocation = active.contains(index) ? active.at(index) : nullptr;
      apply_parameters(effect, frame, invocation);
      effect.dsp->setBypass(effect.laser ? !laser_active : !hold_active);
      if (effect.laser)
        effect.dsp->updateStatusByLaser(status, laser_index == index);
      else {
        auto fx_status = status;
        fx_status.v = 0;
        effect.dsp->updateStatusByFX(
            fx_status, invocation
                           ? std::make_optional(static_cast<std::size_t>(invocation->span.lane))
                           : std::nullopt);
      }
    }
    main_stream.read(frame, offset, main);
    std::copy(main.begin(), main.end(), selected.begin());
    for (auto &[key, stream] : switched_streams) {
      const auto &[id, is_laser] = key;
      auto buffer = std::span(switch_buffer).first(size);
      if (!is_laser) {
        for (auto &filter : switched_filters.at(id)) {
          apply_parameters(filter, frame, nullptr);
          filter.dsp->setBypass(!laser_active);
          filter.dsp->updateStatusByLaser(status, laser_index && program.effects[*laser_index].name ==
                                                                     filter.name);
        }
      }
      stream->read(frame, offset, buffer);
      const bool selected_fx = !is_laser && switch_fx &&
                               program.effects[switch_fx->effect].switch_track == id;
      const bool selected_laser = is_laser && !switch_fx && laser_active && laser_index &&
                                  !program.effects[*laser_index].dsp &&
                                  program.effects[*laser_index].switch_track == id;
      if (selected_fx || selected_laser)
        std::copy(buffer.begin(), buffer.end(), selected.begin());
    }

    while (key_cursor < program.keysounds.size() && program.keysounds[key_cursor].frame <= frame) {
      const auto &event = program.keysounds[key_cursor++];
      auto &pool = voices[event.id];
      const auto sample_frames = static_cast<Frame>(samples.at(event.id).size() / 2);
      std::erase_if(pool, [&](const Voice &voice) { return voice.start + sample_frames <= frame; });
      // All voices have the same playback rate. The oldest voice therefore has
      // the greatest playback position, matching BASS_SAMPLE_OVER_POS.
      if (pool.size() >= program.key_sound_polyphony)
        pool.erase(pool.begin());
      pool.push_back({event.frame, event.volume});
    }
    for (auto it = voices.begin(); it != voices.end();) {
      const auto &source = samples.at(it->first);
      auto &pool = it->second;
      std::erase_if(pool, [&](const Voice &voice) {
        return static_cast<std::size_t>((frame - voice.start) * 2) >= source.size();
      });
      if (pool.empty()) {
        it = voices.erase(it);
        continue;
      }
      for (const auto &voice : pool) {
        const auto start = static_cast<std::size_t>((frame - voice.start) * 2);
        for (std::size_t i = 0; i < size && start + i < source.size(); ++i)
          selected[i] += source[start + i] * voice.volume;
      }
      ++it;
    }
    // Match the signed PCM export range before loudness measurement. Keep the
    // intermediate floating point so quieter samples are not quantized twice.
    for (auto &value : selected) {
      if (!std::isfinite(value))
        throw RenderError("audio.nonfinite", "An effect produced non-finite audio.");
      if (value < -1.0f || value > 1.0f) {
        ++saturated_samples;
        value = std::clamp(value, -1.0f, 1.0f);
      }
    }
    output.append(selected);
    frame += count;
  }
  output.close();
  return {{"protocol_version", 1},
          {"frames", duration},
          {"sample_rate", rate},
          {"channels", 2},
          {"bass_version", version_string(BASS_GetVersion())},
          {"bass_fx_version", version_string(BASS_FX_GetVersion())},
          {"processing_profile", "ksm-compressed-v1"},
          {"saturated_samples", saturated_samples},
          {"effects", program.effects.size()},
          {"keysounds", program.keysounds.size()}};
}
} // namespace ksm2sdvx
