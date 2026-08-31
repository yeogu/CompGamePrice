#pragma once

#include "game_price/persistence/database.h"
#include "game_price/collection/crawl_run.h"
#include "game_price/domain/game.h"
#include "game_price/pricing/price_history.h"
#include "game_price/domain/store_product.h"

#include <string>
#include <vector>

namespace game_price {

class StoreProductRepository {
public:
    static constexpr int CurrentSchemaVersion = 14;
    static constexpr int StaleAfterHours = PriceStaleAfterHours;

    explicit StoreProductRepository(Database& database);

    void initializeSchema() const;
    void saveNormalizedProducts(
        const Game& game,
        const std::vector<StoreProduct>& products) const;
    std::vector<StoreProduct> findProductsByGameId(const std::string& gameId) const;
    std::vector<PriceObservation> findPriceHistory(
        Store store,
        const std::string& productId) const;
    std::vector<PriceObservation> findPriceHistorySince(
        Store store,
        const std::string& productId,
        const std::string& observedSince) const;
    void replacePriceHistory(
        Store store,
        const std::string& productId,
        const std::vector<PriceObservation>& observations) const;
    std::int64_t startCrawlRun(Store store) const;
    void finishCrawlRun(
        std::int64_t runId,
        CrawlRunStatus status,
        std::size_t productsFound,
        std::size_t productsRejected,
        std::size_t productsFailed,
        std::size_t retryCount,
        const std::string& errorMessage) const;
    void recordCollectionRejection(
        std::int64_t runId,
        Store store,
        const std::string& gameId,
        const std::string& productId,
        const std::string& reason) const;
    void recordProductCheckFailure(
        Store store,
        const std::string& productId) const;
    std::vector<CrawlRunRecord> findCrawlRuns() const;
    std::vector<CollectionRejection> findCollectionRejections(
        std::int64_t runId) const;
    Database& database() const noexcept;

private:
    Database& database_;
};

}  // namespace game_price
