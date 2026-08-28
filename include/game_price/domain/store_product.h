#pragma once

#include "game_price/domain/domain_types.h"
#include "game_price/domain/money.h"

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace game_price {

inline constexpr int PriceStaleAfterHours = 48;

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
        int discountPercent = 0,
        Region region = Region::KR,
        GameEdition edition = GameEdition::Standard,
        OfferType offerType = OfferType::BaseGame,
        std::vector<PlatformCompatibility> compatibility = {},
        std::optional<std::string> lastCheckedAt = std::nullopt,
        std::optional<std::string> lastSuccessfulCheckAt = std::nullopt,
        PriceFreshness freshness = PriceFreshness::Unknown)
        : productId(std::move(productId)),
          gameId(std::move(gameId)),
          store(store),
          supportedPlatforms(std::move(supportedPlatforms)),
          currentPrice(currentPrice),
          purchasable(purchasable),
          observedAt(std::move(observedAt)),
          regularPrice(regularPrice),
          discountPercent(discountPercent),
          region(region),
          edition(edition),
          offerType(offerType),
          compatibility(std::move(compatibility)),
          lastCheckedAt(std::move(lastCheckedAt)),
          lastSuccessfulCheckAt(std::move(lastSuccessfulCheckAt)),
          freshness(freshness) {}

    std::string productId;
    std::string gameId;
    Store store;
    std::vector<Platform> supportedPlatforms;
    Money currentPrice;
    bool purchasable{false};
    std::optional<std::string> observedAt;
    std::optional<Money> regularPrice;
    int discountPercent{};
    Region region{Region::KR};
    GameEdition edition{GameEdition::Standard};
    OfferType offerType{OfferType::BaseGame};
    std::vector<PlatformCompatibility> compatibility;
    std::optional<std::string> lastCheckedAt;
    std::optional<std::string> lastSuccessfulCheckAt;
    PriceFreshness freshness{PriceFreshness::Unknown};
};

}  // namespace game_price
