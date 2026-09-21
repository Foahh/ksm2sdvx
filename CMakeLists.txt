cmake_minimum_required(VERSION 3.26)
project(ksm2sdvx LANGUAGES NONE)

set(KSM2SDVX_UPSTREAM "${CMAKE_CURRENT_SOURCE_DIR}/external/ksm-v2")

if(WIN32)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    enable_language(CXX)
    if(NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR
       NOT MSVC_CXX_ARCHITECTURE_ID STREQUAL "x64")
        message(FATAL_ERROR "The offline renderer requires an MSVC Windows x64 build.")
    endif()

    foreach(required IN ITEMS
        ksmaudio/CMakeLists.txt
        kson/include/kson/third_party/nlohmann/json.hpp
        kshootmania/App/se/note/clap.wav)
        if(NOT EXISTS "${KSM2SDVX_UPSTREAM}/${required}")
            message(FATAL_ERROR
                "Missing upstream build input: ${required}. Initialize external/ksm-v2 and its ksmaudio and kson submodules.")
        endif()
    endforeach()

    set(bass_dir "${KSM2SDVX_UPSTREAM}/ksmaudio/ThirdParty_Windows")
    file(SHA256 "${bass_dir}/bass/bass.dll" bass_sha256)
    file(SHA256 "${bass_dir}/bass_fx/bass_fx.dll" bass_fx_sha256)
    if(NOT bass_sha256 STREQUAL "febb2cf1882d554c3a958280777da0b69f07de6e262df271de11c56e4a54afd4"
       OR NOT bass_fx_sha256 STREQUAL "a6e1847eef52d882b4137af514d834c2e220daceb417c821d1e502fb7a34c84a")
        message(FATAL_ERROR "Bundled BASS runtime hashes changed; review and test the dependency update.")
    endif()

    include(CTest)
    add_subdirectory(native)

    set(runtime_destination "ksm2sdvx/music/_native")
    install(TARGETS ksm2sdvx-render RUNTIME DESTINATION "${runtime_destination}")
    install(FILES "${bass_dir}/bass/bass.dll" "${bass_dir}/bass_fx/bass_fx.dll"
        DESTINATION "${runtime_destination}")
    foreach(preset IN ITEMS clap clap_impact clap_punchy snare snare_lo)
        install(FILES "${KSM2SDVX_UPSTREAM}/kshootmania/App/se/note/${preset}.wav"
            DESTINATION "${runtime_destination}/presets")
    endforeach()
    install(FILES "${KSM2SDVX_UPSTREAM}/LICENSE"
        DESTINATION "${runtime_destination}/licenses" RENAME "ksm-v2.txt")
    install(FILES "${KSM2SDVX_UPSTREAM}/ksmaudio/THIRD_PARTY_LICENSE.txt"
        DESTINATION "${runtime_destination}/licenses" RENAME "ksmaudio-dependencies.txt")
    install(FILES "${KSM2SDVX_UPSTREAM}/kson/LICENSE"
        DESTINATION "${runtime_destination}/licenses" RENAME "libkson.txt")
    install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/LICENSES/"
        DESTINATION "${runtime_destination}/licenses")
endif()
