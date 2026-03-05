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
    branchGainSmoother.prepare(sampleRate, smoothingTimeSeconds, computeBranchGain(currentBoostDecibels));

    for (auto& channel : channels)
        channel.prepare(sampleRate);

    lastConfiguredFrequencyHz = -1.0f;
    lastConfiguredBranchGain = -1.0f;
    updateConfiguration();
}

void PultecLfBoost::reset() noexcept
{
    for (auto& channel : channels)
        channel.reset();

    branchGainSmoother.reset(computeBranchGain(currentBoostDecibels));
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

void PultecLfBoost::process(juce::AudioBuffer<float>& buffer) noexcept
{
    updateConfiguration();

    const auto numChannels = juce::jmin(buffer.getNumChannels(), maxChannels);
    const auto numSamples = buffer.getNumSamples();

    for (int sampleIndex = 0; sampleIndex < numSamples; ++sampleIndex)
    {
        const auto mixGain = branchGainSmoother.getNextValue();

        for (int channelIndex = 0; channelIndex < numChannels; ++channelIndex)
        {
            auto* channelData = buffer.getWritePointer(channelIndex);
            const auto inputSample = channelData[sampleIndex];
            const auto lowBandSample = channels[static_cast<size_t>(channelIndex)].processSample(inputSample);

            if (eqInEnabled)
                channelData[sampleIndex] = inputSample + (mixGain * lowBandSample);
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
        for (auto& channel : channels)
            channel.setFrequency(frequencyHz);

        lastConfiguredFrequencyHz = frequencyHz;
    }

    const auto targetBranchGain = computeBranchGain(currentBoostDecibels);
    if (targetBranchGain != lastConfiguredBranchGain)
    {
        branchGainSmoother.setTargetValue(targetBranchGain);
        lastConfiguredBranchGain = targetBranchGain;
    }
}

float PultecLfBoost::computeBranchGain(float boostDb) noexcept
{
    const auto lowFrequencyLinear = juce::Decibels::decibelsToGain(juce::jlimit(0.0f, 13.5f, boostDb));
    return lowFrequencyLinear - 1.0f;
}

} // namespace ProgramEQ::DSP
