#pragma once

#include <JuceHeader.h>

#include "ParameterSmoother.h"

namespace ProgramEQ::DSP
{

struct PultecHfAttenuationBiquadCoefficients
{
    float b0 = 1.0f;
    float b1 = 0.0f;
    float b2 = 0.0f;
    float a1 = 0.0f;
    float a2 = 0.0f;
};

class PultecHfAttenuationBiquadChannel
{
public:
    void reset() noexcept;
    void setCoefficients(const PultecHfAttenuationBiquadCoefficients& newCoefficients) noexcept;
    float processSample(float inputSample) noexcept;

private:
    PultecHfAttenuationBiquadCoefficients coefficients {};
    float z1 = 0.0f;
    float z2 = 0.0f;
};

class PultecHfAttenuation
{
public:
    static constexpr int maxChannels = 2;

    void prepare(double sampleRate, int maximumBlockSize, int numChannels);
    void reset() noexcept;

    void setEqInEnabled(bool shouldApply) noexcept;
    void setFrequencySelection(int selectionIndex) noexcept;
    void setAttenuationDecibels(float attenuationDb) noexcept;

    void process(juce::AudioBuffer<float>& buffer) noexcept;

    static float selectionToFrequencyHz(int selectionIndex) noexcept;

private:
    static constexpr float smoothingTimeSeconds = 0.05f;
    static constexpr float shelfSlope = 1.0f;

    std::array<PultecHfAttenuationBiquadChannel, maxChannels> channels {};
    LinearParameterSmoother attenuationDecibelSmoother;

    double currentSampleRate = 44100.0;
    bool eqInEnabled = true;
    int currentFrequencySelection = 0;
    float currentAttenuationDecibels = 0.0f;
    float currentFrequencyHz = 5000.0f;
    float lastConfiguredAttenuationDecibels = -1.0f;
    float lastAppliedAttenuationDecibels = -1.0f;

    void updateConfiguration() noexcept;
    void applyCoefficients(float attenuationDb) noexcept;
    static float clampAttenuationDecibels(float attenuationDb) noexcept;
    static PultecHfAttenuationBiquadCoefficients makeHighShelfCoefficients(double sampleRate, float frequencyHz, float attenuationDb, float slope) noexcept;
};

} // namespace ProgramEQ::DSP
