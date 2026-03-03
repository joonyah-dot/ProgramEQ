#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include <vector>

namespace ProgramEQ::Parameters
{

using APVTS = juce::AudioProcessorValueTreeState;

inline constexpr auto stateTreeType = "ProgramEQState";

namespace IDs
{
inline constexpr auto globalTrueBypass = "global.true_bypass";
inline constexpr auto globalOutputTrimDb = "global.output_trim_db";
inline constexpr auto globalOversamplingMode = "global.oversampling_mode";
inline constexpr auto globalUiAnalyzerEnabled = "global.ui_analyzer_enabled";

inline constexpr auto pultecEqIn = "pultec.eq_in";
inline constexpr auto pultecLfFreqHz = "pultec.lf_freq_hz";
inline constexpr auto pultecLfBoostDb = "pultec.lf_boost_db";
inline constexpr auto pultecLfAttenDb = "pultec.lf_atten_db";
inline constexpr auto pultecHfBoostFreqKhz = "pultec.hf_boost_freq_khz";
inline constexpr auto pultecHfBoostDb = "pultec.hf_boost_db";
inline constexpr auto pultecHfBandwidth = "pultec.hf_bandwidth";
inline constexpr auto pultecHfAttenSelKhz = "pultec.hf_atten_sel_khz";
inline constexpr auto pultecHfAttenDb = "pultec.hf_atten_db";
inline constexpr auto pultecAnalogEnabled = "pultec.analog_enabled";
inline constexpr auto pultecDrive = "pultec.drive";

inline constexpr auto hpf100Enabled = "hpf100.enabled";

inline constexpr auto peq1Enabled = "peq1.enabled";
inline constexpr auto peq1FreqHz = "peq1.freq_hz";
inline constexpr auto peq1GainDb = "peq1.gain_db";
inline constexpr auto peq1Q = "peq1.q";

inline constexpr auto peq2Enabled = "peq2.enabled";
inline constexpr auto peq2FreqHz = "peq2.freq_hz";
inline constexpr auto peq2GainDb = "peq2.gain_db";
inline constexpr auto peq2Q = "peq2.q";
} // namespace IDs

enum class ParameterKind
{
    boolean,
    choice,
    floating
};

struct ParameterDefinition
{
    juce::String id;
    juce::String name;
    juce::String label;
    ParameterKind kind = ParameterKind::floating;
    juce::NormalisableRange<float> range { 0.0f, 1.0f };
    float defaultValue = 0.0f;
    juce::StringArray choices;
};

const std::vector<ParameterDefinition>& getParameterDefinitions();
APVTS::ParameterLayout createParameterLayout();
const ParameterDefinition* findDefinition(juce::StringRef parameterID);

} // namespace ProgramEQ::Parameters
