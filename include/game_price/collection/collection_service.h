#pragma once

#include "game_price/collection/crawl_run.h"
#include "game_price/domain/game.h"
#include "game_price/collection/store_product_provider.h"
#include "game_price/persistence/store_product_repository.h"

#include <functional>
#include <vector>

namespace game_price {

class CollectionService {
public:
    CollectionService(
        StoreProductRepository& repository,
        std::vector<std::reference_wrapper<const StoreProductProvider>> providers);

    CollectionResult collect(const Game& game) const;

private:
    StoreProductRepository& repository_;
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers_;
};

}  // namespace game_price
