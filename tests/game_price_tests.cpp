#include "game_price/app/command_line.h"
#include "game_price/app/game_query_service.h"
#include "game_price/collection/apple_app_store_provider.h"
#include "game_price/collection/collection_service.h"
#include "game_price/collection/collection_error.h"
#include "game_price/collection/epic_games_provider.h"
#include "game_price/persistence/database.h"
#include "game_price/catalog/game_catalog.h"
#include "game_price/collection/google_play_provider.h"
#include "game_price/collection/nintendo_eshop_provider.h"
#include "game_price/pricing/price_comparison_service.h"
#include "game_price/pricing/price_history_service.h"
#include "game_price/recommendation/purchase_recommendation_service.h"
#include "game_price/support/date_utils.h"
#include "game_price/collection/steam_provider.h"
#include "game_price/persistence/store_product_repository.h"
#include "game_price/notification/account_repository.h"
#include "game_price/notification/alert_service.h"
#include "game_price/notification/auth_service.h"
#include "game_price/notification/oauth_service.h"

#include <cstdint>
#include <chrono>
#include <sqlite3.h>
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
        true,
        std::nullopt};
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
        throw PermanentCollectionError("simulated collection failure");
    }
};

class FlakyTestProvider final : public StoreProductProvider {
public:
    Store store() const noexcept override { return Store::AppleAppStore; }

    std::vector<StoreProduct> findProducts(const std::string& gameId) const override {
        ++attempts_;
        if (attempts_ <= 2) {
            throw TransientCollectionError("temporary failure");
        }
        return {StoreProduct{
            "1406710800", gameId, Store::AppleAppStore, {Platform::IOS},
            Money{6600, Currency::KRW}, true, std::nullopt}};
    }

private:
    mutable std::size_t attempts_{};
};

class ProductListTestProvider final : public StoreProductProvider {
public:
    explicit ProductListTestProvider(std::vector<StoreProduct> products)
        : products_(std::move(products)) {}

    Store store() const noexcept override { return Store::Steam; }
    std::vector<StoreProduct> findProducts(const std::string&) const override {
        return products_;
    }

private:
    std::vector<StoreProduct> products_;
};

void testProviderNormalization() {
    const std::string dataDirectory = TEST_SAMPLE_DATA_DIR;
    SteamProvider steam(dataDirectory + "/steam_products.txt");
    GooglePlayProvider googlePlay(dataDirectory + "/google_play_products.txt");
    AppleAppStoreProvider apple(dataDirectory + "/apple_app_store_products.csv");
    EpicGamesProvider epic(dataDirectory + "/epic_games_products.txt");
    NintendoEShopProvider nintendo(dataDirectory + "/nintendo_eshop_products.csv");

    const auto steamProducts = steam.findProducts("stardew-valley");
    expect(steamProducts.size() == 1, "Steam should return one product");
    expect(steamProducts.front().currentPrice.minorAmount == 11200,
           "Steam price should normalize to 11200 KRW");
    expect(steamProducts.front().supportedPlatforms.size() == 3,
           "Steam should normalize three platforms");
    expect(!steamProducts.front().observedAt.has_value(),
           "Legacy Steam sample rows should use repository import time");
    expect(steamProducts.front().region == Region::KR &&
               steamProducts.front().edition == GameEdition::Standard &&
               steamProducts.front().offerType == OfferType::BaseGame,
           "Providers should normalize the default comparison identity");

    SteamProvider discounted(
        std::string(TEST_SAMPLE_DATA_DIR) +
        "/../tests/fixtures/steam_products_discounted.txt");
    const auto discountedProducts = discounted.findProducts("stardew-valley");
    expect(discountedProducts.size() == 1,
           "Discounted Steam snapshot should return one product");
    expect(discountedProducts.front().currentPrice.minorAmount == 12000,
           "Steam final price should normalize as current price");
    expect(discountedProducts.front().regularPrice.has_value() &&
               discountedProducts.front().regularPrice->minorAmount == 16000,
           "Steam initial price should normalize as regular price");
    expect(discountedProducts.front().discountPercent == 25,
           "Steam discount percent should be preserved");
    expect(discountedProducts.front().observedAt ==
               std::optional<std::string>{"2026-08-26T09:30:45.123Z"},
           "Discounted snapshot should preserve collection time");

    const auto googleProducts = googlePlay.findProducts("stardew-valley");
    expect(googleProducts.size() == 1, "Google Play should return one product");
    expect(googleProducts.front().currentPrice.minorAmount == 6500,
           "Google Play micros should normalize to 6500 KRW");
    expect(googleProducts.front().supportedPlatforms == std::vector<Platform>{Platform::Android},
           "Google Play should support Android");
    GooglePlayProvider invalidGoogle(
        dataDirectory + "/../tests/fixtures/google_play_products_invalid.txt");
    expect(invalidGoogle.findProducts("stardew-valley").empty() &&
               invalidGoogle.findRejections("stardew-valley").size() == 1,
           "Google Play should isolate KRW micros that would lose precision");

    const auto appleProducts = apple.findProducts("stardew-valley");
    expect(appleProducts.size() == 1, "Apple should return one product");
    expect(appleProducts.front().currentPrice.minorAmount == 6600,
           "Apple price should normalize to 6600 KRW");
    expect(appleProducts.front().supportedPlatforms.size() == 2,
           "Apple should normalize iOS and iPadOS");
    AppleAppStoreProvider invalidApple(
        dataDirectory +
        "/../tests/fixtures/apple_app_store_products_invalid.csv");
    expect(invalidApple.findProducts("stardew-valley").empty() &&
               invalidApple.findRejections("stardew-valley").size() == 1,
           "Apple should isolate an invalid price row");

    SteamProvider invalidSteam(
        dataDirectory + "/../tests/fixtures/steam_products_invalid.txt");
    expect(invalidSteam.findProducts("stardew-valley").empty() &&
               invalidSteam.findRejections("stardew-valley").size() == 1,
           "Steam should isolate an invalid snapshot row");

    const auto epicProducts = epic.findProducts("hades");
    expect(epicProducts.size() == 1, "Epic should return one Hades product");
    expect(epicProducts.front().currentPrice.minorAmount == 25000,
           "Epic current price should normalize to KRW");
    expect(epicProducts.front().regularPrice->minorAmount == 27000 &&
               epicProducts.front().discountPercent == 7,
           "Epic should preserve regular price and discount");
    expect(epicProducts.front().supportedPlatforms ==
               std::vector<Platform>{Platform::Windows, Platform::MacOS},
           "Epic should normalize Windows and macOS");

    EpicGamesProvider invalidEpic(
        dataDirectory + "/../tests/fixtures/epic_games_products_invalid.txt");
    expect(invalidEpic.findProducts("hades").empty() &&
               invalidEpic.findRejections("hades").size() == 1,
           "Epic should isolate an invalid price block");

    const auto nintendoProducts = nintendo.findProducts("hades");
    expect(nintendoProducts.size() == 1,
           "Nintendo eShop should return one Hades product");
    expect(nintendoProducts.front().store == Store::NintendoEShop &&
               nintendoProducts.front().supportedPlatforms ==
                   std::vector<Platform>{Platform::NintendoSwitch},
           "Nintendo product should remain native to Nintendo Switch");
    expect(nintendoProducts.front().compatibility.size() == 1 &&
               nintendoProducts.front().compatibility.front().platform ==
                   Platform::NintendoSwitch2 &&
               nintendoProducts.front().compatibility.front().status ==
                   CompatibilityStatus::Compatible,
           "Nintendo Provider should normalize Switch 2 compatibility separately");
    NintendoEShopProvider invalidNintendo(
        dataDirectory + "/../tests/fixtures/nintendo_eshop_products_invalid.csv");
    expect(invalidNintendo.findProducts("hades").empty() &&
               invalidNintendo.findRejections("hades").size() == 1,
           "Nintendo Provider should isolate malformed identifiers and prices");
}

