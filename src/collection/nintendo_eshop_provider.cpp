#include "game_price/collection/nintendo_eshop_provider.h"

#include "game_price/support/text_utils.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <stdexcept>

namespace game_price {
namespace {

CompatibilityStatus parseCompatibility(const std::string& value) {
    if (value == "SUPPORTED") return CompatibilityStatus::Compatible;
    if (value == "LIMITED") return CompatibilityStatus::Limited;
    if (value == "UNSUPPORTED") return CompatibilityStatus::Unsupported;
    if (value == "UNKNOWN") return CompatibilityStatus::Unknown;
    throw std::runtime_error("invalid Switch 2 compatibility");
}

}  // namespace

NintendoEShopProvider::NintendoEShopProvider(const std::string& dataPath) {
    std::ifstream input(dataPath);
    if (!input) throw std::runtime_error("Cannot open Nintendo eShop data: " + dataPath);

    std::string line;
    std::getline(input, line);  // Store-specific CSV header.
    while (std::getline(input, line)) {
        line = trim(line);
        if (line.empty() || line.front() == '#') continue;
        const auto fields = split(line, ',');
        if (fields.size() != 9) {
            throw std::runtime_error("Invalid Nintendo eShop row");
        }
        try {
            const auto regularPrice = std::stoll(trim(fields[2]));
            const auto currentPrice = std::stoll(trim(fields[3]));
            const auto discount = std::stoi(trim(fields[4]));
            const auto productId = trim(fields[0]);
            if (productId.empty() || !std::all_of(productId.begin(), productId.end(),
                    [](unsigned char value) { return std::isdigit(value) != 0; }) ||
                regularPrice < currentPrice || currentPrice < 0 ||
                discount < 0 || discount > 100 || trim(fields[5]) != "SWITCH") {
                throw std::runtime_error("invalid value");
            }
            (void)parseCompatibility(trim(fields[8]));
            products_.push_back(RawProduct{
                productId, trim(fields[1]), regularPrice, currentPrice, discount,
                trim(fields[5]), trim(fields[8]), trim(fields[7]) == "AVAILABLE"});
        } catch (const std::exception&) {
            throw std::runtime_error("Invalid Nintendo eShop product row");
        }
    }
}

Store NintendoEShopProvider::store() const noexcept {
    return Store::NintendoEShop;
}

std::vector<StoreProduct> NintendoEShopProvider::findProducts(
    const std::string& gameId) const {
    std::vector<StoreProduct> result;
    for (const auto& raw : products_) {
        if (raw.gameId != gameId) continue;
        result.push_back(StoreProduct{
            raw.productId, raw.gameId, Store::NintendoEShop,
            {Platform::NintendoSwitch},
            Money{raw.currentPriceWon, Currency::KRW}, raw.purchasable,
            std::nullopt, Money{raw.regularPriceWon, Currency::KRW},
            raw.discountPercent, Region::KR, GameEdition::Standard,
            OfferType::BaseGame,
            {{Platform::NintendoSwitch2, parseCompatibility(raw.compatibility)}}});
    }
    return result;
}

}  // namespace game_price
