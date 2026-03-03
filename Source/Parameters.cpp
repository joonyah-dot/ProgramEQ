#include "Parameters.h"

#include <algorithm>

namespace ProgramEQ::Parameters
{
namespace
{
juce::NormalisableRange<float> makeFrequencyRange()
{
    auto range = juce::NormalisableRange<float> { 20.0f, 20000.0f };
    range.setSkewForCentre(1000.0f);
    return range;
}

juce::NormalisableRange<float> makeQRange()
{
    auto range = juce::NormalisableRange<float> { 0.2f, 10.0f };
    range.setSkewForCentre(1.0f);
    return range;
}

std::unique_ptr<juce::RangedAudioParameter> createParameter(const ParameterDefinition& definition)
{
    const auto parameterID = juce::ParameterID { definition.id, 1 };

    switch (definition.kind)
    {
        case ParameterKind::boolean:
            return std::make_unique<juce::AudioParameterBool>(
                parameterID,
                definition.name,
                definition.defaultValue >= 0.5f,
                juce::AudioParameterBoolAttributes().withLabel(definition.label));

        case ParameterKind::choice:
            return std::make_unique<juce::AudioParameterChoice>(
                parameterID,
                definition.name,
                definition.choices,
                juce::roundToInt(definition.defaultValue),
                juce::AudioParameterChoiceAttributes().withLabel(definition.label));

        case ParameterKind::floating:
            return std::make_unique<juce::AudioParameterFloat>(
                parameterID,
                definition.name,
                definition.range,
                definition.defaultValue,
                juce::AudioParameterFloatAttributes().withLabel(definition.label));
    }

    jassertfalse;
    return {};
}
} // namespace

const std::vector<ParameterDefinition>& getParameterDefinitions()
{
    static const auto definitions = std::vector<ParameterDefinition>
    {
        { IDs::globalTrueBypass, "True Bypass", {}, ParameterKind::boolean, { 0.0f, 1.0f, 1.0f }, 0.0f, {} },
        { IDs::globalOutputTrimDb, "Output Trim", "dB", ParameterKind::floating, { -24.0f, 24.0f }, 0.0f, {} },
        { IDs::globalOversamplingMode, "Oversampling", {}, ParameterKind::choice, { 0.0f, 2.0f, 1.0f }, 0.0f, { "Off", "2x", "4x" } },
        { IDs::globalUiAnalyzerEnabled, "Analyzer Enabled", {}, ParameterKind::boolean, { 0.0f, 1.0f, 1.0f }, 0.0f, {} },

        { IDs::pultecEqIn, "EQ In", {}, ParameterKind::boolean, { 0.0f, 1.0f, 1.0f }, 1.0f, {} },
        { IDs::pultecLfFreqHz, "LF Frequency", "Hz", ParameterKind::choice, { 0.0f, 3.0f, 1.0f }, 0.0f, { "20", "30", "60", "100" } },
        { IDs::pultecLfBoostDb, "LF Boost", "dB", ParameterKind::floating, { 0.0f, 13.5f }, 0.0f, {} },
        { IDs::pultecLfAttenDb, "LF Atten", "dB", ParameterKind::floating, { 0.0f, 17.5f }, 0.0f, {} },
        { IDs::pultecHfBoostFreqKhz, "HF Boost Frequency", "kHz", ParameterKind::choice, { 0.0f, 6.0f, 1.0f }, 0.0f, { "3", "4", "5", "8", "10", "12", "16" } },
        { IDs::pultecHfBoostDb, "HF Boost", "dB", ParameterKind::floating, { 0.0f, 18.0f }, 0.0f, {} },
        { IDs::pultecHfBandwidth, "HF Bandwidth", {}, ParameterKind::floating, { 0.0f, 1.0f }, 0.5f, {} },
        { IDs::pultecHfAttenSelKhz, "HF Atten Select", "kHz", ParameterKind::choice, { 0.0f, 2.0f, 1.0f }, 0.0f, { "5", "10", "20" } },
        { IDs::pultecHfAttenDb, "HF Atten", "dB", ParameterKind::floating, { 0.0f, 16.0f }, 0.0f, {} },
        { IDs::pultecAnalogEnabled, "Analog Enabled", {}, ParameterKind::boolean, { 0.0f, 1.0f, 1.0f }, 0.0f, {} },
        { IDs::pultecDrive, "Drive", {}, ParameterKind::floating, { 0.0f, 1.0f }, 0.0f, {} },

        { IDs::hpf100Enabled, "100 Hz HPF", {}, ParameterKind::boolean, { 0.0f, 1.0f, 1.0f }, 0.0f, {} },

        { IDs::peq1Enabled, "PEQ 1 Enabled", {}, ParameterKind::boolean, { 0.0f, 1.0f, 1.0f }, 0.0f, {} },
        { IDs::peq1FreqHz, "PEQ 1 Frequency", "Hz", ParameterKind::floating, makeFrequencyRange(), 1000.0f, {} },
        { IDs::peq1GainDb, "PEQ 1 Gain", "dB", ParameterKind::floating, { -18.0f, 18.0f }, 0.0f, {} },
        { IDs::peq1Q, "PEQ 1 Q", {}, ParameterKind::floating, makeQRange(), 1.0f, {} },

        { IDs::peq2Enabled, "PEQ 2 Enabled", {}, ParameterKind::boolean, { 0.0f, 1.0f, 1.0f }, 0.0f, {} },
        { IDs::peq2FreqHz, "PEQ 2 Frequency", "Hz", ParameterKind::floating, makeFrequencyRange(), 1000.0f, {} },
        { IDs::peq2GainDb, "PEQ 2 Gain", "dB", ParameterKind::floating, { -18.0f, 18.0f }, 0.0f, {} },
        { IDs::peq2Q, "PEQ 2 Q", {}, ParameterKind::floating, makeQRange(), 1.0f, {} }
    };

    return definitions;
}

APVTS::ParameterLayout createParameterLayout()
{
    APVTS::ParameterLayout layout;

    for (const auto& definition : getParameterDefinitions())
        layout.add(createParameter(definition));

    return layout;
}

const ParameterDefinition* findDefinition(juce::StringRef parameterID)
{
    const auto& definitions = getParameterDefinitions();

    const auto it = std::find_if(definitions.begin(),
                                 definitions.end(),
                                 [parameterID](const auto& definition)
                                 {
                                     return definition.id == parameterID;
                                 });

    return it != definitions.end() ? &(*it) : nullptr;
}

} // namespace ProgramEQ::Parameters
