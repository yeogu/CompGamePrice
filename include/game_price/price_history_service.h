#pragma once

#include "game_price/price_history.h"
#include "game_price/store_product.h"
#include "game_price/store_product_repository.h"

#include <optional>

namespace game_price {

class PriceHistoryService {
public:
    explicit PriceHistoryService(const StoreProductRepository& repository);

    std::optional<PriceHistorySummary> analyze(const StoreProduct& product) const;

private:
    const StoreProductRepository& repository_;
};

}  // namespace game_price
