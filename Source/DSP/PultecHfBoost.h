#pragma once

#include <JuceHeader.h>

#include "ParameterSmoother.h"

namespace ProgramEQ::DSP
{

struct PultecHfBoostBiquadCoefficients
{
    float b0 = 1.0f;
    float b1 = 0.0f;
    float b2 = 0.0f;
    float a1 = 0.0f;
    float a2 = 0.0f;
};

class PultecHfBoostBiquadChannel
{
public:
    void reset() noexcept;
    void setCoefficients(const PultecHfBoostBiquadCoefficients& newCoefficients) noexcept;
    float processSample(float inputSample) noexcept;

private:
    PultecHfBoostBiquadCoefficients coefficients {};
    float z1 = 0.0f;
    float z2 = 0.0f;
};

class PultecHfBoost
{
public:
    static constexpr int maxChannels = 2;

    void prepare(double sampleRate, int maximumBlockSize, int numChannels);
    void reset() noexcept;

    void setEqInEnabled(bool shouldApply) noexcept;
    void setFrequencySelection(int selectionIndex) noexcept;
    void setBoostDecibels(float boostDb) noexcept;
    void setBandwidthNormalized(float bandwidthNormalized) noexcept;

    void process(juce::AudioBuffer<float>& buffer) noexcept;

    static float selectionToFrequencyHz(int selectionIndex) noexcept;

private:
    static constexpr float smoothingTimeSeconds = 0.05f;
    static constexpr float midBandwidthQ = 0.70710678f;
    static constexpr float sharpBandwidthQ = 1.6f;
    static constexpr float broadBandwidthQ = 0.5f;

    std::array<PultecHfBoostBiquadChannel, maxChannels> channels {};
    LinearParameterSmoother boostDecibelSmoother;
    LinearParameterSmoother bandwidthNormalizedSmoother;

    double currentSampleRate = 44100.0;
    bool eqInEnabled = true;
    int currentFrequencySelection = 0;
    float currentBoostDecibels = 0.0f;
    float currentBandwidthNormalized = 0.5f;
    float currentFrequencyHz = 3000.0f;
    float lastConfiguredBoostDecibels = -1.0f;
    float lastConfiguredBandwidthNormalized = -1.0f;
    float lastAppliedBoostDecibels = -1.0f;
    float lastAppliedBandwidthQ = -1.0f;

    void updateConfiguration() noexcept;
    void applyCoefficients(float boostDb, float q) noexcept;
    static float clampBoostDecibels(float boostDb) noexcept;
    static float clampBandwidthNormalized(float bandwidthNormalized) noexcept;
    static float bandwidthNormalizedToQ(float bandwidthNormalized) noexcept;
    static PultecHfBoostBiquadCoefficients makePeakCoefficients(double sampleRate, float frequencyHz, float boostDb, float q) noexcept;
};

} // namespace ProgramEQ::DSP