void testEpicEndToEndComparison() {
    const std::string dataDirectory = TEST_SAMPLE_DATA_DIR;
    GameCatalog catalog(dataDirectory + "/game_catalog.json");
    const auto game = catalog.findById("hades");
    expect(game.has_value(), "Catalog should contain Hades");

    SteamProvider steam(dataDirectory + "/steam_products.txt");
    EpicGamesProvider epic(dataDirectory + "/epic_games_products.txt");
    NintendoEShopProvider nintendo(dataDirectory + "/nintendo_eshop_products.csv");
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{
        steam, epic, nintendo};
    const auto collection = CollectionService(catalog, repository, providers, 1).collect(*game);
    expect(collection.totalProducts == 3,
           "Hades collection should save Steam, Epic, and Nintendo products");

    const auto comparison = PriceComparisonService(catalog, repository)
                                .compareByGameId("hades");
    expect(comparison.has_value() && comparison->products.size() == 3,
           "Hades should compare three Store products");
    expect(comparison->cheapestProduct->store == Store::EpicGamesStore &&
               comparison->cheapestProduct->currentPrice.minorAmount == 25000,
           "Epic should be the cheapest Hades Store");

    const auto report = GameQueryService(catalog, repository)
                            .getGamePriceReportById("hades");
    const auto epicReport = std::find_if(
        report->productReports.begin(), report->productReports.end(),
        [](const ProductPriceReport& product) {
            return product.product.store == Store::EpicGamesStore;
        });
    expect(epicReport != report->productReports.end() &&
               epicReport->purchaseUrl == "https://store.epicgames.com/p/hades",
           "API report should use the Epic catalog purchase URL");

    PriceComparisonCriteria switchCriteria;
    switchCriteria.platform = Platform::NintendoSwitch;
    const auto switchComparison = PriceComparisonService(catalog, repository)
                                      .compareByGameId("hades", switchCriteria);
    expect(switchComparison->products.size() == 1 &&
               switchComparison->cheapestProduct->store == Store::NintendoEShop,
           "Nintendo Switch criteria should find the native eShop product");

    PriceComparisonCriteria switch2Criteria;
    switch2Criteria.platform = Platform::NintendoSwitch2;
    const auto switch2Comparison = PriceComparisonService(catalog, repository)
                                       .compareByGameId("hades", switch2Criteria);
    expect(switch2Comparison->products.size() == 1 &&
               switch2Comparison->products.front().compatibility.front().status ==
                   CompatibilityStatus::Compatible,
           "Nintendo Switch 2 criteria should include a compatible Switch product");
}

void testProviderParsingPartialFailure() {
    const std::string dataDirectory = TEST_SAMPLE_DATA_DIR;
    GameCatalog catalog(dataDirectory + "/game_catalog.json");
    const auto game = catalog.findById("hades");
    expect(game.has_value(), "Catalog should contain Hades");
    EpicGamesProvider provider(
        dataDirectory + "/../tests/fixtures/epic_games_products_mixed.txt");
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{provider};
    const auto result = CollectionService(
        catalog, repository, providers).collect(*game);

    expect(result.totalProducts == 1 && result.runs.size() == 1 &&
               result.runs.front().status == CrawlRunStatus::Succeeded &&
               result.runs.front().productsRejected == 1,
           "A malformed source block must not block a valid block from the same Provider");
    const auto runs = repository.findCrawlRuns();
    const auto rejections = repository.findCollectionRejections(runs.front().id);
    expect(rejections.size() == 1 &&
               rejections.front().productId == "broken" &&
               rejections.front().reason.find("Epic") != std::string::npos,
           "A source parsing rejection must be linked to the collection quarantine");
    expect(repository.findProductsByGameId(game->id).size() == 1,
           "The valid source block must remain queryable after partial failure");
}

void testHistoryDeduplicationAndAnalysis() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();

    const Game game{"stardew-valley", "Stardew Valley", "stardew valley", {}};
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

