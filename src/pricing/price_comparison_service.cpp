#include "game_price/pricing/price_comparison_service.h"

#include <algorithm>

namespace game_price {

PriceComparisonService::PriceComparisonService(
    const GameCatalog& catalog,
    const StoreProductRepository& repository)
    : catalog_(catalog), repository_(repository) {}

std::optional<PriceComparisonResult> PriceComparisonService::compareByGameName(
    const std::string& gameName,
    const PriceComparisonCriteria& criteria) const {
    const auto game = catalog_.findByName(gameName);
    if (!game) {
        return std::nullopt;
    }
    return compare(*game, criteria);
}

std::optional<PriceComparisonResult> PriceComparisonService::compareByGameId(
    const std::string& gameId,
    const PriceComparisonCriteria& criteria) const {
    const auto game = catalog_.findById(gameId);
    if (!game) return std::nullopt;
    return compare(*game, criteria);
}

PriceComparisonResult PriceComparisonService::compare(
    const Game& game,
    const PriceComparisonCriteria& criteria) const {
    PriceComparisonResult result{game, {}, std::nullopt};

    for (const auto& product : repository_.findProductsByGameId(game.id)) {
        if (!product.purchasable) continue;
        if (product.region != criteria.region ||
            product.edition != criteria.edition ||
            product.offerType != criteria.offerType ||
            product.currentPrice.currency != criteria.currency) {
            continue;
        }
        if (criteria.platform) {
            const bool native = std::find(
                product.supportedPlatforms.begin(), product.supportedPlatforms.end(),
                *criteria.platform) != product.supportedPlatforms.end();
            const bool compatible = std::any_of(
                product.compatibility.begin(), product.compatibility.end(),
                [&criteria](const PlatformCompatibility& entry) {
                    return entry.platform == *criteria.platform &&
                        (entry.status == CompatibilityStatus::Native ||
                         entry.status == CompatibilityStatus::Compatible);
                });
            if (!native && !compatible) continue;
        }
        result.products.push_back(product);
        if (!result.cheapestProduct ||
            product.currentPrice.minorAmount < result.cheapestProduct->currentPrice.minorAmount) {
            result.cheapestProduct = product;
        }
    }
    return result;
}

}  // namespace game_price
