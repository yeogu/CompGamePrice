#pragma once

#include "game_price/domain_types.h"
#include "game_price/money.h"

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
