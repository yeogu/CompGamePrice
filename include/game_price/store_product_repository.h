#pragma once

#include "game_price/database.h"
#include "game_price/game.h"
#include "game_price/store_product.h"

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

private:
    Database& database_;
};

}  // namespace game_price