void testPriceObservationIntegrity() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    const Game game{"stardew-valley", "Stardew Valley", "stardew valley", {}};

    auto product = makeSteamProduct(16000);
    product.observedAt = "2026-02-01T00:00:00.000Z";
    repository.saveNormalizedProducts(game, {product});
    repository.saveNormalizedProducts(game, {product});
    expect(repository.findPriceHistory(Store::Steam, "413150").size() == 1,
           "The same state at the same timestamp must be idempotent");

    auto conflicting = product;
    conflicting.currentPrice.minorAmount = 15000;
    bool rejectedConflict = false;
    try {
        repository.saveNormalizedProducts(game, {conflicting});
    } catch (const std::invalid_argument&) {
        rejectedConflict = true;
    }
    expect(rejectedConflict,
           "Different states at the same timestamp must conflict");

    auto outOfOrder = product;
    outOfOrder.observedAt = "2026-01-01T00:00:00.000Z";
    bool rejectedOutOfOrder = false;
    try {
        repository.saveNormalizedProducts(game, {outOfOrder});
    } catch (const std::invalid_argument&) {
        rejectedOutOfOrder = true;
    }
    expect(rejectedOutOfOrder,
           "An older observation must not overwrite the current product state");
    const auto current = repository.findProductsByGameId(game.id);
    expect(current.size() == 1 && current.front().currentPrice.minorAmount == 16000,
           "Rejected timestamp conflicts must preserve the current price");

    repository.replacePriceHistory(Store::Steam, "413150", {
        {Money{100, Currency::KRW}, false, "2026-01-01T00:00:00.000Z"},
        {Money{1000, Currency::KRW}, true, "2026-02-01T00:00:00.000Z"},
        {Money{800, Currency::KRW}, true, "2026-03-01T00:00:00.000Z"}});
    const auto summary = PriceHistoryService(repository).analyze(product);
    expect(summary && summary->lowestPrice.minorAmount == 800 &&
               summary->highestPrice.minorAmount == 1000 &&
               summary->observationCount == 2,
           "Historical statistics must exclude unavailable observations");

    bool rejectedReplacementConflict = false;
    try {
        repository.replacePriceHistory(Store::Steam, "413150", {
            {Money{1000, Currency::KRW}, true, "2026-04-01T00:00:00.000Z"},
            {Money{900, Currency::KRW}, true, "2026-04-01T00:00:00.000Z"}});
    } catch (const std::invalid_argument&) {
        rejectedReplacementConflict = true;
    }
    expect(rejectedReplacementConflict &&
               repository.findPriceHistory(Store::Steam, "413150").size() == 3,
           "A conflicting replacement must roll back and preserve existing history");
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

    Database versionOneDatabase(":memory:");
    versionOneDatabase.execute(R"sql(
        CREATE TABLE store_products (
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL,
            PRIMARY KEY (store, external_product_id)
        );
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL,
            observed_at TEXT NOT NULL
        );
        INSERT INTO store_products VALUES(
            'Steam', '413150', 'stardew-valley', 16000, 'KRW', 1);
        INSERT INTO price_history(
            store, external_product_id, price_minor,
            currency, purchasable, observed_at)
        VALUES('Steam', '413150', 16000, 'KRW', 1,
               '2026-08-01T00:00:00.000Z');
        PRAGMA user_version = 1;
    )sql");
    StoreProductRepository versionOneRepository(versionOneDatabase);
    versionOneRepository.initializeSchema();
    expect(versionOneDatabase.userVersion() == 11,
           "Schema version 1 should migrate to version 11");
    const auto migratedProducts =
        versionOneRepository.findProductsByGameId("stardew-valley");
    expect(migratedProducts.size() == 1,
           "Version 1 migration should preserve current products");
    expect(!migratedProducts.front().regularPrice.has_value() &&
               migratedProducts.front().discountPercent == 0,
           "Legacy products should migrate with unknown regular price and no discount");
    expect(migratedProducts.front().region == Region::KR &&
               migratedProducts.front().edition == GameEdition::Standard &&
               migratedProducts.front().offerType == OfferType::BaseGame,
           "Legacy products should migrate to the default comparison identity");
    expect(migratedProducts.front().lastCheckedAt ==
               std::optional<std::string>{"2026-08-01T00:00:00.000Z"} &&
               migratedProducts.front().lastSuccessfulCheckAt ==
                   std::optional<std::string>{"2026-08-01T00:00:00.000Z"},
           "Legacy products should derive check timestamps from their latest history");
    const auto migratedHistory =
        versionOneRepository.findPriceHistory(Store::Steam, "413150");
    expect(migratedHistory.size() == 1,
           "Version 1 migration should preserve price history");
    expect(!migratedHistory.front().regularPrice.has_value() &&
               migratedHistory.front().discountPercent == 0,
           "Legacy history should migrate without inventing a regular price");

    Database versionTwoDatabase(":memory:");
    versionTwoDatabase.execute(R"sql(
        CREATE TABLE store_products (
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            regular_price_minor INTEGER,
            discount_percent INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL,
            PRIMARY KEY (store, external_product_id)
        );
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            regular_price_minor INTEGER,
            discount_percent INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL,
            observed_at TEXT NOT NULL
        );
        INSERT INTO store_products VALUES(
            'Epic Games Store', 'hades', 'hades', 25000, 27000, 7, 'KRW', 1);
        PRAGMA user_version = 2;
    )sql");
    StoreProductRepository versionTwoRepository(versionTwoDatabase);
    versionTwoRepository.initializeSchema();
    expect(versionTwoDatabase.userVersion() == 11,
           "Schema version 2 should migrate to version 11");
    const auto versionTwoProducts = versionTwoRepository.findProductsByGameId("hades");
    expect(versionTwoProducts.size() == 1 &&
               versionTwoProducts.front().region == Region::KR &&
               versionTwoProducts.front().edition == GameEdition::Standard &&
               versionTwoProducts.front().offerType == OfferType::BaseGame,
           "Version 2 products should preserve data with default comparison identity");

    Database versionEightDatabase(":memory:");
    versionEightDatabase.execute(R"sql(
        CREATE TABLE crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCEEDED','FAILED')),
            products_found INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO crawl_runs(
            store, started_at, finished_at, status, products_found, error_message)
        VALUES('Steam', '2026-08-01T00:00:00.000Z',
               '2026-08-01T00:00:01.000Z', 'SUCCEEDED', 3, '');
        PRAGMA user_version = 8;
    )sql");
    StoreProductRepository versionEightRepository(versionEightDatabase);
    versionEightRepository.initializeSchema();
    const auto migratedRuns = versionEightRepository.findCrawlRuns();
    expect(versionEightDatabase.userVersion() == 11 && migratedRuns.size() == 1 &&
               migratedRuns.front().productsFound == 3 &&
               migratedRuns.front().productsRejected == 0 &&
               migratedRuns.front().productsFailed == 0 &&
               migratedRuns.front().retryCount == 0,
           "Version 8 migration should preserve runs and initialize reliability counters");

    Database versionNineDatabase(":memory:");
    versionNineDatabase.execute(R"sql(
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            regular_price_minor INTEGER,
            discount_percent INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL,
            observed_at TEXT NOT NULL
        );
        CREATE TABLE crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            products_found INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT '',
            products_rejected INTEGER NOT NULL DEFAULT 0,
            products_failed INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO price_history(
            store, external_product_id, price_minor, currency,
            purchasable, observed_at)
        VALUES
            ('Steam','413150',16000,'KRW',1,'2026-01-01T00:00:00.000Z'),
            ('Steam','413150',12000,'KRW',1,'2026-01-01T00:00:00.000Z');
        PRAGMA user_version = 9;
    )sql");
    StoreProductRepository versionNineRepository(versionNineDatabase);
    versionNineRepository.initializeSchema();
    const auto deduplicated = versionNineRepository.findPriceHistory(
        Store::Steam, "413150");
    sqlite3_stmt* conflictCountStatement = nullptr;
    sqlite3_prepare_v2(
        versionNineDatabase.handle(),
        "SELECT COUNT(*) FROM price_history_conflicts;", -1,
        &conflictCountStatement, nullptr);
    sqlite3_step(conflictCountStatement);
    const int conflictCount = sqlite3_column_int(conflictCountStatement, 0);
    sqlite3_finalize(conflictCountStatement);
    expect(versionNineDatabase.userVersion() == 11 &&
               deduplicated.size() == 1 &&
               deduplicated.front().price.minorAmount == 12000 &&
               conflictCount == 1,
           "Version 9 migration should retain the latest duplicate and quarantine the other");
}

