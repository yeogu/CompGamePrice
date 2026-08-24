#include "game_price/purchase_recommendation_service.h"

#include <utility>

namespace game_price {

std::string toString(PurchaseRecommendation recommendation) {
    switch (recommendation) {
        case PurchaseRecommendation::StrongBuy: return "Strong buy";
        case PurchaseRecommendation::Buy: return "Buy";
        case PurchaseRecommendation::Wait: return "Wait";
        case PurchaseRecommendation::InsufficientData: return "Insufficient data";
    }
    return "Unknown recommendation";
}

PurchaseRecommendationResult PurchaseRecommendationService::recommend(
    const PriceHistorySummary& summary) const {
    const auto current = summary.currentPrice.minorAmount;
    const auto lowest = summary.lowestPrice.minorAmount;
    const auto highest = summary.highestPrice.minorAmount;
    const auto average = summary.averagePrice.minorAmount;

    if (summary.observationCount < 2 || highest == lowest) {
        return PurchaseRecommendationResult{
            PurchaseRecommendation::InsufficientData,
            {"At least two different observed prices are required."}};
    }

    if (current == lowest) {
        const auto recommendation = summary.observationCount >= 3
            ? PurchaseRecommendation::StrongBuy
            : PurchaseRecommendation::Buy;
        std::vector<std::string> reasons{"Current price is the historical low."};
        if (summary.trend == PriceTrend::Falling) {
            reasons.push_back("Price fell since the previous observation.");
        }
        return PurchaseRecommendationResult{recommendation, std::move(reasons)};
    }

    const auto fivePercentAboveLowest = lowest + lowest / 20;
    if (current <= fivePercentAboveLowest) {
        return PurchaseRecommendationResult{
            PurchaseRecommendation::Buy,
            {"Current price is within 5% of the historical low."}};
    }

    if (current < average && summary.trend != PriceTrend::Rising) {
        return PurchaseRecommendationResult{
            PurchaseRecommendation::Buy,
            {"Current price is below the observed average."}};
    }

    std::vector<std::string> reasons;
    if (summary.trend == PriceTrend::Rising) {
        reasons.push_back("Price rose since the previous observation.");
    }
    if (current >= average) {
        reasons.push_back("Current price is at or above the observed average.");
    }
    if (reasons.empty()) {
        reasons.push_back("Current price is not close enough to the historical low.");
    }
    return PurchaseRecommendationResult{PurchaseRecommendation::Wait, std::move(reasons)};
}

}  // namespace game_price
