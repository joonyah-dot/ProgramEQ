#include "PultecLfBoost.h"

#include <cmath>

namespace ProgramEQ::DSP
{
namespace
{
float computeResistanceForFrequency(float frequencyHz)
{
    constexpr auto twoPi = 6.28318530717958647692f;
    return 1.0f / (twoPi * frequencyHz * PultecLfBoostLowpassChannel::capacitorValueFarads);
}
} // namespace

#if PROGRAM_EQ_USE_CHOWDSP_WDF
void PultecLfBoostLowpassChannel::prepare(double sampleRate) noexcept
{
    capacitor.prepare(static_cast<float>(sampleRate));
    reset();
}

void PultecLfBoostLowpassChannel::reset() noexcept
{
    capacitor.reset();
}

void PultecLfBoostLowpassChannel::setFrequency(float frequencyHz) noexcept
{
    resistor.setResistanceValue(computeResistanceForFrequency(frequencyHz));
}

float PultecLfBoostLowpassChannel::processSample(float inputSample) noexcept
{
    source.setVoltage(inputSample);
    source.incident(inverter.reflected());
    inverter.incident(source.reflected());
    return capacitor.voltage();
}
#else
void PultecLfBoostLowpassChannel::prepare(double sampleRate) noexcept
{
    juce::dsp::ProcessSpec spec {};
    spec.sampleRate = sampleRate;
    spec.maximumBlockSize = 1;
    spec.numChannels = 1;
    filter.prepare(spec);
    reset();
}

void PultecLfBoostLowpassChannel::reset() noexcept
{
    filter.reset();
}

void PultecLfBoostLowpassChannel::setFrequency(float frequencyHz) noexcept
{
    filter.setCutoffFrequency(frequencyHz);
}

float PultecLfBoostLowpassChannel::processSample(float inputSample) noexcept
{
    return filter.processSample(inputSample);
}
#endif

void PultecLfBoost::prepare(double sampleRate, int maximumBlockSize, int numChannels)
{
    juce::ignoreUnused(maximumBlockSize, numChannels);

    currentSampleRate = sampleRate;
    boostGainSmoother.prepare(sampleRate, smoothingTimeSeconds, computeBoostGain(currentBoostDecibels));
    attenuationGainSmoother.prepare(sampleRate, smoothingTimeSeconds, computeAttenuationGain(currentAttenuationDecibels));

    for (auto& channel : boostChannels)
        channel.prepare(sampleRate);

    for (auto& channel : attenuationChannels)
        channel.prepare(sampleRate);

    for (auto& channel : interactionChannels)
        channel.prepare(sampleRate);

    lastConfiguredFrequencyHz = -1.0f;
    lastConfiguredBoostGain = -1.0f;
    lastConfiguredAttenuationGain = -1.0f;
    updateConfiguration();
}

void PultecLfBoost::reset() noexcept
{
    for (auto& channel : boostChannels)
        channel.reset();

    for (auto& channel : attenuationChannels)
        channel.reset();

    for (auto& channel : interactionChannels)
        channel.reset();

    boostGainSmoother.reset(computeBoostGain(currentBoostDecibels));
    attenuationGainSmoother.reset(computeAttenuationGain(currentAttenuationDecibels));
}

void PultecLfBoost::setEqInEnabled(bool shouldApply) noexcept
{
    eqInEnabled = shouldApply;
}

void PultecLfBoost::setFrequencySelection(int selectionIndex) noexcept
{
    currentFrequencySelection = selectionIndex;
}

void PultecLfBoost::setBoostDecibels(float boostDb) noexcept
{
    currentBoostDecibels = boostDb;
}

void PultecLfBoost::setAttenuationDecibels(float attenuationDb) noexcept
{
    currentAttenuationDecibels = attenuationDb;
}

void PultecLfBoost::process(juce::AudioBuffer<float>& buffer) noexcept
{
    updateConfiguration();

    const auto numChannels = juce::jmin(buffer.getNumChannels(), maxChannels);
    const auto numSamples = buffer.getNumSamples();

    for (int sampleIndex = 0; sampleIndex < numSamples; ++sampleIndex)
    {
        const auto boostGain = boostGainSmoother.getNextValue();
        const auto attenuationGain = attenuationGainSmoother.getNextValue();

        for (int channelIndex = 0; channelIndex < numChannels; ++channelIndex)
        {
            auto* channelData = buffer.getWritePointer(channelIndex);
            const auto inputSample = channelData[sampleIndex];
            const auto boostBandSample = boostChannels[static_cast<size_t>(channelIndex)].processSample(inputSample);
            const auto boostedSample = inputSample + (boostGain * boostBandSample);
            const auto attenuationBandSample = attenuationChannels[static_cast<size_t>(channelIndex)].processSample(boostedSample);
            auto outputSample = boostedSample - (attenuationGain * attenuationBandSample);

            if (boostGain > 0.0f && attenuationGain > 0.0f)
            {
                const auto interactionBandSample = interactionChannels[static_cast<size_t>(channelIndex)].processSample(inputSample) - boostBandSample;
                outputSample -= computeInteractionGain(boostGain, attenuationGain) * interactionBandSample;
            }

            if (eqInEnabled)
                channelData[sampleIndex] = outputSample;
        }
    }
}

float PultecLfBoost::selectionToFrequencyHz(int selectionIndex) noexcept
{
    switch (juce::jlimit(0, 3, selectionIndex))
    {
        case 0: return 20.0f;
        case 1: return 30.0f;
        case 2: return 60.0f;
        case 3: return 100.0f;
        default: break;
    }

    return 20.0f;
}

void PultecLfBoost::updateConfiguration() noexcept
{
    const auto frequencyHz = selectionToFrequencyHz(currentFrequencySelection);
    if (frequencyHz != lastConfiguredFrequencyHz)
    {
        for (auto& channel : boostChannels)
            channel.setFrequency(frequencyHz);

        for (auto& channel : attenuationChannels)
            channel.setFrequency(frequencyHz);

        for (auto& channel : interactionChannels)
            channel.setFrequency(computeInteractionFrequencyHz(frequencyHz));

        lastConfiguredFrequencyHz = frequencyHz;
    }

    const auto targetBoostGain = computeBoostGain(currentBoostDecibels);
    if (targetBoostGain != lastConfiguredBoostGain)
    {
        boostGainSmoother.setTargetValue(targetBoostGain);
        lastConfiguredBoostGain = targetBoostGain;
    }

    const auto targetAttenuationGain = computeAttenuationGain(currentAttenuationDecibels);
    if (targetAttenuationGain != lastConfiguredAttenuationGain)
    {
        attenuationGainSmoother.setTargetValue(targetAttenuationGain);
        lastConfiguredAttenuationGain = targetAttenuationGain;
    }
}

float PultecLfBoost::computeBoostGain(float boostDb) noexcept
{
    const auto lowFrequencyLinear = juce::Decibels::decibelsToGain(juce::jlimit(0.0f, 13.5f, boostDb));
    return lowFrequencyLinear - 1.0f;
}

float PultecLfBoost::computeAttenuationGain(float attenuationDb) noexcept
{
    const auto lowFrequencyLinear = juce::Decibels::decibelsToGain(-juce::jlimit(0.0f, 17.5f, attenuationDb));
    return 1.0f - lowFrequencyLinear;
}

float PultecLfBoost::computeInteractionFrequencyHz(float frequencyHz) noexcept
{
    return juce::jlimit(20.0f, 200.0f, frequencyHz * 2.0f);
}

float PultecLfBoost::computeInteractionGain(float boostGain, float attenuationGain) noexcept
{
    return 0.2f * boostGain * attenuationGain;
}

} // namespace ProgramEQ::DSP
