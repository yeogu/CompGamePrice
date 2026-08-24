#include "game_price/pricing/price_history_service.h"

#include <algorithm>
#include <cstdint>
#include <stdexcept>

namespace game_price {

std::string toString(PriceTrend trend) {
    switch (trend) {
        case PriceTrend::Rising: return "Rising";
        case PriceTrend::Falling: return "Falling";
        case PriceTrend::Stable: return "Stable";
        case PriceTrend::InsufficientData: return "Insufficient data";
    }
    return "Unknown trend";
}

PriceHistoryService::PriceHistoryService(const StoreProductRepository& repository)
    : repository_(repository) {}

std::optional<PriceHistorySummary> PriceHistoryService::analyze(
    const StoreProduct& product) const {
    const auto observations = repository_.findPriceHistory(product.store, product.productId);
    if (observations.empty()) {
        return std::nullopt;
    }

    const Currency currency = observations.front().price.currency;
    std::int64_t lowest = observations.front().price.minorAmount;
    std::int64_t highest = lowest;
    std::int64_t sum = 0;

    for (const auto& observation : observations) {
        if (observation.price.currency != currency) {
            throw std::runtime_error("Cannot analyze price history with mixed currencies");
        }
        const auto amount = observation.price.minorAmount;
        lowest = std::min(lowest, amount);
        highest = std::max(highest, amount);
        sum += amount;
    }

    PriceTrend trend = PriceTrend::InsufficientData;
    if (observations.size() >= 2) {
        const auto previous = observations[observations.size() - 2].price.minorAmount;
        const auto current = observations.back().price.minorAmount;
        if (current > previous) trend = PriceTrend::Rising;
        else if (current < previous) trend = PriceTrend::Falling;
        else trend = PriceTrend::Stable;
    }

    const auto count = static_cast<std::int64_t>(observations.size());
    const std::int64_t roundedAverage = (sum + count / 2) / count;
    return PriceHistorySummary{
        product.store,
        product.productId,
        observations.back().price,
        Money{lowest, currency},
        Money{highest, currency},
        Money{roundedAverage, currency},
        observations.size(),
        trend};
}

}  // namespace game_price
