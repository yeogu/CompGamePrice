#pragma once

#include "game_price/domain/domain_types.h"
#include "game_price/domain/money.h"

#include <optional>
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
    std::optional<std::string> observedAt;
};

}  // namespace game_price