void testDiscountChangeHistory() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    const Game game{"stardew-valley", "Stardew Valley", "stardew valley", {}};

    auto product = makeSteamProduct(16000);
    product.regularPrice = Money{16000, Currency::KRW};
    product.observedAt = "2026-08-01T00:00:00.000Z";
    repository.saveNormalizedProducts(game, {product});

    product.currentPrice.minorAmount = 12000;
    product.discountPercent = 25;
    product.observedAt = "2026-08-02T00:00:00.000Z";
    repository.saveNormalizedProducts(game, {product});

    product.regularPrice = Money{17000, Currency::KRW};
    product.discountPercent = 29;
    product.observedAt = "2026-08-03T00:00:00.000Z";
    repository.saveNormalizedProducts(game, {product});
    repository.saveNormalizedProducts(game, {product});

    product.currentPrice.minorAmount = 17000;
    product.discountPercent = 0;
    product.observedAt = "2026-08-04T00:00:00.000Z";
    repository.saveNormalizedProducts(game, {product});

    const auto history = repository.findPriceHistory(Store::Steam, "413150");
    expect(history.size() == 4,
           "Discount start, metadata change, and end should create observations");
    expect(history[1].regularPrice && history[1].regularPrice->minorAmount == 16000 &&
               history[1].discountPercent == 25,
           "Discount start should preserve regular price and percent");
    expect(history[2].price.minorAmount == 12000 &&
               history[2].regularPrice &&
               history[2].regularPrice->minorAmount == 17000 &&
               history[2].discountPercent == 29,
           "Regular price change should be stored even when current price is unchanged");
    expect(history[3].price.minorAmount == 17000 &&
               history[3].discountPercent == 0,
           "Discount end should create a full-price observation");

    product.regularPrice = std::nullopt;
    product.discountPercent = 10;
    product.observedAt = "2026-08-05T00:00:00.000Z";
    bool rejectedInvalidDiscount = false;
    try {
        repository.saveNormalizedProducts(game, {product});
    } catch (const std::invalid_argument&) {
        rejectedInvalidDiscount = true;
    }
    expect(rejectedInvalidDiscount,
           "A discount without a regular price should be rejected");
    expect(repository.findPriceHistory(Store::Steam, "413150").size() == 4,
           "Invalid discount import should roll back without adding history");
}

void testStoreProductPriceValidation() {
    const Game game{"stardew-valley", "Stardew Valley", "stardew valley", {}};
    const auto isRejected = [&](StoreProduct product) {
        Database database(":memory:");
        StoreProductRepository repository(database);
        repository.initializeSchema();
        try {
            repository.saveNormalizedProducts(game, {std::move(product)});
        } catch (const std::invalid_argument&) {
            return true;
        }
        return false;
    };

    auto negative = makeSteamProduct(-1);
    expect(isRejected(negative), "Negative prices must be rejected");

    auto excessive = makeSteamProduct(100'000'001);
    expect(isRejected(excessive), "Excessive prices must be rejected");

    auto wrongCurrency = makeSteamProduct(11200);
    wrongCurrency.currentPrice.currency = static_cast<Currency>(999);
    expect(isRejected(wrongCurrency), "Unsupported currencies must be rejected");

    auto aboveRegular = makeSteamProduct(17000);
    aboveRegular.regularPrice = Money{16000, Currency::KRW};
    expect(isRejected(aboveRegular),
           "A current price above its regular price must be rejected");

    auto inconsistentDiscount = makeSteamProduct(12000);
    inconsistentDiscount.regularPrice = Money{16000, Currency::KRW};
    inconsistentDiscount.discountPercent = 10;
    expect(isRejected(inconsistentDiscount),
           "Discount percentage must agree with the actual price reduction");

    auto noPlatforms = makeSteamProduct(11200);
    noPlatforms.supportedPlatforms.clear();
    expect(isRejected(noPlatforms),
           "A product without a supported platform must be rejected");

    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    auto freeProduct = makeSteamProduct(0);
    freeProduct.regularPrice = Money{0, Currency::KRW};
    repository.saveNormalizedProducts(game, {freeProduct});
    const auto stored = repository.findProductsByGameId(game.id);
    expect(stored.size() == 1 && stored.front().currentPrice.minorAmount == 0 &&
               stored.front().purchasable,
           "An explicit purchasable zero price must remain a valid free offer");
}

void testPriceComparisonReadsRepository() {
    const std::string dataDirectory = TEST_SAMPLE_DATA_DIR;
    GameCatalog catalog(dataDirectory + "/game_catalog.json");
    const auto game = catalog.findByName("  STARDEW   VALLEY  ");
    expect(game.has_value(), "GameCatalog should normalize lookup names");

    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    repository.saveNormalizedProducts(*game, {
        makeSteamProduct(11200),
        StoreProduct{"mobile", game->id, Store::GooglePlay, {Platform::Android},
                     Money{6500, Currency::KRW}, true, std::nullopt},
        StoreProduct{"cheap-dlc", game->id, Store::EpicGamesStore,
                     {Platform::Windows}, Money{1000, Currency::KRW}, true,
                     std::nullopt, std::nullopt, 0, Region::KR,
                     GameEdition::Standard, OfferType::DLC}});

    PriceComparisonService service(catalog, repository);
    const auto result = service.compareByGameName("Stardew Valley");
    expect(result.has_value(), "Comparison result should exist");
    expect(result->products.size() == 2,
           "Default comparison should expose only comparable BaseGame products");
    expect(result->cheapestProduct.has_value(), "Cheapest product should exist");
    expect(result->cheapestProduct->store == Store::GooglePlay,
           "A cheaper DLC must not replace the cheapest Standard BaseGame");

    PriceComparisonCriteria windowsCriteria;
    windowsCriteria.platform = Platform::Windows;
    const auto windows = service.compareByGameName("Stardew Valley", windowsCriteria);
    expect(windows->products.size() == 1 &&
               windows->cheapestProduct->store == Store::Steam,
           "Windows criteria should only compare Windows Store products");

    PriceComparisonCriteria androidCriteria;
    androidCriteria.platform = Platform::Android;
    const auto android = service.compareByGameName("Stardew Valley", androidCriteria);
    expect(android->products.size() == 1 &&
               android->cheapestProduct->store == Store::GooglePlay,
           "Android criteria should only compare Android Store products");

    PriceComparisonCriteria deluxeCriteria;
    deluxeCriteria.edition = GameEdition::Deluxe;
    const auto deluxe = service.compareByGameName("Stardew Valley", deluxeCriteria);
    expect(deluxe->products.empty() && !deluxe->cheapestProduct,
           "A criteria group without products should return no cheapest offer");
}

