#pragma once
#include <JuceHeader.h>

#include "DSP/PultecAnalogStage.h"
#include "DSP/PultecHfAttenuation.h"
#include "DSP/PultecHfBoost.h"
#include "DSP/PultecHfInteraction.h"
#include "DSP/PultecLfBoost.h"
#include "Parameters.h"

class ProgramEQAudioProcessor : public juce::AudioProcessor
{
public:
    using APVTS = juce::AudioProcessorValueTreeState;

    ProgramEQAudioProcessor();
    ~ProgramEQAudioProcessor() override = default;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock&) override;
    void setStateInformation (const void*, int) override;

    APVTS& getValueTreeState() noexcept { return apvts; }
    const APVTS& getValueTreeState() const noexcept { return apvts; }

private:
    static constexpr int maxChannels = 2;
    static constexpr int oversamplingModeOff = 0;
    static constexpr int oversamplingMode2x = 1;
    static constexpr int oversamplingMode4x = 2;

    APVTS apvts;
    ProgramEQ::DSP::PultecAnalogStage pultecAnalogStage1x;
    ProgramEQ::DSP::PultecAnalogStage pultecAnalogStage2x;
    ProgramEQ::DSP::PultecAnalogStage pultecAnalogStage4x;
    ProgramEQ::DSP::PultecHfAttenuation pultecHfAttenuation;
    ProgramEQ::DSP::PultecHfBoost pultecHfBoost;
    ProgramEQ::DSP::PultecHfInteraction pultecHfInteraction;
    ProgramEQ::DSP::PultecLfBoost pultecLfBoost;
    juce::dsp::Oversampling<float> analogOversampling2x { static_cast<size_t>(maxChannels),
                                                          1u,
                                                          juce::dsp::Oversampling<float>::filterHalfBandPolyphaseIIR,
                                                          true,
                                                          true };
    juce::dsp::Oversampling<float> analogOversampling4x { static_cast<size_t>(maxChannels),
                                                          2u,
                                                          juce::dsp::Oversampling<float>::filterHalfBandPolyphaseIIR,
                                                          true,
                                                          true };

    std::atomic<float>* trueBypassParam = nullptr;
    std::atomic<float>* oversamplingModeParam = nullptr;
    std::atomic<float>* pultecEqInParam = nullptr;
    std::atomic<float>* pultecLfFreqHzParam = nullptr;
    std::atomic<float>* pultecLfBoostDbParam = nullptr;
    std::atomic<float>* pultecLfAttenDbParam = nullptr;
    std::atomic<float>* pultecHfBoostFreqKhzParam = nullptr;
    std::atomic<float>* pultecHfBoostDbParam = nullptr;
    std::atomic<float>* pultecHfBandwidthParam = nullptr;
    std::atomic<float>* pultecHfAttenSelKhzParam = nullptr;
    std::atomic<float>* pultecHfAttenDbParam = nullptr;
    std::atomic<float>* pultecAnalogEnabledParam = nullptr;
    std::atomic<float>* pultecDriveParam = nullptr;

    int lastReportedLatencySamples = -1;
    int lastOversamplingMode = oversamplingModeOff;
    bool lastAnalogEnabled = false;

    void updateLatencyReporting(int oversamplingMode, bool analogEnabled) noexcept;
    void resetOversampledAnalogPath(int oversamplingMode) noexcept;
    ProgramEQ::DSP::PultecAnalogStage& getAnalogStageForMode(int oversamplingMode) noexcept;
    juce::dsp::Oversampling<float>* getOversamplerForMode(int oversamplingMode) noexcept;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ProgramEQAudioProcessor)
};
