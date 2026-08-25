#include "game_price/app/command_line.h"
#include "game_price/app/game_query_service.h"
#include "game_price/collection/apple_app_store_provider.h"
#include "game_price/collection/collection_service.h"
#include "game_price/persistence/database.h"
#include "game_price/catalog/game_catalog.h"
#include "game_price/collection/google_play_provider.h"
#include "game_price/pricing/price_comparison_service.h"
#include "game_price/pricing/price_history_service.h"
#include "game_price/recommendation/purchase_recommendation_service.h"
#include "game_price/support/date_utils.h"
#include "game_price/collection/steam_provider.h"
#include "game_price/persistence/store_product_repository.h"

#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace game_price;

void expect(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

StoreProduct makeSteamProduct(std::int64_t price) {
    return StoreProduct{
        "413150",
        "stardew-valley",
        Store::Steam,
        {Platform::Windows, Platform::MacOS, Platform::Linux},
        Money{price, Currency::KRW},
        true};
}

class StaticTestProvider final : public StoreProductProvider {
public:
    Store store() const noexcept override { return Store::Steam; }

    std::vector<StoreProduct> findProducts(const std::string&) const override {
        return {makeSteamProduct(11200)};
    }
};

class FailingTestProvider final : public StoreProductProvider {
public:
    Store store() const noexcept override { return Store::GooglePlay; }

    std::vector<StoreProduct> findProducts(const std::string&) const override {
        throw std::runtime_error("simulated collection failure");
    }
};

class FlakyTestProvider final : public StoreProductProvider {
public:
    Store store() const noexcept override { return Store::AppleAppStore; }

    std::vector<StoreProduct> findProducts(const std::string& gameId) const override {
        ++attempts_;
        if (attempts_ == 1) {
            throw std::runtime_error("temporary failure");
        }
        return {StoreProduct{
            "retry-product", gameId, Store::AppleAppStore, {Platform::IOS},
            Money{6600, Currency::KRW}, true}};
    }

private:
    mutable std::size_t attempts_{};
};

void testProviderNormalization() {
    const std::string dataDirectory = TEST_SAMPLE_DATA_DIR;
    SteamProvider steam(dataDirectory + "/steam_products.txt");
    GooglePlayProvider googlePlay(dataDirectory + "/google_play_products.txt");
    AppleAppStoreProvider apple(dataDirectory + "/apple_app_store_products.csv");

    const auto steamProducts = steam.findProducts("stardew-valley");
    expect(steamProducts.size() == 1, "Steam should return one product");
    expect(steamProducts.front().currentPrice.minorAmount == 11200,
           "Steam price should normalize to 11200 KRW");
    expect(steamProducts.front().supportedPlatforms.size() == 3,
           "Steam should normalize three platforms");

    const auto googleProducts = googlePlay.findProducts("stardew-valley");
    expect(googleProducts.size() == 1, "Google Play should return one product");
    expect(googleProducts.front().currentPrice.minorAmount == 6500,
           "Google Play micros should normalize to 6500 KRW");
    expect(googleProducts.front().supportedPlatforms == std::vector<Platform>{Platform::Android},
           "Google Play should support Android");

    const auto appleProducts = apple.findProducts("stardew-valley");
    expect(appleProducts.size() == 1, "Apple should return one product");
    expect(appleProducts.front().currentPrice.minorAmount == 6600,
           "Apple price should normalize to 6600 KRW");
    expect(appleProducts.front().supportedPlatforms.size() == 2,
           "Apple should normalize iOS and iPadOS");
}

void testHistoryDeduplicationAndAnalysis() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();

    const Game game{"stardew-valley", "Stardew Valley", "stardew valley"};
    auto product = makeSteamProduct(17500);
    repository.saveNormalizedProducts(game, {product});
    repository.saveNormalizedProducts(game, {product});
    expect(repository.findPriceHistory(Store::Steam, "413150").size() == 1,
           "Unchanged imports must not duplicate price history");

    product.currentPrice.minorAmount = 11200;
    repository.saveNormalizedProducts(game, {product});
    const auto history = repository.findPriceHistory(Store::Steam, "413150");
    expect(history.size() == 2, "A price change must append one history row");

    PriceHistoryService historyService(repository);
    const auto summary = historyService.analyze(product);
    expect(summary.has_value(), "Price history summary should exist");
    expect(summary->currentPrice.minorAmount == 11200, "Current price should be 11200");
    expect(summary->lowestPrice.minorAmount == 11200, "Lowest price should be 11200");
    expect(summary->highestPrice.minorAmount == 17500, "Highest price should be 17500");
    expect(summary->averagePrice.minorAmount == 14350, "Average price should be 14350");
    expect(summary->trend == PriceTrend::Falling, "Price trend should be falling");

    expect(!historyService.analyze(product, "9999-01-01").has_value(),
           "A future history boundary should return no summary");

    const std::vector<PriceObservation> replacement{
        {Money{15000, Currency::KRW}, true, "2026-01-01T00:00:00.000Z"},
        {Money{15000, Currency::KRW}, true, "2026-02-01T00:00:00.000Z"},
        {Money{11200, Currency::KRW}, true, "2026-03-01T00:00:00.000Z"}};
    repository.replacePriceHistory(Store::Steam, "413150", replacement);
    repository.replacePriceHistory(Store::Steam, "413150", replacement);
    const auto replacedHistory = repository.findPriceHistory(Store::Steam, "413150");
    expect(replacedHistory.size() == 2,
           "Replacement should skip unchanged prices and remain idempotent");
    expect(replacedHistory.front().observedAt == "2026-01-01T00:00:00.000Z",
           "Replacement history should preserve explicit observation dates");
    expect(replacedHistory.back().observedAt == "2026-03-01T00:00:00.000Z",
           "The next changed price should preserve its observation date");
}

