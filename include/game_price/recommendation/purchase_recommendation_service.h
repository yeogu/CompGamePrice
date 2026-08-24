#pragma once

#include "game_price/pricing/price_history.h"
#include "game_price/recommendation/purchase_recommendation.h"

namespace game_price {

class PurchaseRecommendationService {
public:
    PurchaseRecommendationResult recommend(const PriceHistorySummary& summary) const;
};

}  // namespace game_price
