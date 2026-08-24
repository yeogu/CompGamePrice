#pragma once

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
};

std::string toString(PurchaseRecommendation recommendation);

}  // namespace game_price
