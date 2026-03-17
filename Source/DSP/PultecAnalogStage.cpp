#include "PultecAnalogStage.h"

#include <cmath>

namespace ProgramEQ::DSP
{

void PultecAnalogStage::prepare(double sampleRate, int maximumBlockSize, int numChannels)
{
    juce::ignoreUnused(maximumBlockSize, numChannels);

    driveNormalizedSmoother.prepare(sampleRate, smoothingTimeSeconds, clampDriveNormalized(currentDriveNormalized));
    lastConfiguredDriveNormalized = -1.0f;
    reset();
    updateConfiguration();
}

void PultecAnalogStage::reset() noexcept
{
    driveNormalizedSmoother.reset(clampDriveNormalized(currentDriveNormalized));
}

void PultecAnalogStage::setEnabled(bool shouldProcess) noexcept
{
    enabled = shouldProcess;
}

void PultecAnalogStage::setDriveNormalized(float driveNormalized) noexcept
{
    currentDriveNormalized = driveNormalized;
}

void PultecAnalogStage::process(juce::AudioBuffer<float>& buffer) noexcept
{
    updateConfiguration();

    if (! enabled)
        return;

    if (! driveNormalizedSmoother.isSmoothing() && driveNormalizedSmoother.getCurrentValue() <= minimumDriveNormalized)
        return;

    const auto numChannels = juce::jmin(buffer.getNumChannels(), maxChannels);
    const auto numSamples = buffer.getNumSamples();
    processBlock(
        numChannels,
        numSamples,
        [&buffer](int channelIndex, int sampleIndex) noexcept
        {
            return buffer.getReadPointer(channelIndex)[sampleIndex];
        },
        [&buffer](int channelIndex, int sampleIndex, float sample) noexcept
        {
            buffer.getWritePointer(channelIndex)[sampleIndex] = sample;
        });
}

void PultecAnalogStage::process(juce::dsp::AudioBlock<float> block) noexcept
{
    updateConfiguration();

    if (! enabled)
        return;

    if (! driveNormalizedSmoother.isSmoothing() && driveNormalizedSmoother.getCurrentValue() <= minimumDriveNormalized)
        return;

    const auto numChannels = juce::jmin(static_cast<int>(block.getNumChannels()), maxChannels);
    const auto numSamples = static_cast<int>(block.getNumSamples());
    processBlock(
        numChannels,
        numSamples,
        [&block](int channelIndex, int sampleIndex) noexcept
        {
            return block.getChannelPointer(static_cast<size_t>(channelIndex))[sampleIndex];
        },
        [&block](int channelIndex, int sampleIndex, float sample) noexcept
        {
            block.getChannelPointer(static_cast<size_t>(channelIndex))[sampleIndex] = sample;
        });
}

void PultecAnalogStage::updateConfiguration() noexcept
{
    const auto clampedDriveNormalized = clampDriveNormalized(currentDriveNormalized);
    if (clampedDriveNormalized != lastConfiguredDriveNormalized)
    {
        driveNormalizedSmoother.setTargetValue(clampedDriveNormalized);
        lastConfiguredDriveNormalized = clampedDriveNormalized;
    }
}

float PultecAnalogStage::clampDriveNormalized(float driveNormalized) noexcept
{
    return juce::jlimit(minimumDriveNormalized, maximumDriveNormalized, driveNormalized);
}

float PultecAnalogStage::sanitizeSample(float sample) noexcept
{
    if (! std::isfinite(sample) || std::abs(sample) < denormalThreshold)
        return 0.0f;

    return sample;
}

float PultecAnalogStage::driveNormalizedToPreGain(float driveNormalized) noexcept
{
    return 1.0f + (clampDriveNormalized(driveNormalized) * (maximumPreGain - 1.0f));
}

float PultecAnalogStage::processSample(float inputSample, float driveNormalized) noexcept
{
    const auto sanitizedInput = sanitizeSample(inputSample);
    const auto clampedDriveNormalized = clampDriveNormalized(driveNormalized);
    if (clampedDriveNormalized <= minimumDriveNormalized)
        return sanitizedInput;

    const auto preGain = driveNormalizedToPreGain(clampedDriveNormalized);
    const auto bias = maximumBias * clampedDriveNormalized;
    const auto biasedCenter = std::tanh(preGain * bias);
    const auto smallSignalGain = juce::jmax(minimumLinearGain, preGain * (1.0f - (biasedCenter * biasedCenter)));
    const auto saturated = std::tanh(preGain * (sanitizedInput + bias)) - biasedCenter;
    return sanitizeSample(saturated / smallSignalGain);
}

template <typename GetSample, typename SetSample>
void PultecAnalogStage::processBlock(int numChannels, int numSamples, GetSample&& getSample, SetSample&& setSample) noexcept
{
    for (int sampleIndex = 0; sampleIndex < numSamples; ++sampleIndex)
    {
        const auto driveNormalized = driveNormalizedSmoother.getNextValue();

        for (int channelIndex = 0; channelIndex < numChannels; ++channelIndex)
            setSample(channelIndex, sampleIndex, processSample(getSample(channelIndex, sampleIndex), driveNormalized));
    }
}

} // namespace ProgramEQ::DSP
