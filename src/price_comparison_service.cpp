#include "game_price/price_comparison_service.h"

#include <algorithm>
#include <iterator>
#include <stdexcept>

namespace game_price {

PriceComparisonService::PriceComparisonService(
    const GameCatalog& catalog,
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers)
    : catalog_(catalog), providers_(std::move(providers)) {}

std::optional<PriceComparisonResult> PriceComparisonService::compareByGameName(
    const std::string& gameName) const {
    const auto game = catalog_.findByName(gameName);
    if (!game) {
        return std::nullopt;
    }

    PriceComparisonResult result{*game, {}, std::nullopt};
    for (const auto& provider : providers_) {
        auto products = provider.get().findProducts(game->id);
        std::move(products.begin(), products.end(), std::back_inserter(result.products));
    }

    for (const auto& product : result.products) {
        if (!product.purchasable) continue;
        if (product.currentPrice.currency != Currency::KRW) {
            throw std::runtime_error("Cannot compare products with different currencies");
        }
        if (!result.cheapestProduct ||
            product.currentPrice.minorAmount < result.cheapestProduct->currentPrice.minorAmount) {
            result.cheapestProduct = product;
        }
    }
    return result;
}

}  // namespace game_price
