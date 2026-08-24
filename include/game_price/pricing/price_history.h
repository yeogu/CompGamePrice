#pragma once

#include "game_price/domain/domain_types.h"
#include "game_price/domain/money.h"

#include <cstddef>
#include <string>

namespace game_price {

struct PriceObservation {
    Money price;
    bool purchasable{false};
    std::string observedAt;
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