void testStalePriceSafety() {
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/game_catalog.json");
    const auto game = catalog.findById("stardew-valley");
    expect(game.has_value(), "Catalog should contain Stardew Valley");
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();

    auto staleSteam = makeSteamProduct(1000);
    StoreProduct freshGoogle{
        "com.chucklefish.stardewvalley", game->id, Store::GooglePlay,
        {Platform::Android}, Money{6500, Currency::KRW}, true};
    repository.saveNormalizedProducts(*game, {staleSteam, freshGoogle});
    database.execute(R"sql(
        UPDATE store_products
        SET last_checked_at = '2000-01-01T00:00:00.000Z',
            last_successful_check_at = '2000-01-01T00:00:00.000Z'
        WHERE store = 'Steam' AND external_product_id = '413150';
    )sql");
    repository.recordProductCheckFailure(Store::Steam, "413150");

    const auto comparison = PriceComparisonService(catalog, repository)
                                .compareByGameId(game->id);
    expect(comparison && comparison->products.size() == 2 &&
               comparison->cheapestProduct &&
               comparison->cheapestProduct->store == Store::GooglePlay,
           "A stale cheaper product must not become the current cheapest offer");
    const auto staleProduct = std::find_if(
        comparison->products.begin(), comparison->products.end(),
        [](const StoreProduct& product) { return product.store == Store::Steam; });
    expect(staleProduct != comparison->products.end() &&
               staleProduct->freshness == PriceFreshness::Stale &&
               staleProduct->lastCheckedAt &&
               *staleProduct->lastCheckedAt != "2000-01-01T00:00:00.000Z" &&
               staleProduct->lastSuccessfulCheckAt ==
                   std::optional<std::string>{"2000-01-01T00:00:00.000Z"},
           "A failed check should update only lastCheckedAt and leave stale success time");

    const auto report = GameQueryService(catalog, repository)
                            .getGamePriceReportById(game->id);
    const auto staleReport = std::find_if(
        report->productReports.begin(), report->productReports.end(),
        [](const ProductPriceReport& product) {
            return product.product.store == Store::Steam;
        });
    expect(staleReport != report->productReports.end() &&
               staleReport->history.has_value() &&
               !staleReport->recommendation.has_value(),
           "Stale history may remain visible but must not produce a purchase recommendation");

    AccountRepository accounts(database);
    AuthService auth(accounts);
    AlertService alerts(accounts);
    const auto user = auth.registerUser(
        "stale-alert@example.com", "safe-password-123").user;
    accounts.addRule(
        user.id, game->id, AlertRuleType::BelowTargetPrice, 2000);
    expect(alerts.evaluateGame(game->id) == 0,
           "A stale price must not trigger a target price notification");
}

void testGameCatalogSearch() {
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/game_catalog.json");
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
    expect(catalog.allGames().size() == 4,
           "Catalog should expose all games for batch collection");
    expect(catalog.allGames().front().id == "stardew-valley",
           "Batch catalog should preserve canonical game ids");
    expect(catalog.findByName("Terraria").has_value(),
           "Catalog should contain the second Steam collection target");
    expect(catalog.findByName("Hollow Knight").has_value(),
           "Catalog should contain the newly added game");
    expect(catalog.findByName("Hollow Knight")->supportedPlatforms ==
               std::vector<Platform>{Platform::Windows, Platform::MacOS, Platform::Linux},
           "Game should expose catalog-level platform availability");
    expect(catalog.storeProducts(Store::Steam).size() == 4,
           "Catalog should expose every Steam product mapping");
    expect(catalog.storeProducts(Store::Steam).front().productUrl ==
               "https://store.steampowered.com/app/413150",
           "Catalog product should own its purchase URL");
    expect(catalog.storeProducts(Store::Steam).front().supportedPlatforms.size() == 3,
           "Catalog product should expose Store-specific platforms");
    expect(catalog.storeProducts(Store::GooglePlay).size() == 1,
           "Catalog should expose Store-specific product mappings");
    expect(catalog.storeProducts(Store::EpicGamesStore).size() == 1,
           "Catalog should expose the Epic product mapping");
    expect(catalog.storeProducts(Store::NintendoEShop).size() == 1 &&
               catalog.storeProducts(Store::NintendoEShop).front().compatibility.size() == 1,
           "Catalog should expose Nintendo eShop and Switch 2 compatibility");
    expect(catalog.storeProducts(Store::EpicGamesStore).front().region == Region::KR &&
               catalog.storeProducts(Store::EpicGamesStore).front().edition ==
                   GameEdition::Standard &&
               catalog.storeProducts(Store::EpicGamesStore).front().offerType ==
                   OfferType::BaseGame,
           "Catalog should preserve the product comparison identity");
}

void testGameCatalogValidation() {
    const std::string fixtures = std::string(TEST_SAMPLE_DATA_DIR) + "/../tests/fixtures/";
    for (const auto& filename : {"game_catalog_duplicate_id.json",
                                 "game_catalog_duplicate_steam_id.json",
                                 "game_catalog_missing_title.json",
                                 "game_catalog_invalid_platform.json",
                                 "game_catalog_invalid_store.json",
                                 "game_catalog_missing_offer_identity.json"}) {
        bool rejected = false;
        try {
            GameCatalog catalog(fixtures + filename);
        } catch (const std::runtime_error&) {
            rejected = true;
        }
        expect(rejected, std::string("Catalog should reject invalid fixture: ") + filename);
    }
}

void testGameQueryServiceReport() {
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/game_catalog.json");
    const auto game = catalog.findByName("Stardew Valley");
    expect(game.has_value(), "Test game should exist");
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    repository.saveNormalizedProducts(*game, {makeSteamProduct(11200)});

    GameQueryService service(catalog, repository);
    expect(service.listGames().size() == 4,
           "Query service should expose the full catalog");
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
    expect(isUtcTimestamp("2026-08-26T09:30:45.123Z"),
           "UTC timestamp with milliseconds should be valid");
    expect(!isUtcTimestamp("2026-08-26T24:00:00.000Z"),
           "UTC timestamp should reject hour 24");
    expect(!isUtcTimestamp("2026-08-26 09:30:45Z"),
           "UTC timestamp should require the snapshot format");
}

