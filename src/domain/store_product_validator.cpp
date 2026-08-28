#include "game_price/domain/store_product_validator.h"

#include "game_price/support/date_utils.h"

#include <algorithm>
#include <cstdlib>
#include <stdexcept>

namespace game_price {
namespace {

void validateMoney(const Money& money, const char* field) {
    if (money.currency != Currency::KRW) {
        throw std::invalid_argument(std::string(field) + " must use KRW");
    }
    if (money.minorAmount < 0 ||
        money.minorAmount > MaximumSupportedPriceMinor) {
        throw std::invalid_argument(
            std::string(field) + " must be between 0 and " +
            std::to_string(MaximumSupportedPriceMinor) + " KRW");
    }
}

}  // namespace

void validateStoreProduct(const StoreProduct& product) {
    if (product.productId.empty()) {
        throw std::invalid_argument("StoreProduct productId cannot be empty");
    }
    if (product.gameId.empty()) {
        throw std::invalid_argument("StoreProduct gameId cannot be empty");
    }
    if (product.region != Region::KR) {
        throw std::invalid_argument("StoreProduct region must be KR");
    }
    if (product.supportedPlatforms.empty()) {
        throw std::invalid_argument(
            "StoreProduct must support at least one platform");
    }
    for (auto current = product.supportedPlatforms.begin();
         current != product.supportedPlatforms.end(); ++current) {
        if (std::find(product.supportedPlatforms.begin(), current, *current) != current) {
            throw std::invalid_argument(
                "StoreProduct cannot contain duplicate platforms");
        }
    }
    for (auto current = product.compatibility.begin();
         current != product.compatibility.end(); ++current) {
        if (std::any_of(
                product.compatibility.begin(), current,
                [current](const PlatformCompatibility& previous) {
                    return previous.platform == current->platform;
                })) {
            throw std::invalid_argument(
                "StoreProduct cannot contain duplicate compatibility platforms");
        }
    }

    validateMoney(product.currentPrice, "Current price");
    if (product.regularPrice) {
        validateMoney(*product.regularPrice, "Regular price");
        if (product.regularPrice->currency != product.currentPrice.currency) {
            throw std::invalid_argument(
                "Regular and current prices must use the same currency");
        }
        if (product.currentPrice.minorAmount > product.regularPrice->minorAmount) {
            throw std::invalid_argument(
                "Current price cannot be higher than regular price");
        }
    }

    if (product.discountPercent < 0 || product.discountPercent > 100) {
        throw std::invalid_argument(
            "Discount percent must be between 0 and 100");
    }
    if (product.discountPercent > 0 && !product.regularPrice) {
        throw std::invalid_argument(
            "A discounted product requires a regular price");
    }
    if (product.regularPrice) {
        const auto regular = product.regularPrice->minorAmount;
        const auto current = product.currentPrice.minorAmount;
        const int calculatedDiscount = regular == 0
            ? 0
            : static_cast<int>(((regular - current) * 100 + regular / 2) / regular);
        if (std::abs(calculatedDiscount - product.discountPercent) > 1) {
            throw std::invalid_argument(
                "Discount percent does not match regular and current prices");
        }
    }
    if (product.observedAt && !isUtcTimestamp(*product.observedAt)) {
        throw std::invalid_argument(
            "Invalid StoreProduct observedAt timestamp: " + *product.observedAt);
    }
}

}  // namespace game_price
