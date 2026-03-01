#include "PluginEditor.h"

ProgramEQAudioProcessorEditor::ProgramEQAudioProcessorEditor (ProgramEQAudioProcessor& p)
    : AudioProcessorEditor (&p), processor (p)
{
    setSize (420, 260);
}

void ProgramEQAudioProcessorEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colours::black);
    g.setColour (juce::Colours::white);
    g.setFont (20.0f);
    g.drawFittedText ("ProgramEQ", getLocalBounds(), juce::Justification::centred, 1);
}

void ProgramEQAudioProcessorEditor::resized() {}