void testAuthenticationAndPriceAlerts() {
    Database database(":memory:");
    StoreProductRepository products(database); products.initializeSchema();
    AccountRepository accounts(database); AuthService auth(accounts); AlertService alerts(accounts);
    const auto registration = auth.registerUser("Buyer@Example.com", "safe-password-123");
    expect(registration.user.email == "buyer@example.com" && !registration.token.empty(),
           "Registration should normalize email and issue a session");
    sqlite3_stmt* storedSession=nullptr;
    expect(sqlite3_prepare_v2(database.handle(),"SELECT token FROM user_sessions LIMIT 1;",-1,&storedSession,nullptr)==SQLITE_OK &&
               sqlite3_step(storedSession)==SQLITE_ROW &&
               reinterpret_cast<const char*>(sqlite3_column_text(storedSession,0))!=registration.token,
           "Database must store only a hash of the bearer token");
    sqlite3_finalize(storedSession);
    expect(auth.authenticate(registration.token).has_value(), "Session should authenticate");
    expect(!auth.login("buyer@example.com", "wrong-password").has_value(),
           "Wrong password should be rejected");
    expect(auth.login("buyer@example.com", "safe-password-123").has_value(),
           "Correct password should create a session");
    for(int attempt=0;attempt<5;++attempt)accounts.recordLoginFailure("buyer@example.com","client-a");
    expect(accounts.isLoginRateLimited("buyer@example.com","client-a"),
           "Five recent failures should rate-limit the same account and client");
    accounts.clearLoginFailures("buyer@example.com","client-a");
    expect(!accounts.isLoginRateLimited("buyer@example.com","client-a"),
           "A successful login should clear its failure window");

    const Game game{"alert-game", "Alert Game", "alert game", {Platform::Windows}};
    auto product = StoreProduct{"alert-product", game.id, Store::Steam,
        {Platform::Windows}, Money{20000, Currency::KRW}, true,
        "2026-01-01T00:00:00.000Z"};
    products.saveNormalizedProducts(game, {product});
    accounts.addRule(registration.user.id, game.id, AlertRuleType::PriceDrop, std::nullopt);
    accounts.addRule(registration.user.id, game.id, AlertRuleType::NewHistoricalLow, std::nullopt);
    accounts.addRule(registration.user.id, game.id, AlertRuleType::BelowAverage, std::nullopt);
    accounts.addRule(registration.user.id, game.id, AlertRuleType::BelowTargetPrice, 16000);
    bool rejectedDuplicate=false;
    try{accounts.addRule(registration.user.id,game.id,AlertRuleType::BelowTargetPrice,16000);}
    catch(const std::invalid_argument&){rejectedDuplicate=true;}
    expect(rejectedDuplicate,"An identical alert rule should be rejected");
    product.currentPrice.minorAmount = 15000;
    product.observedAt = "2026-02-01T00:00:00.000Z";
    products.saveNormalizedProducts(game, {product});
    expect(alerts.evaluateGame(game.id) == 4,
           "A price drop should satisfy all four configured rule types");
    expect(alerts.evaluateGame(game.id) == 0, "Repeated evaluation must not duplicate alerts");
    auto notifications = accounts.findNotifications(registration.user.id);
    expect(notifications.size() == 4 && !notifications.front().read,
           "User should receive four unread notifications");
    accounts.markNotificationRead(registration.user.id, notifications.front().id);
    expect(accounts.findNotifications(registration.user.id).front().read,
           "Notification ownership-aware read update should persist");
    const auto rules = accounts.findRules(registration.user.id);
    accounts.deleteRule(registration.user.id, rules.front().id);
    expect(accounts.findRules(registration.user.id).size() == 3,
           "User should be able to remove an owned alert rule");
}

void expectOfferDoesNotTriggerDefaultPriceAlert(
    const std::string& productId,
    GameEdition edition,
    OfferType offerType) {
    Database database(":memory:");
    StoreProductRepository products(database);
    products.initializeSchema();
    AccountRepository accounts(database);
    AuthService auth(accounts);
    AlertService alerts(accounts);
    const auto user = auth.registerUser(
        "comparable-alert@example.com", "safe-password-123").user;
    const Game game{
        "non-comparable-alert-game",
        "Non-comparable Alert Game",
        "non comparable alert game",
        {Platform::Windows}};
    const StoreProduct product{
        productId,
        game.id,
        Store::Steam,
        {Platform::Windows},
        Money{100, Currency::KRW},
        true,
        "2026-01-01T00:00:00.000Z",
        std::nullopt,
        0,
        Region::KR,
        edition,
        offerType};
    products.saveNormalizedProducts(game, {product});
    accounts.addRule(
        user.id, game.id, AlertRuleType::BelowTargetPrice, 1000,
        Platform::Windows);

    expect(
        alerts.evaluateGame(game.id) == 0 &&
            accounts.findNotifications(user.id).empty(),
        productId + " must not trigger a default Standard BaseGame alert");
}

void testDlcDoesNotTriggerDefaultPriceAlert() {
    expectOfferDoesNotTriggerDefaultPriceAlert(
        "cheap-dlc",
        GameEdition::Standard,
        OfferType::DLC);
}

void testDeluxeDoesNotTriggerDefaultPriceAlert() {
    expectOfferDoesNotTriggerDefaultPriceAlert(
        "cheap-deluxe",
        GameEdition::Deluxe,
        OfferType::BaseGame);
}

void testBundleDoesNotTriggerDefaultPriceAlert() {
    expectOfferDoesNotTriggerDefaultPriceAlert(
        "cheap-bundle",
        GameEdition::Standard,
        OfferType::Bundle);
}

void testSubscriptionDoesNotTriggerDefaultPriceAlert() {
    expectOfferDoesNotTriggerDefaultPriceAlert(
        "cheap-subscription",
        GameEdition::Standard,
        OfferType::Subscription);
}

void testStandardBaseGameTriggersDefaultPriceAlert() {
    Database database(":memory:");
    StoreProductRepository products(database);
    products.initializeSchema();
    AccountRepository accounts(database);
    AuthService auth(accounts);
    AlertService alerts(accounts);
    const auto user = auth.registerUser(
        "standard-alert@example.com", "safe-password-123").user;
    const Game game{
        "standard-alert-game",
        "Standard Alert Game",
        "standard alert game",
        {Platform::Windows}};
    const StoreProduct baseGame{
        "standard-base",
        game.id,
        Store::Steam,
        {Platform::Windows},
        Money{900, Currency::KRW},
        true,
        "2026-01-01T00:00:00.000Z",
        std::nullopt,
        0,
        Region::KR,
        GameEdition::Standard,
        OfferType::BaseGame};
    products.saveNormalizedProducts(game, {baseGame});
    accounts.addRule(
        user.id,
        game.id,
        AlertRuleType::BelowTargetPrice,
        1000,
        Platform::Windows);

    expect(alerts.evaluateGame(game.id) == 1,
           "A matching Standard BaseGame should trigger the default target alert");
    const auto notifications = accounts.findNotifications(user.id);
    expect(notifications.size() == 1 &&
               notifications.front().productId == "standard-base" &&
               notifications.front().priceMinor == 900,
           "The notification must identify only the comparable Standard BaseGame");
}

