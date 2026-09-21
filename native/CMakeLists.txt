cmake_minimum_required(VERSION 3.26)

if(NOT DEFINED KSM2SDVX_UPSTREAM)
  set(KSM2SDVX_UPSTREAM "${CMAKE_CURRENT_SOURCE_DIR}/../external/ksm-v2")
endif()
if(NOT TARGET ksmaudio)
  add_subdirectory("${KSM2SDVX_UPSTREAM}/ksmaudio" "${CMAKE_CURRENT_BINARY_DIR}/ksmaudio")
endif()

add_library(ksm2sdvx_audio STATIC render.cpp)
target_compile_features(ksm2sdvx_audio PUBLIC cxx_std_20)
target_include_directories(ksm2sdvx_audio PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_include_directories(ksm2sdvx_audio SYSTEM PUBLIC
  "${KSM2SDVX_UPSTREAM}/kson/include/kson/third_party")
target_link_libraries(ksm2sdvx_audio PUBLIC ksmaudio)
target_compile_definitions(ksm2sdvx_audio PUBLIC NOMINMAX WIN32_LEAN_AND_MEAN)
target_compile_options(ksm2sdvx_audio PRIVATE "$<$<CXX_COMPILER_ID:MSVC>:/W4;/utf-8>")

add_executable(ksm2sdvx-render main.cpp)
target_link_libraries(ksm2sdvx-render PRIVATE ksm2sdvx_audio)
if(MSVC)
  target_link_libraries(ksm2sdvx-render PRIVATE delayimp)
  target_link_options(ksm2sdvx-render PRIVATE /DELAYLOAD:bass.dll /DELAYLOAD:bass_fx.dll)
endif()

foreach(runtime bass bass_fx)
  add_custom_command(TARGET ksm2sdvx-render POST_BUILD COMMAND "${CMAKE_COMMAND}" -E copy_if_different
    "${KSM2SDVX_UPSTREAM}/ksmaudio/ThirdParty_Windows/${runtime}/${runtime}.dll"
    "$<TARGET_FILE_DIR:ksm2sdvx-render>/${runtime}.dll")
endforeach()

if(BUILD_TESTING)
  add_executable(ksm2sdvx-render-tests tests.cpp)
  target_link_libraries(ksm2sdvx-render-tests PRIVATE ksm2sdvx_audio)
  add_dependencies(ksm2sdvx-render-tests ksm2sdvx-render)
  add_test(NAME native-audio COMMAND ksm2sdvx-render-tests)
endif()