void testDatabaseSchemaVersion() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    expect(database.userVersion() == 0, "A new SQLite database should start at version 0");

    repository.initializeSchema();
    expect(database.userVersion() == StoreProductRepository::CurrentSchemaVersion,
           "Schema initialization should record the current version");
    repository.initializeSchema();
    expect(database.userVersion() == StoreProductRepository::CurrentSchemaVersion,
           "Schema initialization should be idempotent");

    Database futureDatabase(":memory:");
    futureDatabase.execute("PRAGMA user_version = 999;");
    StoreProductRepository futureRepository(futureDatabase);
    bool rejectedFutureSchema = false;
    try {
        futureRepository.initializeSchema();
    } catch (const std::runtime_error&) {
        rejectedFutureSchema = true;
    }
    expect(rejectedFutureSchema, "A newer unsupported schema should be rejected");
}

void testPriceComparisonReadsRepository() {
    const std::string dataDirectory = TEST_SAMPLE_DATA_DIR;
    GameCatalog catalog(dataDirectory + "/games.txt");
    const auto game = catalog.findByName("  STARDEW   VALLEY  ");
    expect(game.has_value(), "GameCatalog should normalize lookup names");

    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    repository.saveNormalizedProducts(*game, {
        makeSteamProduct(11200),
        StoreProduct{"mobile", game->id, Store::GooglePlay, {Platform::Android},
                     Money{6500, Currency::KRW}, true}});

    PriceComparisonService service(catalog, repository);
    const auto result = service.compareByGameName("Stardew Valley");
    expect(result.has_value(), "Comparison result should exist");
    expect(result->products.size() == 2, "Comparison should read two DB products");
    expect(result->cheapestProduct.has_value(), "Cheapest product should exist");
    expect(result->cheapestProduct->store == Store::GooglePlay,
           "Google Play should be the cheapest DB product");
}

void testGameCatalogSearch() {
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/games.txt");
    const auto matches = catalog.searchByName("  VALLEY ");
    expect(matches.size() == 1, "Partial normalized title should find one game");
    expect(matches.front().id == "stardew-valley", "Search should return Stardew Valley");
    expect(catalog.searchByName("missing").empty(),
           "Unknown partial title should return no games");
    expect(catalog.searchByName("   ").empty(), "Empty search should return no games");
    expect(catalog.findById("stardew-valley").has_value(),
           "Catalog should find a game by stable id");
    expect(!catalog.findById("missing").has_value(),
           "Catalog should reject an unknown game id");
    expect(catalog.allGames().size() == 1,
           "Catalog should expose all games for batch collection");
    expect(catalog.allGames().front().id == "stardew-valley",
           "Batch catalog should preserve canonical game ids");
}

