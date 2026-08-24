#pragma once

#include "game_price/pricing/price_history.h"
#include "game_price/domain/store_product.h"
#include "game_price/persistence/store_product_repository.h"

#include <optional>

namespace game_price {

class PriceHistoryService {
public:
    explicit PriceHistoryService(const StoreProductRepository& repository);

    std::optional<PriceHistorySummary> analyze(
        const StoreProduct& product,
        const std::optional<std::string>& observedSince = std::nullopt) const;

private:
    const StoreProductRepository& repository_;
};

}  // namespace game_price
