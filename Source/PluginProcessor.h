#pragma once
#include <JuceHeader.h>

#include "DSP/PultecHfBoost.h"
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
    APVTS apvts;
    ProgramEQ::DSP::PultecHfBoost pultecHfBoost;
    ProgramEQ::DSP::PultecLfBoost pultecLfBoost;

    std::atomic<float>* trueBypassParam = nullptr;
    std::atomic<float>* pultecEqInParam = nullptr;
    std::atomic<float>* pultecLfFreqHzParam = nullptr;
    std::atomic<float>* pultecLfBoostDbParam = nullptr;
    std::atomic<float>* pultecLfAttenDbParam = nullptr;
    std::atomic<float>* pultecHfBoostFreqKhzParam = nullptr;
    std::atomic<float>* pultecHfBoostDbParam = nullptr;
    std::atomic<float>* pultecHfBandwidthParam = nullptr;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ProgramEQAudioProcessor)
};
