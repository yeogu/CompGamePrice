#pragma once

#include "game_price/database.h"
#include "game_price/crawl_run.h"
#include "game_price/game.h"
#include "game_price/price_history.h"
#include "game_price/store_product.h"

#include <string>
#include <vector>

namespace game_price {

class StoreProductRepository {
public:
    explicit StoreProductRepository(Database& database);

    void initializeSchema() const;
    void saveNormalizedProducts(
        const Game& game,
        const std::vector<StoreProduct>& products) const;
    std::vector<StoreProduct> findProductsByGameId(const std::string& gameId) const;
    std::vector<PriceObservation> findPriceHistory(
        Store store,
        const std::string& productId) const;
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
