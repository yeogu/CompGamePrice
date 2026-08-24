cmake_minimum_required(VERSION 3.14)

project(game_price_tracker LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(game_price_tracker
    src/main.cpp
    src/domain_types.cpp
    src/game_catalog.cpp
    src/steam_provider.cpp
    src/google_play_provider.cpp
    src/apple_app_store_provider.cpp
    src/price_comparison_service.cpp
)

target_include_directories(game_price_tracker PRIVATE include)

target_compile_definitions(game_price_tracker PRIVATE
    SAMPLE_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/data"
)

if(MSVC)
    target_compile_options(game_price_tracker PRIVATE /W4)
else()
    target_compile_options(game_price_tracker PRIVATE -Wall -Wextra -Wpedantic)
endif()
