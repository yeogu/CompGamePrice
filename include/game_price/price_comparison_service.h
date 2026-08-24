#pragma once

#include "game_price/game.h"
#include "game_price/game_catalog.h"
#include "game_price/store_product.h"
#include "game_price/store_product_provider.h"

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace game_price {

struct PriceComparisonResult {
    Game game;
    std::vector<StoreProduct> products;
    std::optional<StoreProduct> cheapestProduct;
};

class PriceComparisonService {
public:
    PriceComparisonService(
        const GameCatalog& catalog,
        std::vector<std::reference_wrapper<const StoreProductProvider>> providers);

    std::optional<PriceComparisonResult> compareByGameName(const std::string& gameName) const;

private:
    const GameCatalog& catalog_;
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers_;
};

}  // namespace game_price
