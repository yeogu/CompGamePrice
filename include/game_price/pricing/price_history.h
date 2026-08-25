#pragma once

#include "game_price/domain/domain_types.h"
#include "game_price/domain/money.h"

#include <cstddef>
#include <optional>
#include <string>
#include <utility>

namespace game_price {

struct PriceObservation {
    PriceObservation(
        Money price,
        bool purchasable,
        std::string observedAt,
        std::optional<Money> regularPrice = std::nullopt,
        int discountPercent = 0)
        : price(price),
          purchasable(purchasable),
          observedAt(std::move(observedAt)),
          regularPrice(regularPrice),
          discountPercent(discountPercent) {}

    Money price;
    bool purchasable{false};
    std::string observedAt;
    std::optional<Money> regularPrice;
    int discountPercent{};
};

enum class PriceTrend {
    Rising,
    Falling,
    Stable,
    InsufficientData
};

struct PriceHistorySummary {
    Store store;
    std::string productId;
    Money currentPrice;
    Money lowestPrice;
    Money highestPrice;
    Money averagePrice;
    std::size_t observationCount{};
    PriceTrend trend{PriceTrend::InsufficientData};
};

std::string toString(PriceTrend trend);

}  // namespace game_price
