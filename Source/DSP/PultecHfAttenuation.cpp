#include "PultecHfAttenuation.h"

#include <cmath>

namespace ProgramEQ::DSP
{

void PultecHfAttenuationBiquadChannel::reset() noexcept
{
    z1 = 0.0f;
    z2 = 0.0f;
}

void PultecHfAttenuationBiquadChannel::setCoefficients(const PultecHfAttenuationBiquadCoefficients& newCoefficients) noexcept
{
    coefficients = newCoefficients;
}

float PultecHfAttenuationBiquadChannel::processSample(float inputSample) noexcept
{
    const auto outputSample = (coefficients.b0 * inputSample) + z1;
    z1 = (coefficients.b1 * inputSample) - (coefficients.a1 * outputSample) + z2;
    z2 = (coefficients.b2 * inputSample) - (coefficients.a2 * outputSample);
    return outputSample;
}

void PultecHfAttenuation::prepare(double sampleRate, int maximumBlockSize, int numChannels)
{
    juce::ignoreUnused(maximumBlockSize, numChannels);

    currentSampleRate = sampleRate;
    currentFrequencyHz = selectionToFrequencyHz(currentFrequencySelection);
    attenuationDecibelSmoother.prepare(sampleRate, smoothingTimeSeconds, clampAttenuationDecibels(currentAttenuationDecibels));
    lastConfiguredAttenuationDecibels = -1.0f;
    lastAppliedAttenuationDecibels = -1.0f;
    reset();
    updateConfiguration();
    applyCoefficients(attenuationDecibelSmoother.getCurrentValue());
}

void PultecHfAttenuation::reset() noexcept
{
    for (auto& channel : channels)
        channel.reset();

    attenuationDecibelSmoother.reset(clampAttenuationDecibels(currentAttenuationDecibels));
}

void PultecHfAttenuation::setEqInEnabled(bool shouldApply) noexcept
{
    eqInEnabled = shouldApply;
}

void PultecHfAttenuation::setFrequencySelection(int selectionIndex) noexcept
{
    currentFrequencySelection = selectionIndex;
}

void PultecHfAttenuation::setAttenuationDecibels(float attenuationDb) noexcept
{
    currentAttenuationDecibels = attenuationDb;
}

void PultecHfAttenuation::process(juce::AudioBuffer<float>& buffer) noexcept
{
    updateConfiguration();

    if (! attenuationDecibelSmoother.isSmoothing() && attenuationDecibelSmoother.getCurrentValue() <= 0.0f)
        return;

    const auto numChannels = juce::jmin(buffer.getNumChannels(), maxChannels);
    const auto numSamples = buffer.getNumSamples();

    for (int sampleIndex = 0; sampleIndex < numSamples; ++sampleIndex)
    {
        const auto attenuationDb = attenuationDecibelSmoother.getNextValue();
        if (attenuationDb != lastAppliedAttenuationDecibels)
            applyCoefficients(attenuationDb);

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

float PultecHfAttenuation::selectionToFrequencyHz(int selectionIndex) noexcept
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

void PultecHfAttenuation::updateConfiguration() noexcept
{
    const auto newFrequencyHz = selectionToFrequencyHz(currentFrequencySelection);
    if (newFrequencyHz != currentFrequencyHz)
    {
        currentFrequencyHz = newFrequencyHz;
        lastAppliedAttenuationDecibels = -1.0f;
    }

    const auto clampedAttenuationDb = clampAttenuationDecibels(currentAttenuationDecibels);
    if (clampedAttenuationDb != lastConfiguredAttenuationDecibels)
    {
        attenuationDecibelSmoother.setTargetValue(clampedAttenuationDb);
        lastConfiguredAttenuationDecibels = clampedAttenuationDb;
    }
}

void PultecHfAttenuation::applyCoefficients(float attenuationDb) noexcept
{
    const auto coefficients = makeHighShelfCoefficients(currentSampleRate, currentFrequencyHz, attenuationDb, shelfSlope);
    for (auto& channel : channels)
        channel.setCoefficients(coefficients);

    lastAppliedAttenuationDecibels = attenuationDb;
}

float PultecHfAttenuation::clampAttenuationDecibels(float attenuationDb) noexcept
{
    return juce::jlimit(0.0f, 16.0f, attenuationDb);
}

PultecHfAttenuationBiquadCoefficients PultecHfAttenuation::makeHighShelfCoefficients(double sampleRate, float frequencyHz, float attenuationDb, float slope) noexcept
{
    if (attenuationDb <= 0.0f)
        return {};

    const auto gainDb = -attenuationDb;
    const auto safeFrequencyHz = juce::jlimit(20.0f, static_cast<float>(0.45 * sampleRate), frequencyHz);
    const auto w0 = juce::MathConstants<float>::twoPi * safeFrequencyHz / static_cast<float>(sampleRate);
    const auto cosW0 = std::cos(w0);
    const auto sinW0 = std::sin(w0);
    const auto a = std::pow(10.0f, gainDb / 40.0f);
    const auto alpha = (sinW0 * 0.5f) * std::sqrt((a + (1.0f / a)) * ((1.0f / slope) - 1.0f) + 2.0f);
    const auto beta = 2.0f * std::sqrt(a) * alpha;

    const auto b0 = a * ((a + 1.0f) + ((a - 1.0f) * cosW0) + beta);
    const auto b1 = -2.0f * a * ((a - 1.0f) + ((a + 1.0f) * cosW0));
    const auto b2 = a * ((a + 1.0f) + ((a - 1.0f) * cosW0) - beta);
    const auto a0 = (a + 1.0f) - ((a - 1.0f) * cosW0) + beta;
    const auto a1 = 2.0f * ((a - 1.0f) - ((a + 1.0f) * cosW0));
    const auto a2 = (a + 1.0f) - ((a - 1.0f) * cosW0) - beta;

    return {
        b0 / a0,
        b1 / a0,
        b2 / a0,
        a1 / a0,
        a2 / a0,
    };
}

} // namespace ProgramEQ::DSP
