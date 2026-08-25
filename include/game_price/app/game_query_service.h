#pragma once

#include "game_price/catalog/game_catalog.h"
#include "game_price/collection/crawl_run.h"
#include "game_price/persistence/store_product_repository.h"
#include "game_price/pricing/price_comparison_service.h"
#include "game_price/pricing/price_history.h"
#include "game_price/recommendation/purchase_recommendation.h"

#include <optional>
#include <string>
#include <vector>

namespace game_price {

struct ProductPriceReport {
    StoreProduct product;
    std::optional<PriceHistorySummary> history;
    std::optional<PurchaseRecommendationResult> recommendation;
};

struct GamePriceReport {
    PriceComparisonResult comparison;
    std::vector<ProductPriceReport> productReports;
};

class GameQueryService {
public:
    GameQueryService(
        const GameCatalog& catalog,
        const StoreProductRepository& repository);

    std::vector<Game> searchGames(const std::string& query) const;
    std::optional<GamePriceReport> getGamePriceReport(
        const std::string& gameName,
        const std::optional<std::string>& observedSince = std::nullopt) const;
    std::vector<CrawlRunRecord> getCollectionRuns() const;

private:
    const GameCatalog& catalog_;
    const StoreProductRepository& repository_;
};

}  // namespace game_price
