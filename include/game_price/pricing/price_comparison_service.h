#pragma once

#include "game_price/domain/game.h"
#include "game_price/catalog/game_catalog.h"
#include "game_price/domain/store_product.h"
#include "game_price/persistence/store_product_repository.h"

#include <optional>
#include <string>
#include <vector>

namespace game_price {

struct PriceComparisonCriteria {
    Region region{Region::KR};
    GameEdition edition{GameEdition::Standard};
    OfferType offerType{OfferType::BaseGame};
    Currency currency{Currency::KRW};
    std::optional<Platform> platform;
};

struct PriceComparisonResult {
    Game game;
    std::vector<StoreProduct> products;
    std::optional<StoreProduct> cheapestProduct;
};

class PriceComparisonService {
public:
    PriceComparisonService(const GameCatalog& catalog, const StoreProductRepository& repository);

    std::optional<PriceComparisonResult> compareByGameName(
        const std::string& gameName,
        const PriceComparisonCriteria& criteria = {}) const;
    std::optional<PriceComparisonResult> compareByGameId(
        const std::string& gameId,
        const PriceComparisonCriteria& criteria = {}) const;

private:
    PriceComparisonResult compare(
        const Game& game,
        const PriceComparisonCriteria& criteria) const;
    const GameCatalog& catalog_;
    const StoreProductRepository& repository_;
};

}  // namespace game_price
