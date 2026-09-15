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
        if (std::find(criteria.excludedStores.begin(), criteria.excludedStores.end(),
                      product.store) != criteria.excludedStores.end()) continue;
        if (!product.purchasable) continue;
        if (product.region != criteria.region ||
            product.edition != criteria.edition ||
            (product.offerType != criteria.offerType &&
             !(criteria.includeBundles && criteria.offerType == OfferType::BaseGame &&
               product.offerType == OfferType::Bundle)) ||
            (!criteria.includeForeignCurrencies &&
             product.currentPrice.currency != criteria.currency)) {
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
        const bool preferredCurrency =
            product.currentPrice.currency == criteria.currency;
        const bool currentCheapestIsPreferred = result.cheapestProduct &&
            result.cheapestProduct->currentPrice.currency == criteria.currency;
        const bool comparableToCurrent = result.cheapestProduct &&
            result.cheapestProduct->currentPrice.currency ==
                product.currentPrice.currency;
        if (product.freshness == PriceFreshness::Fresh &&
            (!result.cheapestProduct ||
             (preferredCurrency && !currentCheapestIsPreferred) ||
             ((!currentCheapestIsPreferred || preferredCurrency) &&
              comparableToCurrent && product.currentPrice.minorAmount <
                  result.cheapestProduct->currentPrice.minorAmount))) {
            result.cheapestProduct = product;
        }
    }
    return result;
}

}  // namespace game_price
