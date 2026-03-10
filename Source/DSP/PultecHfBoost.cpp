#include "PultecHfBoost.h"

#include <cmath>

namespace ProgramEQ::DSP
{
namespace
{
float interpolateLogarithmic(float startValue, float endValue, float t) noexcept
{
    const auto clampedT = juce::jlimit(0.0f, 1.0f, t);
    return std::exp(std::log(startValue) + (std::log(endValue) - std::log(startValue)) * clampedT);
}
} // namespace

void PultecHfBoostBiquadChannel::reset() noexcept
{
    z1 = 0.0f;
    z2 = 0.0f;
}

void PultecHfBoostBiquadChannel::setCoefficients(const PultecHfBoostBiquadCoefficients& newCoefficients) noexcept
{
    coefficients = newCoefficients;
}

float PultecHfBoostBiquadChannel::processSample(float inputSample) noexcept
{
    const auto outputSample = (coefficients.b0 * inputSample) + z1;
    z1 = (coefficients.b1 * inputSample) - (coefficients.a1 * outputSample) + z2;
    z2 = (coefficients.b2 * inputSample) - (coefficients.a2 * outputSample);
    return outputSample;
}

void PultecHfBoost::prepare(double sampleRate, int maximumBlockSize, int numChannels)
{
    juce::ignoreUnused(maximumBlockSize, numChannels);

    currentSampleRate = sampleRate;
    currentFrequencyHz = selectionToFrequencyHz(currentFrequencySelection);
    boostDecibelSmoother.prepare(sampleRate, smoothingTimeSeconds, clampBoostDecibels(currentBoostDecibels));
    bandwidthNormalizedSmoother.prepare(sampleRate, smoothingTimeSeconds, clampBandwidthNormalized(currentBandwidthNormalized));
    lastConfiguredBoostDecibels = -1.0f;
    lastConfiguredBandwidthNormalized = -1.0f;
    lastAppliedBoostDecibels = -1.0f;
    lastAppliedBandwidthQ = -1.0f;
    reset();
    updateConfiguration();
    applyCoefficients(
        boostDecibelSmoother.getCurrentValue(),
        bandwidthNormalizedToQ(bandwidthNormalizedSmoother.getCurrentValue())
    );
}

void PultecHfBoost::reset() noexcept
{
    for (auto& channel : channels)
        channel.reset();

    boostDecibelSmoother.reset(clampBoostDecibels(currentBoostDecibels));
    bandwidthNormalizedSmoother.reset(clampBandwidthNormalized(currentBandwidthNormalized));
}

void PultecHfBoost::setEqInEnabled(bool shouldApply) noexcept
{
    eqInEnabled = shouldApply;
}

void PultecHfBoost::setFrequencySelection(int selectionIndex) noexcept
{
    currentFrequencySelection = selectionIndex;
}

void PultecHfBoost::setBoostDecibels(float boostDb) noexcept
{
    currentBoostDecibels = boostDb;
}

void PultecHfBoost::setBandwidthNormalized(float bandwidthNormalized) noexcept
{
    currentBandwidthNormalized = bandwidthNormalized;
}

void PultecHfBoost::process(juce::AudioBuffer<float>& buffer) noexcept
{
    updateConfiguration();

    if (! boostDecibelSmoother.isSmoothing() && boostDecibelSmoother.getCurrentValue() <= 0.0f)
        return;

    const auto numChannels = juce::jmin(buffer.getNumChannels(), maxChannels);
    const auto numSamples = buffer.getNumSamples();

    for (int sampleIndex = 0; sampleIndex < numSamples; ++sampleIndex)
    {
        const auto boostDb = boostDecibelSmoother.getNextValue();
        const auto bandwidthQ = bandwidthNormalizedToQ(bandwidthNormalizedSmoother.getNextValue());
        if (boostDb != lastAppliedBoostDecibels || bandwidthQ != lastAppliedBandwidthQ)
            applyCoefficients(boostDb, bandwidthQ);

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

float PultecHfBoost::selectionToFrequencyHz(int selectionIndex) noexcept
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

void PultecHfBoost::updateConfiguration() noexcept
{
    const auto newFrequencyHz = selectionToFrequencyHz(currentFrequencySelection);
    if (newFrequencyHz != currentFrequencyHz)
    {
        currentFrequencyHz = newFrequencyHz;
        lastAppliedBoostDecibels = -1.0f;
        lastAppliedBandwidthQ = -1.0f;
    }

    const auto clampedBoostDb = clampBoostDecibels(currentBoostDecibels);
    if (clampedBoostDb != lastConfiguredBoostDecibels)
    {
        boostDecibelSmoother.setTargetValue(clampedBoostDb);
        lastConfiguredBoostDecibels = clampedBoostDb;
    }

    const auto clampedBandwidthNormalized = clampBandwidthNormalized(currentBandwidthNormalized);
    if (clampedBandwidthNormalized != lastConfiguredBandwidthNormalized)
    {
        bandwidthNormalizedSmoother.setTargetValue(clampedBandwidthNormalized);
        lastConfiguredBandwidthNormalized = clampedBandwidthNormalized;
    }
}

void PultecHfBoost::applyCoefficients(float boostDb, float q) noexcept
{
    const auto coefficients = makePeakCoefficients(currentSampleRate, currentFrequencyHz, boostDb, q);
    for (auto& channel : channels)
        channel.setCoefficients(coefficients);

    lastAppliedBoostDecibels = boostDb;
    lastAppliedBandwidthQ = q;
}

float PultecHfBoost::clampBoostDecibels(float boostDb) noexcept
{
    return juce::jlimit(0.0f, 18.0f, boostDb);
}

float PultecHfBoost::clampBandwidthNormalized(float bandwidthNormalized) noexcept
{
    return juce::jlimit(0.0f, 1.0f, bandwidthNormalized);
}

float PultecHfBoost::bandwidthNormalizedToQ(float bandwidthNormalized) noexcept
{
    const auto clampedBandwidth = clampBandwidthNormalized(bandwidthNormalized);
    if (clampedBandwidth <= 0.5f)
        return interpolateLogarithmic(sharpBandwidthQ, midBandwidthQ, clampedBandwidth * 2.0f);

    return interpolateLogarithmic(midBandwidthQ, broadBandwidthQ, (clampedBandwidth - 0.5f) * 2.0f);
}

PultecHfBoostBiquadCoefficients PultecHfBoost::makePeakCoefficients(double sampleRate, float frequencyHz, float boostDb, float q) noexcept
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
