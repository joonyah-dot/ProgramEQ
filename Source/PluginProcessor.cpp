#include "PluginProcessor.h"
#include "PluginEditor.h"

ProgramEQAudioProcessor::ProgramEQAudioProcessor()
    : AudioProcessor (BusesProperties()
        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
        .withOutput ("Output", juce::AudioChannelSet::stereo(), true))
{
}

void ProgramEQAudioProcessor::prepareToPlay (double, int) {}
void ProgramEQAudioProcessor::releaseResources() {}

bool ProgramEQAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    return layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

void ProgramEQAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;
    juce::ignoreUnused (buffer);
    // passthrough
}

juce::AudioProcessorEditor* ProgramEQAudioProcessor::createEditor()
{
    return new ProgramEQAudioProcessorEditor (*this);
}
