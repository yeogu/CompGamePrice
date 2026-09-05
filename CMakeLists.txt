cmake_minimum_required(VERSION 3.14)

project(game_price_tracker LANGUAGES CXX)

find_package(SQLite3 REQUIRED)
find_package(OpenSSL REQUIRED)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(game_price_core
    src/app/command_line.cpp
    src/app/game_query_service.cpp
    src/domain/domain_types.cpp
    src/domain/store_product_validator.cpp
    src/notification/account_repository.cpp
    src/notification/alert_service.cpp
    src/notification/auth_service.cpp
    src/notification/notification.cpp
    src/notification/oauth_service.cpp
    src/catalog/game_catalog.cpp
    src/collection/apple_app_store_provider.cpp
    src/collection/collection_service.cpp
    src/collection/console_store_provider.cpp
    src/collection/crawl_run.cpp
    src/collection/epic_games_provider.cpp
    src/collection/google_play_provider.cpp
    src/collection/nintendo_eshop_provider.cpp
    src/collection/steam_provider.cpp
    src/persistence/database.cpp
    src/persistence/store_product_repository.cpp
    src/pricing/price_comparison_service.cpp
    src/pricing/price_history_service.cpp
    src/recommendation/purchase_recommendation_service.cpp
    src/support/date_utils.cpp
)

target_include_directories(game_price_core PUBLIC include)

if(TARGET SQLite3::SQLite3)
    target_link_libraries(game_price_core PUBLIC SQLite3::SQLite3)
else()
    target_link_libraries(game_price_core PUBLIC SQLite::SQLite3)
endif()
target_link_libraries(game_price_core PUBLIC OpenSSL::Crypto)

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

