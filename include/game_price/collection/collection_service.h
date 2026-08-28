#pragma once

#include "game_price/collection/crawl_run.h"
#include "game_price/catalog/game_catalog.h"
#include "game_price/domain/game.h"
#include "game_price/collection/store_product_provider.h"
#include "game_price/persistence/store_product_repository.h"

#include <cstddef>
#include <functional>
#include <vector>

namespace game_price {
class AlertService;

class CollectionService {
public:
    CollectionService(
        const GameCatalog& catalog,
        StoreProductRepository& repository,
        std::vector<std::reference_wrapper<const StoreProductProvider>> providers,
        std::size_t maxAttemptsPerStore = 1,
        const AlertService* alertService = nullptr);

    CollectionResult collect(const Game& game) const;

private:
    const GameCatalog& catalog_;
    StoreProductRepository& repository_;
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers_;
    std::size_t maxAttemptsPerStore_;
    const AlertService* alertService_{};
};

}  // namespace game_price