void testGameQueryServiceReport() {
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/games.txt");
    const auto game = catalog.findByName("Stardew Valley");
    expect(game.has_value(), "Test game should exist");
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    repository.saveNormalizedProducts(*game, {makeSteamProduct(11200)});

    GameQueryService service(catalog, repository);
    const auto report = service.getGamePriceReport("Stardew Valley");
    expect(report.has_value(), "Query service should return a game report");
    expect(report->comparison.cheapestProduct.has_value(),
           "Game report should contain the cheapest product");
    expect(report->productReports.size() == 1,
           "Game report should contain one product analysis");
    expect(report->productReports.front().history.has_value(),
           "Product report should contain price history");
    expect(report->productReports.front().recommendation.has_value(),
           "Product report should contain a recommendation");
    expect(service.searchGames("valley").size() == 1,
           "Query service should expose catalog search");
    expect(service.getGamePriceReportById("stardew-valley").has_value(),
           "Query service should return a report by stable game id");
    const auto history = service.getGamePriceHistoryById("stardew-valley");
    expect(history.has_value(), "Query service should return raw history by game id");
    expect(history->productHistories.size() == 1,
           "Raw history should contain one product");
    expect(history->productHistories.front().observations.size() == 1,
           "Raw history should contain one observation");
}

void testIsoDateValidation() {
    expect(isIsoDate("2024-02-29"), "Leap day should be valid in a leap year");
    expect(!isIsoDate("2023-02-29"), "Leap day should be invalid in a common year");
    expect(!isIsoDate("2026-04-31"), "A day outside the month should be invalid");
    expect(!isIsoDate("not-a-date"), "Non-date text should be invalid");
}

void testRecommendationRules() {
    PurchaseRecommendationService service;
    const PriceHistorySummary insufficient{
        Store::Steam, "413150", Money{11200, Currency::KRW},
        Money{11200, Currency::KRW}, Money{11200, Currency::KRW},
        Money{11200, Currency::KRW}, 1, PriceTrend::InsufficientData};
    expect(service.recommend(insufficient).recommendation ==
               PurchaseRecommendation::InsufficientData,
           "One observation should be insufficient");

    const PriceHistorySummary strongBuy{
        Store::Steam, "413150", Money{11200, Currency::KRW},
        Money{11200, Currency::KRW}, Money{17500, Currency::KRW},
        Money{13300, Currency::KRW}, 3, PriceTrend::Falling};
    const auto strongBuyResult = service.recommend(strongBuy);
    expect(strongBuyResult.recommendation == PurchaseRecommendation::StrongBuy,
           "Historical low after a fall should be a strong buy");
    expect(strongBuyResult.amountAboveHistoricalLow == 0,
           "Historical low should have no price difference");
    expect(strongBuyResult.percentComparedToAverage == -15,
           "Recommendation should expose percent below average");
    expect(strongBuyResult.priceRangePositionPercent == std::optional<int>{0},
           "Historical low should be at the bottom of its range");

    const PriceHistorySummary wait{
        Store::Steam, "413150", Money{17000, Currency::KRW},
        Money{10000, Currency::KRW}, Money{18000, Currency::KRW},
        Money{14000, Currency::KRW}, 4, PriceTrend::Rising};
    const auto waitResult = service.recommend(wait);
    expect(waitResult.recommendation == PurchaseRecommendation::Wait,
           "A rising above-average price should recommend waiting");
    expect(waitResult.amountAboveHistoricalLow == 7000,
           "Recommendation should expose amount above historical low");
    expect(waitResult.percentAboveHistoricalLow == 70,
           "Recommendation should expose percent above historical low");
    expect(waitResult.priceRangePositionPercent == std::optional<int>{87},
           "Recommendation should expose position within historical range");
}

