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
    static constexpr int CurrentSchemaVersion = 3;

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
        const std::string& errorMessage) const;
    std::vector<CrawlRunRecord> findCrawlRuns() const;

private:
    Database& database_;
};

}  // namespace game_price
