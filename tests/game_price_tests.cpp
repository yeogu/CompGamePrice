#include "game_price/collection/apple_app_store_provider.h"
#include "game_price/collection/collection_service.h"
#include "game_price/persistence/database.h"
#include "game_price/catalog/game_catalog.h"
#include "game_price/collection/google_play_provider.h"
#include "game_price/pricing/price_comparison_service.h"
#include "game_price/pricing/price_history_service.h"
#include "game_price/recommendation/purchase_recommendation_service.h"
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
    expect(service.recommend(strongBuy).recommendation == PurchaseRecommendation::StrongBuy,
           "Historical low after a fall should be a strong buy");

    const PriceHistorySummary wait{
        Store::Steam, "413150", Money{17000, Currency::KRW},
        Money{10000, Currency::KRW}, Money{18000, Currency::KRW},
        Money{14000, Currency::KRW}, 4, PriceTrend::Rising};
    expect(service.recommend(wait).recommendation == PurchaseRecommendation::Wait,
           "A rising above-average price should recommend waiting");
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

}  // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"Provider normalization", testProviderNormalization},
        {"History deduplication and analysis", testHistoryDeduplicationAndAnalysis},
        {"Repository-backed comparison", testPriceComparisonReadsRepository},
        {"Recommendation rules", testRecommendationRules},
        {"Collection run tracking and failure isolation",
         testCollectionRunTrackingAndFailureIsolation},
        {"Collection retry after temporary failure",
         testCollectionRetryAfterTemporaryFailure}};

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
