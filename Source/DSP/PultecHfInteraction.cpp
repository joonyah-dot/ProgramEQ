#include "PultecHfInteraction.h"

#include <cmath>

namespace ProgramEQ::DSP
{

void PultecHfInteractionBiquadChannel::reset() noexcept
{
    z1 = 0.0f;
    z2 = 0.0f;
}

void PultecHfInteractionBiquadChannel::setCoefficients(const PultecHfInteractionBiquadCoefficients& newCoefficients) noexcept
{
    coefficients = newCoefficients;
}

float PultecHfInteractionBiquadChannel::processSample(float inputSample) noexcept
{
    const auto outputSample = (coefficients.b0 * inputSample) + z1;
    z1 = (coefficients.b1 * inputSample) - (coefficients.a1 * outputSample) + z2;
    z2 = (coefficients.b2 * inputSample) - (coefficients.a2 * outputSample);
    return outputSample;
}

void PultecHfInteraction::prepare(double sampleRate, int maximumBlockSize, int numChannels)
{
    juce::ignoreUnused(maximumBlockSize, numChannels);

    currentSampleRate = sampleRate;
    currentFrequencyHz = selectionToBoostFrequencyHz(currentBoostFrequencySelection);
    const auto initialInteractionBoostDb = computeInteractionBoostDb(
        currentBoostDecibels,
        currentAttenuationDecibels,
        currentFrequencyHz,
        selectionToAttenuationFrequencyHz(currentAttenuationSelection)
    );
    interactionBoostDecibelSmoother.prepare(sampleRate, smoothingTimeSeconds, initialInteractionBoostDb);
    lastConfiguredInteractionBoostDb = -1.0f;
    lastAppliedInteractionBoostDb = -1.0f;
    reset();
    updateConfiguration();
    applyCoefficients(interactionBoostDecibelSmoother.getCurrentValue());
}

void PultecHfInteraction::reset() noexcept
{
    for (auto& channel : channels)
        channel.reset();

    interactionBoostDecibelSmoother.reset(computeInteractionBoostDb(
        currentBoostDecibels,
        currentAttenuationDecibels,
        selectionToBoostFrequencyHz(currentBoostFrequencySelection),
        selectionToAttenuationFrequencyHz(currentAttenuationSelection)
    ));
}

void PultecHfInteraction::setEqInEnabled(bool shouldApply) noexcept
{
    eqInEnabled = shouldApply;
}

void PultecHfInteraction::setBoostFrequencySelection(int selectionIndex) noexcept
{
    currentBoostFrequencySelection = selectionIndex;
}

void PultecHfInteraction::setAttenuationSelection(int selectionIndex) noexcept
{
    currentAttenuationSelection = selectionIndex;
}

void PultecHfInteraction::setBoostDecibels(float boostDb) noexcept
{
    currentBoostDecibels = boostDb;
}

void PultecHfInteraction::setAttenuationDecibels(float attenuationDb) noexcept
{
    currentAttenuationDecibels = attenuationDb;
}

void PultecHfInteraction::process(juce::AudioBuffer<float>& buffer) noexcept
{
    updateConfiguration();

    if (! interactionBoostDecibelSmoother.isSmoothing() && interactionBoostDecibelSmoother.getCurrentValue() <= 0.0f)
        return;

    const auto numChannels = juce::jmin(buffer.getNumChannels(), maxChannels);
    const auto numSamples = buffer.getNumSamples();

    for (int sampleIndex = 0; sampleIndex < numSamples; ++sampleIndex)
    {
        const auto interactionBoostDb = interactionBoostDecibelSmoother.getNextValue();
        if (interactionBoostDb != lastAppliedInteractionBoostDb)
            applyCoefficients(interactionBoostDb);

        for (int channelIndex = 0; channelIndex < numChannels; ++channelIndex)
        {
            auto* channelData = buffer.getWritePointer(channelIndex);
            const auto inputSample = channelData[sampleIndex];
            const auto outputSample = channels[static_cast<size_t>(channelIndex)].processSample(inputSample);

            if (eqInEnabled)
                channelData[sampleIndex] = outputSample;
        }
    }
}

void PultecHfInteraction::updateConfiguration() noexcept
{
    const auto boostFrequencyHz = selectionToBoostFrequencyHz(currentBoostFrequencySelection);
    if (boostFrequencyHz != currentFrequencyHz)
    {
        currentFrequencyHz = boostFrequencyHz;
        lastAppliedInteractionBoostDb = -1.0f;
    }

    const auto interactionBoostDb = computeInteractionBoostDb(
        currentBoostDecibels,
        currentAttenuationDecibels,
        boostFrequencyHz,
        selectionToAttenuationFrequencyHz(currentAttenuationSelection)
    );
    if (interactionBoostDb != lastConfiguredInteractionBoostDb)
    {
        interactionBoostDecibelSmoother.setTargetValue(interactionBoostDb);
        lastConfiguredInteractionBoostDb = interactionBoostDb;
    }
}

void PultecHfInteraction::applyCoefficients(float interactionBoostDb) noexcept
{
    const auto coefficients = makePeakCoefficients(currentSampleRate, currentFrequencyHz, interactionBoostDb, interactionQ);
    for (auto& channel : channels)
        channel.setCoefficients(coefficients);

    lastAppliedInteractionBoostDb = interactionBoostDb;
}

float PultecHfInteraction::computeInteractionBoostDb(float boostDb, float attenuationDb, float boostFrequencyHz, float attenuationFrequencyHz) noexcept
{
    if (boostDb <= 0.0f || attenuationDb <= 0.0f || boostFrequencyHz <= 0.0f || attenuationFrequencyHz <= 0.0f)
        return 0.0f;

    const auto boostNormalised = juce::jlimit(0.0f, 1.0f, boostDb / 18.0f);
    const auto attenuationNormalised = juce::jlimit(0.0f, 1.0f, attenuationDb / 16.0f);
    const auto selectorOffset = juce::jlimit(-1.0f, 1.0f, std::log2(boostFrequencyHz / attenuationFrequencyHz));
    const auto selectorWeight = 1.0f + (0.25f * selectorOffset);
    return clampInteractionBoostDb(2.0f * boostNormalised * attenuationNormalised * selectorWeight);
}

float PultecHfInteraction::clampInteractionBoostDb(float interactionBoostDb) noexcept
{
    return juce::jlimit(0.0f, 3.0f, interactionBoostDb);
}

float PultecHfInteraction::selectionToBoostFrequencyHz(int selectionIndex) noexcept
{
    switch (juce::jlimit(0, 6, selectionIndex))
    {
        case 0: return 3000.0f;
        case 1: return 4000.0f;
        case 2: return 5000.0f;
        case 3: return 8000.0f;
        case 4: return 10000.0f;
        case 5: return 12000.0f;
        case 6: return 16000.0f;
        default: break;
    }

    return 3000.0f;
}

float PultecHfInteraction::selectionToAttenuationFrequencyHz(int selectionIndex) noexcept
{
    switch (juce::jlimit(0, 2, selectionIndex))
    {
        case 0: return 5000.0f;
        case 1: return 10000.0f;
        case 2: return 20000.0f;
        default: break;
    }

    return 5000.0f;
}

PultecHfInteractionBiquadCoefficients PultecHfInteraction::makePeakCoefficients(double sampleRate, float frequencyHz, float boostDb, float q) noexcept
{
    if (boostDb <= 0.0f)
        return {};

    const auto safeFrequencyHz = juce::jlimit(20.0f, static_cast<float>(0.45 * sampleRate), frequencyHz);
    const auto w0 = juce::MathConstants<float>::twoPi * safeFrequencyHz / static_cast<float>(sampleRate);
    const auto cosW0 = std::cos(w0);
    const auto sinW0 = std::sin(w0);
    const auto a = std::pow(10.0f, boostDb / 40.0f);
    const auto alpha = sinW0 / (2.0f * q);

    const auto b0 = 1.0f + (alpha * a);
    const auto b1 = -2.0f * cosW0;
    const auto b2 = 1.0f - (alpha * a);
    const auto a0 = 1.0f + (alpha / a);
    const auto a1 = -2.0f * cosW0;
    const auto a2 = 1.0f - (alpha / a);

    return {
        b0 / a0,
        b1 / a0,
        b2 / a0,
        a1 / a0,
        a2 / a0,
    };
}

} // namespace ProgramEQ::DSP
