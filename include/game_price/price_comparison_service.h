#pragma once

#include "game_price/game.h"
#include "game_price/game_catalog.h"
#include "game_price/store_product.h"
#include "game_price/store_product_repository.h"

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
    PriceComparisonService(const GameCatalog& catalog, const StoreProductRepository& repository);

    std::optional<PriceComparisonResult> compareByGameName(const std::string& gameName) const;

private:
    const GameCatalog& catalog_;
    const StoreProductRepository& repository_;
};

}  // namespace game_price
