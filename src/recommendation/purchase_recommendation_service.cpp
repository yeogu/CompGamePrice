#include "game_price/recommendation/purchase_recommendation_service.h"

#include <optional>
#include <utility>

namespace game_price {
namespace {

int percentDifference(std::int64_t value, std::int64_t baseline) {
    if (baseline == 0) return 0;
    return static_cast<int>(((value - baseline) * 100) / baseline);
}

PurchaseRecommendationResult makeResult(
    PurchaseRecommendation recommendation,
    std::vector<std::string> reasons,
    const PriceHistorySummary& summary) {
    const auto current = summary.currentPrice.minorAmount;
    const auto lowest = summary.lowestPrice.minorAmount;
    const auto highest = summary.highestPrice.minorAmount;
    const auto average = summary.averagePrice.minorAmount;
    std::optional<int> rangePosition;
    if (highest > lowest) {
        rangePosition = static_cast<int>(
            ((current - lowest) * 100) / (highest - lowest));
    }
    return PurchaseRecommendationResult{
        recommendation,
        std::move(reasons),
        current - lowest,
        percentDifference(current, lowest),
        percentDifference(current, average),
        rangePosition};
}

}  // namespace

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
        return makeResult(
            PurchaseRecommendation::InsufficientData,
            {"At least two different observed prices are required."},
            summary);
    }

    if (current == lowest) {
        const auto recommendation = summary.observationCount >= 3
            ? PurchaseRecommendation::StrongBuy
            : PurchaseRecommendation::Buy;
        std::vector<std::string> reasons{"Current price is the historical low."};
        if (summary.trend == PriceTrend::Falling) {
            reasons.push_back("Price fell since the previous observation.");
        }
        return makeResult(recommendation, std::move(reasons), summary);
    }

    const auto fivePercentAboveLowest = lowest + lowest / 20;
    if (current <= fivePercentAboveLowest) {
        return makeResult(
            PurchaseRecommendation::Buy,
            {"Current price is within 5% of the historical low."},
            summary);
    }

    if (current < average && summary.trend != PriceTrend::Rising) {
        return makeResult(
            PurchaseRecommendation::Buy,
            {"Current price is below the observed average."},
            summary);
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
    return makeResult(PurchaseRecommendation::Wait, std::move(reasons), summary);
}

}  // namespace game_price
