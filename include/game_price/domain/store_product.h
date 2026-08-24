#pragma once

#include "game_price/domain/domain_types.h"
#include "game_price/domain/money.h"

#include <string>
#include <vector>

namespace game_price {

struct StoreProduct {
    std::string productId;
    std::string gameId;
    Store store;
    std::vector<Platform> supportedPlatforms;
    Money currentPrice;
    bool purchasable{false};
};

}  // namespace game_price
