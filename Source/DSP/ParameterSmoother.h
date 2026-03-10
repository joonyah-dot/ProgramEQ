#pragma once

#include <JuceHeader.h>

namespace ProgramEQ::DSP
{

class LinearParameterSmoother
{
public:
    void prepare(double sampleRate, float rampTimeSeconds, float initialValue) noexcept
    {
        smoother.reset(sampleRate, rampTimeSeconds);
        smoother.setCurrentAndTargetValue(initialValue);
    }

    void reset(float value) noexcept
    {
        smoother.setCurrentAndTargetValue(value);
    }

    void setTargetValue(float value) noexcept
    {
        smoother.setTargetValue(value);
    }

    float getNextValue() noexcept
    {
        return smoother.getNextValue();
    }

    float getCurrentValue() const noexcept
    {
        return smoother.getCurrentValue();
    }

    bool isSmoothing() const noexcept
    {
        return smoother.isSmoothing();
    }

private:
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> smoother;
};

} // namespace ProgramEQ::DSP
