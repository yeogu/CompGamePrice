#include "game_price/collection/apple_app_store_provider.h"

#include "game_price/support/text_utils.h"

#include <fstream>
#include <stdexcept>

namespace game_price {

AppleAppStoreProvider::AppleAppStoreProvider(const std::string& dataPath) {
    std::ifstream input(dataPath);
    if (!input) {
        throw std::runtime_error("Cannot open Apple App Store data: " + dataPath);
    }

    std::string line;
    while (std::getline(input, line)) {
        if (trim(line).empty() || line.front() == '#') {
            continue;
        }
        const auto fields = split(line, ',');
        if (fields.size() != 5) {
            throw std::runtime_error("Invalid Apple App Store row: " + line);
        }
        products_.push_back(RawProduct{
            fields[0], fields[1], std::stoll(fields[2]), fields[3], parseBool(fields[4])});
    }
}

Store AppleAppStoreProvider::store() const noexcept {
    return Store::AppleAppStore;
}

std::vector<StoreProduct> AppleAppStoreProvider::findProducts(const std::string& gameId) const {
    std::vector<StoreProduct> result;
    for (const auto& raw : products_) {
        if (raw.gameId != gameId) {
            continue;
        }

        std::vector<Platform> platforms;
        for (const auto& family : split(raw.deviceFamilies, '+')) {
            if (family == "IPHONE") platforms.push_back(Platform::IOS);
            else if (family == "IPAD") platforms.push_back(Platform::IPadOS);
        }

        result.push_back(StoreProduct{
            raw.trackId, raw.gameId, Store::AppleAppStore, std::move(platforms),
            Money{raw.amountWon, Currency::KRW}, raw.availableForSale, std::nullopt,
            std::nullopt, 0, Region::KR, GameEdition::Standard,
            OfferType::BaseGame});
    }
    return result;
}

}  // namespace game_price