void testCollectionRunTrackingAndFailureIsolation() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();

    StaticTestProvider successfulProvider;
    FailingTestProvider failingProvider;
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{
        successfulProvider, failingProvider};
    CollectionService service(repository, std::move(providers));

    const Game game{"stardew-valley", "Stardew Valley", "stardew valley"};
    const auto result = service.collect(game);
    expect(result.runs.size() == 2, "Both Store collection runs should be reported");
    expect(result.totalProducts == 1, "Successful Store product should still be saved");
    expect(result.runs[0].status == CrawlRunStatus::Succeeded,
           "First collection run should succeed");
    expect(result.runs[1].status == CrawlRunStatus::Failed,
           "Second collection run should fail without stopping the first");

    const auto persistedRuns = repository.findCrawlRuns();
    expect(persistedRuns.size() == 2, "Both crawl runs should be persisted");
    expect(persistedRuns[0].productsFound == 1,
           "Successful crawl run should record its product count");
    expect(persistedRuns[1].errorMessage == "simulated collection failure",
           "Failed crawl run should persist its error message");
    expect(repository.findProductsByGameId(game.id).size() == 1,
           "A failed Store must not roll back another Store's products");
}

void testCollectionRetryAfterTemporaryFailure() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();

    FlakyTestProvider provider;
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{provider};
    CollectionService service(repository, std::move(providers), 2);

    const Game game{"stardew-valley", "Stardew Valley", "stardew valley"};
    const auto result = service.collect(game);
    expect(result.runs.size() == 2, "A temporary failure should produce two attempts");
    expect(result.runs[0].status == CrawlRunStatus::Failed,
           "First collection attempt should fail");
    expect(result.runs[0].attemptNumber == 1, "First attempt number should be 1");
    expect(result.runs[1].status == CrawlRunStatus::Succeeded,
           "Second collection attempt should succeed");
    expect(result.runs[1].attemptNumber == 2, "Second attempt number should be 2");
    expect(result.totalProducts == 1, "Successful retry should save one product");

    const auto persistedRuns = repository.findCrawlRuns();
    expect(persistedRuns.size() == 2, "Both retry attempts should be persisted");
    expect(persistedRuns[0].status == CrawlRunStatus::Failed,
           "Failed retry attempt should remain in crawl history");
    expect(persistedRuns[1].status == CrawlRunStatus::Succeeded,
           "Successful retry attempt should be persisted");
}

