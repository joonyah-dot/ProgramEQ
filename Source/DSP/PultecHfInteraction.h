#pragma once

#include <JuceHeader.h>

#include "ParameterSmoother.h"

namespace ProgramEQ::DSP
{

struct PultecHfInteractionBiquadCoefficients
{
    float b0 = 1.0f;
    float b1 = 0.0f;
    float b2 = 0.0f;
    float a1 = 0.0f;
    float a2 = 0.0f;
};

class PultecHfInteractionBiquadChannel
{
public:
    void reset() noexcept;
    void setCoefficients(const PultecHfInteractionBiquadCoefficients& newCoefficients) noexcept;
    float processSample(float inputSample) noexcept;

private:
    PultecHfInteractionBiquadCoefficients coefficients {};
    float z1 = 0.0f;
    float z2 = 0.0f;
};

class PultecHfInteraction
{
public:
    static constexpr int maxChannels = 2;

    void prepare(double sampleRate, int maximumBlockSize, int numChannels);
    void reset() noexcept;

    void setEqInEnabled(bool shouldApply) noexcept;
    void setBoostFrequencySelection(int selectionIndex) noexcept;
    void setAttenuationSelection(int selectionIndex) noexcept;
    void setBoostDecibels(float boostDb) noexcept;
    void setAttenuationDecibels(float attenuationDb) noexcept;

    void process(juce::AudioBuffer<float>& buffer) noexcept;

private:
    static constexpr float smoothingTimeSeconds = 0.05f;
    static constexpr float interactionQ = 1.0f;

    std::array<PultecHfInteractionBiquadChannel, maxChannels> channels {};
    LinearParameterSmoother interactionBoostDecibelSmoother;

    double currentSampleRate = 44100.0;
    bool eqInEnabled = true;
    int currentBoostFrequencySelection = 0;
    int currentAttenuationSelection = 0;
    float currentBoostDecibels = 0.0f;
    float currentAttenuationDecibels = 0.0f;
    float currentFrequencyHz = 3000.0f;
    float lastConfiguredInteractionBoostDb = -1.0f;
    float lastAppliedInteractionBoostDb = -1.0f;

    void updateConfiguration() noexcept;
    void applyCoefficients(float interactionBoostDb) noexcept;
    static float computeInteractionBoostDb(float boostDb, float attenuationDb, float boostFrequencyHz, float attenuationFrequencyHz) noexcept;
    static float clampInteractionBoostDb(float interactionBoostDb) noexcept;
    static float selectionToBoostFrequencyHz(int selectionIndex) noexcept;
    static float selectionToAttenuationFrequencyHz(int selectionIndex) noexcept;
    static PultecHfInteractionBiquadCoefficients makePeakCoefficients(double sampleRate, float frequencyHz, float boostDb, float q) noexcept;
};

} // namespace ProgramEQ::DSP
