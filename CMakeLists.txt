cmake_minimum_required(VERSION 3.14)

project(game_price_tracker LANGUAGES CXX)

find_package(SQLite3 REQUIRED)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(game_price_core
    src/domain_types.cpp
    src/crawl_run.cpp
    src/collection_service.cpp
    src/database.cpp
    src/store_product_repository.cpp
    src/game_catalog.cpp
    src/steam_provider.cpp
    src/google_play_provider.cpp
    src/apple_app_store_provider.cpp
    src/price_comparison_service.cpp
    src/price_history_service.cpp
    src/purchase_recommendation_service.cpp
)

target_include_directories(game_price_core PUBLIC include)

if(TARGET SQLite3::SQLite3)
    target_link_libraries(game_price_core PUBLIC SQLite3::SQLite3)
else()
    target_link_libraries(game_price_core PUBLIC SQLite::SQLite3)
endif()

add_executable(game_price_tracker src/main.cpp)
target_link_libraries(game_price_tracker PRIVATE game_price_core)

target_compile_definitions(game_price_tracker PRIVATE
    SAMPLE_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/data"
    GAME_PRICE_DATABASE_PATH="${CMAKE_CURRENT_BINARY_DIR}/game_prices.db"
)

function(enable_project_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endfunction()

enable_project_warnings(game_price_core)
enable_project_warnings(game_price_tracker)

include(CTest)
if(BUILD_TESTING)
    add_executable(game_price_tests tests/game_price_tests.cpp)
    target_link_libraries(game_price_tests PRIVATE game_price_core)
    target_compile_definitions(game_price_tests PRIVATE
        TEST_SAMPLE_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/data"
    )
    enable_project_warnings(game_price_tests)
    add_test(NAME game_price_tests COMMAND game_price_tests)
endif()