void testCommandLineModes() {
    expect(static_cast<int>(AppExitCode::Success) == 0,
           "Success exit code should be zero");
    expect(static_cast<int>(AppExitCode::UsageError) == 2,
           "Usage errors should have a distinct exit code");
    expect(static_cast<int>(AppExitCode::CollectionFailed) == 5,
           "Collection failures should have a distinct exit code");

    const auto defaults = parseCommandLine({});
    expect(defaults.command == AppCommand::Demo, "No arguments should select demo mode");
    expect(defaults.gameName == "Stardew Valley", "Default game should be Stardew Valley");

    const auto collect = parseCommandLine({"collect", "Stardew", "Valley"});
    expect(collect.command == AppCommand::Collect, "collect should select collection mode");
    expect(collect.gameName == "Stardew Valley", "Unquoted game words should be joined");
    const auto snapshotCollect = parseCommandLine(
        {"collect", "--data-dir", "/tmp/store snapshot", "Stardew", "Valley"});
    expect(snapshotCollect.dataDirectory ==
               std::optional<std::string>{"/tmp/store snapshot"},
           "collect should parse a snapshot data directory");
    expect(snapshotCollect.gameName == "Stardew Valley",
           "collect should parse the game after the data directory");
    const auto steamCollect = parseCommandLine(
        {"collect-steam", "--data-dir", "/tmp/steam snapshot", "Stardew", "Valley"});
    expect(steamCollect.command == AppCommand::CollectSteam,
           "collect-steam should select Steam-only collection mode");
    expect(steamCollect.dataDirectory ==
               std::optional<std::string>{"/tmp/steam snapshot"},
           "collect-steam should parse its snapshot directory");
    expect(steamCollect.gameName == "Stardew Valley",
           "collect-steam should parse its game name");
    const auto allSteamCollect = parseCommandLine(
        {"collect-steam-all", "--data-dir", "/tmp/steam snapshot"});
    expect(allSteamCollect.command == AppCommand::CollectSteamAll,
           "collect-steam-all should select catalog collection mode");
    expect(allSteamCollect.dataDirectory ==
               std::optional<std::string>{"/tmp/steam snapshot"},
           "collect-steam-all should parse its snapshot directory");

    expect(parseCommandLine({"compare"}).command == AppCommand::Compare,
           "compare should select comparison mode");
    expect(parseCommandLine({"history"}).command == AppCommand::History,
           "history should select history mode");
    const auto historySince = parseCommandLine(
        {"history", "--since", "2026-01-01", "Stardew", "Valley"});
    expect(historySince.historySince == std::optional<std::string>{"2026-01-01"},
           "history should parse the since boundary");
    expect(historySince.gameName == "Stardew Valley",
           "history should parse the game name after the since boundary");
    bool rejectedInvalidDate = false;
    try {
        parseCommandLine({"history", "--since", "not-a-date"});
    } catch (const std::invalid_argument&) {
        rejectedInvalidDate = true;
    }
    expect(rejectedInvalidDate, "history should reject an invalid since date");
    bool rejectedMissingDataDirectory = false;
    try {
        parseCommandLine({"collect", "--data-dir"});
    } catch (const std::invalid_argument&) {
        rejectedMissingDataDirectory = true;
    }
    expect(rejectedMissingDataDirectory,
           "collect should reject a missing snapshot data directory");
    bool rejectedMissingSteamDataDirectory = false;
    try {
        parseCommandLine({"collect-steam"});
    } catch (const std::invalid_argument&) {
        rejectedMissingSteamDataDirectory = true;
    }
    expect(rejectedMissingSteamDataDirectory,
           "collect-steam should require a snapshot data directory");
    bool rejectedMissingAllSteamDataDirectory = false;
    try {
        parseCommandLine({"collect-steam-all"});
    } catch (const std::invalid_argument&) {
        rejectedMissingAllSteamDataDirectory = true;
    }
    expect(rejectedMissingAllSteamDataDirectory,
           "collect-steam-all should require a snapshot data directory");
    const auto runs = parseCommandLine({"runs"});
    expect(runs.command == AppCommand::CollectionRuns,
           "runs should select collection run history mode");
    expect(runs.gameName.empty(), "runs should not require a game name");
    const auto search = parseCommandLine({"search", "star", "dew"});
    expect(search.command == AppCommand::Search, "search should select catalog search mode");
    expect(search.gameName == "star dew", "search query words should be joined");
    const auto seedDemo = parseCommandLine({"seed-demo"});
    expect(seedDemo.command == AppCommand::SeedDemo,
           "seed-demo should select deterministic Demo seeding mode");
    expect(seedDemo.gameName == "Stardew Valley",
           "seed-demo should use the default game name");
    expect(parseCommandLine({"--help"}).command == AppCommand::Help,
           "--help should select help mode");

    bool rejectedUnknownCommand = false;
    try {
        parseCommandLine({"unknown"});
    } catch (const std::invalid_argument&) {
        rejectedUnknownCommand = true;
    }
    expect(rejectedUnknownCommand, "Unknown CLI commands should be rejected");
}

}  // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"Provider normalization", testProviderNormalization},
        {"History deduplication and analysis", testHistoryDeduplicationAndAnalysis},
        {"Database schema version", testDatabaseSchemaVersion},
        {"Repository-backed comparison", testPriceComparisonReadsRepository},
        {"Game catalog search", testGameCatalogSearch},
        {"Game query service report", testGameQueryServiceReport},
        {"ISO date validation", testIsoDateValidation},
        {"Recommendation rules", testRecommendationRules},
        {"Collection run tracking and failure isolation",
         testCollectionRunTrackingAndFailureIsolation},
        {"Collection retry after temporary failure",
         testCollectionRetryAfterTemporaryFailure},
        {"Command line modes", testCommandLineModes}};

    std::size_t passed = 0;
    for (const auto& test : tests) {
        try {
            test.second();
            std::cout << "[PASS] " << test.first << '\n';
            ++passed;
        } catch (const std::exception& error) {
            std::cerr << "[FAIL] " << test.first << ": " << error.what() << '\n';
        }
    }

    std::cout << passed << '/' << tests.size() << " tests passed\n";
    return passed == tests.size() ? 0 : 1;
}
