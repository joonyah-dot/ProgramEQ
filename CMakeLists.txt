cmake_minimum_required(VERSION 3.15)

project(
    ProgramEQ
    VERSION 0.1.0
)

add_subdirectory(extern/juce)

option(USE_CHOWDSP_WDF "Enable chowdsp_wdf dependency integration" ON)

if(USE_CHOWDSP_WDF)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/external/chowdsp_wdf/CMakeLists.txt")
        message(FATAL_ERROR "USE_CHOWDSP_WDF is ON, but external/chowdsp_wdf is missing. Run: git submodule update --init --recursive")
    endif()

    set(CHOWDSP_WDF_BUILD_TESTS OFF CACHE BOOL "Build chowdsp_wdf tests" FORCE)
    set(CHOWDSP_WDF_BUILD_BENCHMARKS OFF CACHE BOOL "Build chowdsp_wdf benchmarks" FORCE)
    add_subdirectory(external/chowdsp_wdf)
endif()

option(BUILD_VST3_HARNESS "Build VST3 harness CLI" ON)
if(BUILD_VST3_HARNESS)
    add_subdirectory(tools/vst3_harness)
endif()

juce_add_plugin(
    ProgramEQ
    COMPANY_NAME "KyleAudio"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    FORMATS VST3 Standalone
    PRODUCT_NAME "ProgramEQ"
)

# Generates JuceHeader.h + sets up include paths correctly
juce_generate_juce_header(ProgramEQ)

# Beginner-safe: avoids VST3/VST2 replacement automation warnings
target_compile_definitions(
    ProgramEQ
    PRIVATE
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_USE_VST2_SDK=0
)

target_sources(
    ProgramEQ
    PRIVATE
    Source/DSP/PultecHfBoost.cpp
    Source/DSP/PultecHfBoost.h
    Source/DSP/PultecLfBoost.cpp
    Source/DSP/PultecLfBoost.h
    Source/Parameters.cpp
    Source/Parameters.h
    Source/PluginProcessor.cpp
    Source/PluginProcessor.h
    Source/PluginEditor.cpp
    Source/PluginEditor.h
    Source/PluginEntry.cpp
)

if(USE_CHOWDSP_WDF)
    target_link_libraries(
        ProgramEQ
        PRIVATE
        chowdsp_wdf
    )

    target_compile_definitions(
        ProgramEQ
        PRIVATE
        PROGRAM_EQ_USE_CHOWDSP_WDF=1
    )
else()
    target_compile_definitions(
        ProgramEQ
        PRIVATE
        PROGRAM_EQ_USE_CHOWDSP_WDF=0
    )
endif()

target_compile_features(
    ProgramEQ
    PRIVATE cxx_std_17
)

target_link_libraries(
    ProgramEQ
    PRIVATE
    juce::juce_audio_utils
    juce::juce_dsp
    juce::juce_gui_extra
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)
