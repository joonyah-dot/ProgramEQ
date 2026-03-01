#pragma once
#include <JuceHeader.h>
#include "PluginProcessor.h"

class ProgramEQAudioProcessorEditor : public juce::AudioProcessorEditor
{
public:
    explicit ProgramEQAudioProcessorEditor (ProgramEQAudioProcessor&);
    ~ProgramEQAudioProcessorEditor() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    ProgramEQAudioProcessor& processor;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ProgramEQAudioProcessorEditor)
};