option(BUILD_GAME_PRICE_API "Build the Drogon HTTP API server" ON)
if(BUILD_GAME_PRICE_API)
    find_package(Drogon CONFIG QUIET)
    if(Drogon_FOUND)
        add_executable(game_price_api src/api/main.cpp)
        target_link_libraries(game_price_api PRIVATE game_price_core Drogon::Drogon)
        target_compile_definitions(game_price_api PRIVATE
            SAMPLE_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/data"
            PROJECT_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
            GAME_PRICE_DATABASE_PATH="${CMAKE_CURRENT_BINARY_DIR}/game_prices.db"
        )
        enable_project_warnings(game_price_api)
    else()
        message(STATUS "Drogon not found; game_price_api target will not be built")
    endif()
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(game_price_tests tests/game_price_tests.cpp)
    target_link_libraries(game_price_tests PRIVATE game_price_core)
    target_compile_definitions(game_price_tests PRIVATE
        TEST_SAMPLE_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/data"
    )
    enable_project_warnings(game_price_tests)
    add_test(NAME game_price_tests COMMAND game_price_tests)
    add_test(
        NAME production_catalog_smoke_test
        COMMAND game_price_tracker search Terraria
    )
    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_test(
            NAME steam_collector_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_collector.py
        )
        add_test(
            NAME console_collector_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_console_collector.py
        )
        add_test(
            NAME steam_catalog_import_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_catalog_import.py
        )
        add_test(
            NAME catalog_storage_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_catalog_storage.py
        )
        add_test(
            NAME catalog_metadata_update_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_catalog_metadata_update.py
        )
        add_test(
            NAME catalog_metadata_audit_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_catalog_metadata_audit.py
        )
        add_test(
            NAME steam_metadata_sync_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_metadata_sync.py
        )
        add_test(
            NAME admin_health_summary_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_admin_health_summary.py
        )
        add_test(
            NAME catalog_price_integrity_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_catalog_price_integrity.py
        )
        add_test(
            NAME steam_catalog_batch_import_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_catalog_batch_import.py
        )
        add_test(
            NAME steam_catalog_search_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_catalog_search.py
        )
        add_test(
            NAME steam_catalog_sync_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_catalog_sync.py
        )
        add_test(
            NAME catalog_sync_pipeline_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_catalog_sync_pipeline.py
        )
        add_test(
            NAME steam_catalog_discovery_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_catalog_discovery.py
        )
        add_test(
            NAME steam_pipeline_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_steam_pipeline.py
        )
        add_test(
            NAME storage_retention_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_storage_retention.py
        )
        add_test(
            NAME database_backup_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_database_backup.py
        )
        add_test(
            NAME macos_schedule_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_macos_schedule.py
        )
        add_test(
            NAME collection_health_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_collection_health.py
        )
        add_test(
            NAME collection_scheduler_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_collection_scheduler.py
        )
        add_test(
            NAME backup_scheduler_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_backup_scheduler.py
        )
        add_test(
            NAME email_dispatcher_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_email_dispatcher.py
        )
        add_test(
            NAME notification_outbox_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_notification_outbox.py
        )
        add_test(
            NAME apple_collector_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_apple_collector.py
        )
        add_test(
            NAME apple_catalog_search_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_apple_catalog_search.py
        )
        add_test(
            NAME apple_catalog_import_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_apple_catalog_import.py
        )
        add_test(
            NAME apple_pipeline_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_apple_pipeline.py
        )
        add_test(
            NAME google_play_collector_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_google_play_collector.py
        )
        add_test(
            NAME google_play_catalog_search_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_google_play_catalog_search.py
        )
        add_test(
            NAME google_play_catalog_import_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_google_play_catalog_import.py
        )
        add_test(
            NAME mobile_catalog_sync_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_mobile_catalog_sync.py
        )
        add_test(
            NAME storefront_catalog_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_storefront_catalog.py
        )
        add_test(
            NAME storefront_price_collector_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_storefront_price_collectors.py
        )
        add_test(
            NAME storefront_price_pipeline_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_storefront_price_pipeline.py
        )
        add_test(
            NAME remove_catalog_product_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_remove_catalog_product.py
        )
        add_test(
            NAME set_user_role_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_set_user_role.py
        )
        add_test(
            NAME daily_operations_tests
            COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_daily_operations.py
        )
        if(APPLE)
            add_test(
                NAME macos_schedule_script_syntax
                COMMAND bash -n ${CMAKE_CURRENT_SOURCE_DIR}/tools/manage_macos_schedule.sh
            )
        endif()
        add_test(
            NAME steam_collection_integration
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/steam_collection_integration.py
                $<TARGET_FILE:game_price_tracker>
                ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tools/run_steam_pipeline.py
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/steam_appdetails_413150.json
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/game_catalog.json
        )
        add_test(
            NAME mobile_price_collection_e2e
            COMMAND ${Python3_EXECUTABLE}
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/mobile_price_collection_e2e.py
                $<TARGET_FILE:game_price_tracker>
        )
    endif()
    if(TARGET game_price_api AND UNIX)
        find_program(CURL_EXECUTABLE curl)
        if(CURL_EXECUTABLE)
            add_test(
                NAME game_price_api_integration
                COMMAND bash
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/game_price_api_integration.sh
                    $<TARGET_FILE:game_price_api>
                    $<TARGET_FILE:game_price_tracker>
                    ${CURL_EXECUTABLE}
            )
            set_tests_properties(game_price_api_integration PROPERTIES TIMEOUT 15)
            add_test(
                NAME user_price_alert_e2e
                COMMAND bash
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/user_price_alert_e2e.sh
                    $<TARGET_FILE:game_price_api>
                    $<TARGET_FILE:game_price_tracker>
                    ${CURL_EXECUTABLE}
            )
            set_tests_properties(user_price_alert_e2e PROPERTIES TIMEOUT 15)
            add_test(
                NAME data_reliability_e2e
                COMMAND bash
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/data_reliability_e2e.sh
                    $<TARGET_FILE:game_price_api>
                    $<TARGET_FILE:game_price_tracker>
                    ${CURL_EXECUTABLE}
            )
            set_tests_properties(data_reliability_e2e PROPERTIES TIMEOUT 15)
        endif()
    endif()
endif()