void testSocialIdentityLoginAndLinking() {
    Database database(":memory:"); StoreProductRepository products(database); products.initializeSchema();
    AccountRepository accounts(database); AuthService auth(accounts); OAuthService oauth(accounts);
    const OAuthProfile google{OAuthProvider::Google,"google-user-1",std::string{"same@example.com"}};
    const auto socialLogin=oauth.completeLogin(google);
    expect(socialLogin.user.email=="Google-google-user-1@social.local" &&
               auth.authenticate(socialLogin.token).has_value(),
           "A new social identity should create its own user and session");
    expect(oauth.completeLogin(google).user.id==socialLogin.user.id,
           "The same provider subject should reuse its linked user");

    const auto local=auth.registerUser("same@example.com","safe-password-123");
    expect(local.user.id!=socialLogin.user.id,
           "Matching provider email must not automatically merge accounts");
    const OAuthProfile kakao{OAuthProvider::Kakao,"kakao-user-1",std::string{"same@example.com"}};
    oauth.linkIdentity(local.user.id,kakao);
    expect(accounts.findExternalIdentities(local.user.id).size()==1,
           "An authenticated user should explicitly link a social identity");
    bool rejectedCrossAccount=false;
    try{oauth.linkIdentity(socialLogin.user.id,kakao);}catch(const std::invalid_argument&){rejectedCrossAccount=true;}
    expect(rejectedCrossAccount,"A social identity must not link to two users");

    const auto loginState=accounts.createOAuthState(OAuthProvider::Naver,std::nullopt);
    const auto consumedLogin=accounts.consumeOAuthState(OAuthProvider::Naver,loginState);
    expect(consumedLogin.has_value() && *consumedLogin==0 &&
               !accounts.consumeOAuthState(OAuthProvider::Naver,loginState).has_value(),
           "OAuth login state should be provider-bound and single-use");
    const auto linkState=accounts.createOAuthState(OAuthProvider::Google,local.user.id);
    expect(accounts.consumeOAuthState(OAuthProvider::Google,linkState)==
               std::optional<std::int64_t>{local.user.id},
           "OAuth link state should preserve the authenticated user");
}

void testPlatformScopedTargetAlert() {
    Database database(":memory:");StoreProductRepository products(database);products.initializeSchema();
    AccountRepository accounts(database);AlertService alerts(accounts);AuthService auth(accounts);
    const auto user=auth.registerUser("platform@example.com","safe-password-123").user;
    const Game game{"multi-platform","Multi Platform","multi platform",{Platform::Windows,Platform::Android}};
    auto windows=StoreProduct{"windows",game.id,Store::Steam,{Platform::Windows},Money{25000,Currency::KRW},true,"2026-01-01T00:00:00.000Z"};
    auto android=StoreProduct{"android",game.id,Store::GooglePlay,{Platform::Android},Money{15000,Currency::KRW},true,"2026-01-01T00:00:00.000Z"};
    products.saveNormalizedProducts(game,{windows,android});
    accounts.addRule(user.id,game.id,AlertRuleType::BelowTargetPrice,20000,Platform::Windows);
    windows.currentPrice.minorAmount=19000;windows.observedAt="2026-02-01T00:00:00.000Z";
    android.currentPrice.minorAmount=10000;android.observedAt="2026-02-01T00:00:00.000Z";
    products.saveNormalizedProducts(game,{windows,android});
    expect(alerts.evaluateGame(game.id)==1,"A platform-scoped rule should create one matching alert");
    const auto notifications=accounts.findNotifications(user.id);
    expect(notifications.size()==1&&notifications.front().store=="Steam",
           "Android price must not trigger a Windows target alert");
    expect(accounts.findRules(user.id).front().platform==std::optional<Platform>{Platform::Windows},
           "Repository should preserve the rule platform");
}

