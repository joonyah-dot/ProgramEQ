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
    oversamplingModeParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::globalOversamplingMode);
    pultecEqInParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecEqIn);
    pultecLfFreqHzParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecLfFreqHz);
    pultecLfBoostDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecLfBoostDb);
    pultecLfAttenDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecLfAttenDb);
    pultecHfBoostFreqKhzParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfBoostFreqKhz);
    pultecHfBoostDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfBoostDb);
    pultecHfBandwidthParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfBandwidth);
    pultecHfAttenSelKhzParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfAttenSelKhz);
    pultecHfAttenDbParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecHfAttenDb);
    pultecAnalogEnabledParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecAnalogEnabled);
    pultecDriveParam = apvts.getRawParameterValue(ProgramEQ::Parameters::IDs::pultecDrive);
}

void ProgramEQAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    analogOversampling2x.reset();
    analogOversampling2x.initProcessing(static_cast<size_t>(samplesPerBlock));
    analogOversampling4x.reset();
    analogOversampling4x.initProcessing(static_cast<size_t>(samplesPerBlock));

    pultecAnalogStage1x.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
    pultecAnalogStage2x.prepare(sampleRate * 2.0, samplesPerBlock * 2, getTotalNumOutputChannels());
    pultecAnalogStage4x.prepare(sampleRate * 4.0, samplesPerBlock * 4, getTotalNumOutputChannels());
    pultecHfAttenuation.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
    pultecHfBoost.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
    pultecHfInteraction.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());
    pultecLfBoost.prepare(sampleRate, samplesPerBlock, getTotalNumOutputChannels());

    lastOversamplingMode = oversamplingModeOff;
    lastAnalogEnabled = false;
    lastReportedLatencySamples = -1;
    updateLatencyReporting(oversamplingModeOff, false);
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
    const auto oversamplingMode = oversamplingModeParam != nullptr ? juce::jlimit(oversamplingModeOff, oversamplingMode4x, juce::roundToInt(oversamplingModeParam->load())) : oversamplingModeOff;
    const auto analogEnabled = pultecAnalogEnabledParam != nullptr && pultecAnalogEnabledParam->load() >= 0.5f;
    const auto driveNormalized = pultecDriveParam != nullptr ? pultecDriveParam->load() : 0.0f;

    updateLatencyReporting(oversamplingMode, analogEnabled);
    if (oversamplingMode != lastOversamplingMode || analogEnabled != lastAnalogEnabled)
    {
        resetOversampledAnalogPath(oversamplingMode);
        lastOversamplingMode = oversamplingMode;
        lastAnalogEnabled = analogEnabled;
    }

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

    auto& analogStage = getAnalogStageForMode(oversamplingMode);
    analogStage.setEnabled(analogEnabled);
    analogStage.setDriveNormalized(driveNormalized);

    if (! analogEnabled || oversamplingMode == oversamplingModeOff)
    {
        analogStage.process(buffer);
        return;
    }

    auto* oversampler = getOversamplerForMode(oversamplingMode);
    jassert(oversampler != nullptr);
    if (oversampler == nullptr)
    {
        analogStage.process(buffer);
        return;
    }

    auto baseRateBlock = juce::dsp::AudioBlock<float>(buffer);
    auto oversampledBlock = oversampler->processSamplesUp(baseRateBlock);
    analogStage.process(oversampledBlock);
    oversampler->processSamplesDown(baseRateBlock);
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

void ProgramEQAudioProcessor::updateLatencyReporting(int oversamplingMode, bool analogEnabled) noexcept
{
    auto reportedLatencySamples = 0;
    if (analogEnabled)
    {
        if (auto* oversampler = getOversamplerForMode(oversamplingMode))
            reportedLatencySamples = juce::roundToInt(oversampler->getLatencyInSamples());
    }

    if (reportedLatencySamples != lastReportedLatencySamples)
    {
        setLatencySamples(reportedLatencySamples);
        lastReportedLatencySamples = reportedLatencySamples;
    }
}

void ProgramEQAudioProcessor::resetOversampledAnalogPath(int oversamplingMode) noexcept
{
    getAnalogStageForMode(oversamplingMode).reset();

    if (auto* oversampler = getOversamplerForMode(oversamplingMode))
        oversampler->reset();
}

ProgramEQ::DSP::PultecAnalogStage& ProgramEQAudioProcessor::getAnalogStageForMode(int oversamplingMode) noexcept
{
    switch (oversamplingMode)
    {
        case oversamplingMode2x: return pultecAnalogStage2x;
        case oversamplingMode4x: return pultecAnalogStage4x;
        case oversamplingModeOff:
        default: break;
    }

    return pultecAnalogStage1x;
}

juce::dsp::Oversampling<float>* ProgramEQAudioProcessor::getOversamplerForMode(int oversamplingMode) noexcept
{
    switch (oversamplingMode)
    {
        case oversamplingMode2x: return &analogOversampling2x;
        case oversamplingMode4x: return &analogOversampling4x;
        case oversamplingModeOff:
        default: break;
    }

    return nullptr;
}
