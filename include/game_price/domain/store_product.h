#pragma once

#include "game_price/domain/domain_types.h"
#include "game_price/domain/money.h"

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace game_price {

struct StoreProduct {
    StoreProduct(
        std::string productId,
        std::string gameId,
        Store store,
        std::vector<Platform> supportedPlatforms,
        Money currentPrice,
        bool purchasable = false,
        std::optional<std::string> observedAt = std::nullopt,
        std::optional<Money> regularPrice = std::nullopt,
        int discountPercent = 0)
        : productId(std::move(productId)),
          gameId(std::move(gameId)),
          store(store),
          supportedPlatforms(std::move(supportedPlatforms)),
          currentPrice(currentPrice),
          purchasable(purchasable),
          observedAt(std::move(observedAt)),
          regularPrice(regularPrice),
          discountPercent(discountPercent) {}

    std::string productId;
    std::string gameId;
    Store store;
    std::vector<Platform> supportedPlatforms;
    Money currentPrice;
    bool purchasable{false};
    std::optional<std::string> observedAt;
    std::optional<Money> regularPrice;
    int discountPercent{};
};

}  // namespace game_price
