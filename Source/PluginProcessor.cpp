#include "PluginProcessor.h"
#include "PluginEditor.h"

ProgramEQAudioProcessor::ProgramEQAudioProcessor()
    : AudioProcessor (BusesProperties()
        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
        .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this,
             nullptr,
             juce::Identifier (ProgramEQ::Parameters::stateTreeType),
             ProgramEQ::Parameters::createParameterLayout())
{
    trueBypassParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::globalTrueBypass);
    pultecEqInParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecEqIn);
    pultecLfFreqHzParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecLfFreqHz);
    pultecLfBoostDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecLfBoostDb);
    pultecLfAttenDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecLfAttenDb);
    pultecHfBoostFreqKhzParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfBoostFreqKhz);
    pultecHfBoostDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfBoostDb);
    pultecHfBandwidthParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfBandwidth);
    pultecHfAttenSelKhzParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfAttenSelKhz);
    pultecHfAttenDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfAttenDb);
}

void ProgramEQAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    pultecHfAttenuation.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
    pultecHfBoost.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
    pultecHfInteraction.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
    pultecLfBoost.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
}

void ProgramEQAudioProcessor::releaseResources() {}

bool ProgramEQAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    return layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

void ProgramEQAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;

    if (trueBypassParam != nullptr && trueBypassParam->load() >= 0.5f)
        return;

    const auto eqInEnabled = pultecEqInParam == nullptr || pultecEqInParam->load() >= 0.5f;
    const auto frequencySelection = pultecLfFreqHzParam != nullptr ? juce::roundToInt(pultecLfFreqHzParam->load()) : 0;
    const auto boostDb = pultecLfBoostDbParam != nullptr ? pultecLfBoostDbParam->load() : 0.0f;
    const auto attenuationDb = pultecLfAttenDbParam != nullptr ? pultecLfAttenDbParam->load() : 0.0f;
    const auto hfFrequencySelection = pultecHfBoostFreqKhzParam != nullptr ? juce::roundToInt(pultecHfBoostFreqKhzParam->load()) : 0;
    const auto hfBoostDb = pultecHfBoostDbParam != nullptr ? pultecHfBoostDbParam->load() : 0.0f;
    const auto hfBandwidthNormalized = pultecHfBandwidthParam != nullptr ? pultecHfBandwidthParam->load() : 0.5f;
    const auto hfAttenuationSelection = pultecHfAttenSelKhzParam != nullptr ? juce::roundToInt(pultecHfAttenSelKhzParam->load()) : 0;
    const auto hfAttenuationDb = pultecHfAttenDbParam != nullptr ? pultecHfAttenDbParam->load() : 0.0f;

    pultecLfBoost.setEqInEnabled(eqInEnabled);
    pultecLfBoost.setFrequencySelection(frequencySelection);
    pultecLfBoost.setBoostDecibels(boostDb);
    pultecLfBoost.setAttenuationDecibels(attenuationDb);
    pultecLfBoost.process(buffer);

    pultecHfBoost.setEqInEnabled(eqInEnabled);
    pultecHfBoost.setFrequencySelection(hfFrequencySelection);
    pultecHfBoost.setBoostDecibels(hfBoostDb);
    pultecHfBoost.setBandwidthNormalized(hfBandwidthNormalized);
    pultecHfBoost.process(buffer);

    pultecHfAttenuation.setEqInEnabled(eqInEnabled);
    pultecHfAttenuation.setFrequencySelection(hfAttenuationSelection);
    pultecHfAttenuation.setAttenuationDecibels(hfAttenuationDb);
    pultecHfAttenuation.process(buffer);

    pultecHfInteraction.setEqInEnabled(eqInEnabled);
    pultecHfInteraction.setBoostFrequencySelection(hfFrequencySelection);
    pultecHfInteraction.setAttenuationSelection(hfAttenuationSelection);
    pultecHfInteraction.setBoostDecibels(hfBoostDb);
    pultecHfInteraction.setAttenuationDecibels(hfAttenuationDb);
    pultecHfInteraction.process(buffer);
}

juce::AudioProcessorEditor* ProgramEQAudioProcessor::createEditor()
{
    return new ProgramEQAudioProcessorEditor (*this);
}

void ProgramEQAudioProcessor::getStateInformation (juce::MemoryBlock& destinationData)
{
    const auto state = apvts.copyState();
    std::unique_ptr<juce::XmlElement> xml(state.createXml());

    if (xml != nullptr)
        copyXmlToBinary(*xml, destinationData);
}

void ProgramEQAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (data == nullptr || sizeInBytes <= 0)
        return;

    const std::unique_ptr<juce::XmlElement> xml(getXmlFromBinary(data, sizeInBytes));
    if (xml == nullptr)
        return;

    const auto state = juce::ValueTree::fromXml(*xml);
    if (state.isValid() && state.hasType(juce::Identifier(ProgramEQ::Parameters::stateTreeType)))
        apvts.replaceState(state);
}
