#pragma once

#include <JuceHeader.h>

#include "ParameterSmoother.h"

#if PROGRAM_EQ_USE_CHOWDSP_WDF
#include <chowdsp_wdf/chowdsp_wdf.h>
#endif

namespace ProgramEQ::DSP
{

#if PROGRAM_EQ_USE_CHOWDSP_WDF
struct PultecLfBoostLowpassChannel
{
    static constexpr float capacitorValueFarads = 1.0e-6f;

    chowdsp::wdf::Capacitor<float> capacitor { capacitorValueFarads, 48000.0f };
    chowdsp::wdf::Resistor<float> resistor { 7957.7471f };
    chowdsp::wdf::WDFSeries<float> series { &resistor, &capacitor };
    chowdsp::wdf::PolarityInverter<float> inverter { &series };
    chowdsp::wdf::IdealVoltageSource<float> source { &inverter };

    void prepare(double sampleRate) noexcept;
    void reset() noexcept;
    void setFrequency(float frequencyHz) noexcept;
    float processSample(float inputSample) noexcept;
};
#else
struct PultecLfBoostLowpassChannel
{
    juce::dsp::StateVariableTPTFilter<float> filter { juce::dsp::StateVariableTPTFilterType::lowpass };

    void prepare(double sampleRate) noexcept;
    void reset() noexcept;
    void setFrequency(float frequencyHz) noexcept;
    float processSample(float inputSample) noexcept;
};
#endif

class PultecLfBoost
{
public:
    static constexpr int maxChannels = 2;

    void prepare(double sampleRate, int maximumBlockSize, int numChannels);
    void reset() noexcept;

    void setEqInEnabled(bool shouldApply) noexcept;
    void setFrequencySelection(int selectionIndex) noexcept;
    void setBoostDecibels(float boostDb) noexcept;

    void process(juce::AudioBuffer<float>& buffer) noexcept;

    static float selectionToFrequencyHz(int selectionIndex) noexcept;

private:
    static constexpr float smoothingTimeSeconds = 0.05f;

    std::array<PultecLfBoostLowpassChannel, maxChannels> channels {};
    LinearParameterSmoother branchGainSmoother;

    double currentSampleRate = 44100.0;
    bool eqInEnabled = true;
    int currentFrequencySelection = 0;
    float currentBoostDecibels = 0.0f;
    float lastConfiguredFrequencyHz = -1.0f;
    float lastConfiguredBranchGain = -1.0f;

    void updateConfiguration() noexcept;
    static float computeBranchGain(float boostDb) noexcept;
};

} // namespace ProgramEQ::DSP
