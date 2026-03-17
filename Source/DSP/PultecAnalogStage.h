#pragma once

#include <JuceHeader.h>

#include "ParameterSmoother.h"

namespace ProgramEQ::DSP
{

class PultecAnalogStage
{
public:
    static constexpr int maxChannels = 2;

    void prepare(double sampleRate, int maximumBlockSize, int numChannels);
    void reset() noexcept;

    void setEnabled(bool shouldProcess) noexcept;
    void setDriveNormalized(float driveNormalized) noexcept;

    void process(juce::AudioBuffer<float>& buffer) noexcept;
    void process(juce::dsp::AudioBlock<float> block) noexcept;

private:
    static constexpr float smoothingTimeSeconds = 0.05f;
    static constexpr float minimumDriveNormalized = 0.0f;
    static constexpr float maximumDriveNormalized = 1.0f;
    static constexpr float maximumPreGain = 6.0f;
    static constexpr float maximumBias = 0.12f;
    static constexpr float denormalThreshold = 1.0e-15f;
    static constexpr float minimumLinearGain = 1.0e-6f;

    LinearParameterSmoother driveNormalizedSmoother;

    bool enabled = false;
    float currentDriveNormalized = 0.0f;
    float lastConfiguredDriveNormalized = -1.0f;

    void updateConfiguration() noexcept;
    static float clampDriveNormalized(float driveNormalized) noexcept;
    static float sanitizeSample(float sample) noexcept;
    static float driveNormalizedToPreGain(float driveNormalized) noexcept;
    static float processSample(float inputSample, float driveNormalized) noexcept;
    template <typename GetSample, typename SetSample>
    void processBlock(int numChannels, int numSamples, GetSample&& getSample, SetSample&& setSample) noexcept;
};

} // namespace ProgramEQ::DSP