void testExplicitCollectionTimestamp() {
    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    const Game game{"stardew-valley", "Stardew Valley", "stardew valley", {}};

    auto product = makeSteamProduct(16000);
    product.observedAt = "2026-08-26T09:30:45.123Z";
    repository.saveNormalizedProducts(game, {product});
    const auto history = repository.findPriceHistory(Store::Steam, "413150");
    expect(history.size() == 1, "Explicit timestamp import should save one observation");
    expect(history.front().observedAt == *product.observedAt,
           "Price history should preserve the Store collection timestamp");

    product.currentPrice.minorAmount = 15000;
    product.observedAt = "invalid";
    bool rejected = false;
    try {
        repository.saveNormalizedProducts(game, {product});
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    expect(rejected, "Repository should reject an invalid collection timestamp");
    expect(repository.findPriceHistory(Store::Steam, "413150").size() == 1,
           "Invalid timestamp import should roll back the transaction");
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
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/game_catalog.json");
    std::size_t permanentRetrySleeps = 0;
    CollectionService service(
        catalog, repository, std::move(providers), 3, nullptr,
        std::chrono::milliseconds{100},
        [&permanentRetrySleeps](std::chrono::milliseconds) {
            ++permanentRetrySleeps;
        });

    const Game game{"stardew-valley", "Stardew Valley", "stardew valley", {}};
    const auto result = service.collect(game);
    expect(result.runs.size() == 2, "Both Store collection runs should be reported");
    expect(permanentRetrySleeps == 0,
           "Permanent Provider errors must not be retried");
    expect(result.totalProducts == 1, "Successful Store product should still be saved");
    expect(result.runs[0].status == CrawlRunStatus::Succeeded,
           "First collection run should succeed");
    expect(result.runs[1].status == CrawlRunStatus::Failed,
           "Second collection run should fail without stopping the first");
    expect(result.runs[1].productsFailed == 1 &&
               result.runs[1].productsRejected == 0,
           "A Provider failure should be separated from validation rejection");

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
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/game_catalog.json");
    std::vector<std::chrono::milliseconds> delays;
    CollectionService service(
        catalog, repository, std::move(providers), 3, nullptr,
        std::chrono::milliseconds{100},
        [&delays](std::chrono::milliseconds delay) { delays.push_back(delay); });

    const Game game{"stardew-valley", "Stardew Valley", "stardew valley", {}};
    const auto result = service.collect(game);
    expect(result.runs.size() == 3, "Temporary failures should use bounded retries");
    expect(result.runs[0].status == CrawlRunStatus::Failed,
           "First collection attempt should fail");
    expect(result.runs[0].attemptNumber == 1, "First attempt number should be 1");
    expect(result.runs[1].status == CrawlRunStatus::Failed,
           "Second collection attempt should still report its failure");
    expect(result.runs[2].status == CrawlRunStatus::Succeeded,
           "Third collection attempt should succeed");
    expect(result.runs[2].attemptNumber == 3, "Third attempt number should be 3");
    expect(result.runs[2].retryCount == 2,
           "A successful third attempt should report two retries");
    expect(delays == std::vector<std::chrono::milliseconds>{
                         std::chrono::milliseconds{100},
                         std::chrono::milliseconds{200}},
           "Transient retries should use exponential backoff");
    expect(result.totalProducts == 1, "Successful retry should save one product");

    const auto persistedRuns = repository.findCrawlRuns();
    expect(persistedRuns.size() == 3, "Every retry attempt should be persisted");
    expect(persistedRuns[0].status == CrawlRunStatus::Failed,
           "Failed retry attempt should remain in crawl history");
    expect(persistedRuns[2].status == CrawlRunStatus::Succeeded,
           "Successful retry attempt should be persisted");
}

void testCatalogProductIdentityProtection() {
    GameCatalog catalog(std::string(TEST_SAMPLE_DATA_DIR) + "/game_catalog.json");
    const auto game = catalog.findById("stardew-valley");
    expect(game.has_value(), "Catalog should contain Stardew Valley");

    const auto collectWith = [&](std::vector<StoreProduct> products) {
        Database database(":memory:");
        StoreProductRepository repository(database);
        repository.initializeSchema();
        ProductListTestProvider provider(std::move(products));
        std::vector<std::reference_wrapper<const StoreProductProvider>> providers{provider};
        return CollectionService(catalog, repository, providers, 3).collect(*game);
    };

    auto unknown = makeSteamProduct(11200);
    unknown.productId = "999999999";
    const auto unknownResult = collectWith({unknown});
    expect(unknownResult.totalProducts == 0 &&
               unknownResult.runs.size() == 1 &&
               unknownResult.runs.back().status == CrawlRunStatus::Failed &&
               unknownResult.runs.back().productsRejected == 1,
           "A product without a Catalog mapping must not be saved");

    auto wrongIdentity = makeSteamProduct(11200);
    wrongIdentity.offerType = OfferType::DLC;
    const auto wrongIdentityResult = collectWith({wrongIdentity});
    expect(wrongIdentityResult.totalProducts == 0 &&
               wrongIdentityResult.runs.back().status == CrawlRunStatus::Failed,
           "Provider comparison identity must match the Catalog mapping");

    Database partialDatabase(":memory:");
    StoreProductRepository partialRepository(partialDatabase);
    partialRepository.initializeSchema();
    ProductListTestProvider duplicateProvider(
        {makeSteamProduct(11200), makeSteamProduct(11200)});
    std::vector<std::reference_wrapper<const StoreProductProvider>> duplicateProviders{
        duplicateProvider};
    const auto duplicateResult = CollectionService(
        catalog, partialRepository, duplicateProviders).collect(*game);
    expect(duplicateResult.totalProducts == 1 &&
               duplicateResult.runs.back().status == CrawlRunStatus::Succeeded &&
               duplicateResult.runs.back().productsRejected == 1,
           "A duplicate record must not block a valid normalized product");
    const auto partialRuns = partialRepository.findCrawlRuns();
    const auto rejections = partialRepository.findCollectionRejections(
        partialRuns.back().id);
    expect(rejections.size() == 1 &&
               rejections.front().productId == "413150" &&
               rejections.front().reason.find("duplicate") != std::string::npos,
           "Rejected records must be quarantined with their reason");

    Database database(":memory:");
    StoreProductRepository repository(database);
    repository.initializeSchema();
    repository.saveNormalizedProducts(*game, {makeSteamProduct(11200)});
    const Game otherGame{"other-game", "Other Game", "other game", {}};
    auto reassigned = makeSteamProduct(12000);
    reassigned.gameId = otherGame.id;
    bool rejectedReassignment = false;
    try {
        repository.saveNormalizedProducts(otherGame, {reassigned});
    } catch (const std::invalid_argument&) {
        rejectedReassignment = true;
    }
    expect(rejectedReassignment,
           "An existing Store product must not be reassigned to another Game");
    expect(repository.findProductsByGameId(game->id).size() == 1 &&
               repository.findProductsByGameId(otherGame.id).empty(),
           "Rejected reassignment must preserve the original product identity");
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
        {"Epic end-to-end comparison", testEpicEndToEndComparison},
        {"Provider parsing partial failure", testProviderParsingPartialFailure},
        {"History deduplication and analysis", testHistoryDeduplicationAndAnalysis},
        {"Price observation integrity", testPriceObservationIntegrity},
        {"Database schema version", testDatabaseSchemaVersion},
        {"Discount change history", testDiscountChangeHistory},
        {"Store product price validation", testStoreProductPriceValidation},
        {"Repository-backed comparison", testPriceComparisonReadsRepository},
        {"Stale price safety", testStalePriceSafety},
        {"Game catalog search", testGameCatalogSearch},
        {"Game catalog validation", testGameCatalogValidation},
        {"Game query service report", testGameQueryServiceReport},
        {"ISO date validation", testIsoDateValidation},
        {"Authentication and price alerts", testAuthenticationAndPriceAlerts},
        {"Standard BaseGame price alert",
         testStandardBaseGameTriggersDefaultPriceAlert},
        {"DLC excluded from default price alerts",
         testDlcDoesNotTriggerDefaultPriceAlert},
        {"Deluxe excluded from default price alerts",
         testDeluxeDoesNotTriggerDefaultPriceAlert},
        {"Bundle excluded from default price alerts",
         testBundleDoesNotTriggerDefaultPriceAlert},
        {"Subscription excluded from default price alerts",
         testSubscriptionDoesNotTriggerDefaultPriceAlert},
        {"Social identity login and linking", testSocialIdentityLoginAndLinking},
        {"Platform-scoped target alert", testPlatformScopedTargetAlert},
        {"Explicit collection timestamp", testExplicitCollectionTimestamp},
        {"Recommendation rules", testRecommendationRules},
        {"Collection run tracking and failure isolation",
         testCollectionRunTrackingAndFailureIsolation},
        {"Collection retry after temporary failure",
         testCollectionRetryAfterTemporaryFailure},
        {"Catalog product identity protection",
         testCatalogProductIdentityProtection},
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
