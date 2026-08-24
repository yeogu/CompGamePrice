#pragma once

#include "game_price/price_history.h"
#include "game_price/purchase_recommendation.h"

namespace game_price {

class PurchaseRecommendationService {
public:
    PurchaseRecommendationResult recommend(const PriceHistorySummary& summary) const;
};

}  // namespace game_price
