#include "game_price/pricing/price_comparison_service.h"

#include <stdexcept>

namespace game_price {

PriceComparisonService::PriceComparisonService(
    const GameCatalog& catalog,
    const StoreProductRepository& repository)
    : catalog_(catalog), repository_(repository) {}

std::optional<PriceComparisonResult> PriceComparisonService::compareByGameName(
    const std::string& gameName) const {
    const auto game = catalog_.findByName(gameName);
    if (!game) {
        return std::nullopt;
    }

    PriceComparisonResult result{
        *game, repository_.findProductsByGameId(game->id), std::nullopt};

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
