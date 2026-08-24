#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace game_price {

enum class PurchaseRecommendation {
    StrongBuy,
    Buy,
    Wait,
    InsufficientData
};

struct PurchaseRecommendationResult {
    PurchaseRecommendation recommendation{PurchaseRecommendation::InsufficientData};
    std::vector<std::string> reasons;
    std::int64_t amountAboveHistoricalLow{};
    int percentAboveHistoricalLow{};
    int percentComparedToAverage{};
    std::optional<int> priceRangePositionPercent;
};

std::string toString(PurchaseRecommendation recommendation);

}  // namespace game_price
