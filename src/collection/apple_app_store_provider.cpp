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
        const auto productId = fields.empty() ? std::string{} : fields[0];
        const auto gameId = fields.size() > 1 ? fields[1] : std::string{};
        try {
            if (fields.size() != 5) {
                throw std::runtime_error("unexpected field count");
            }
            for (const auto& family : split(fields[3], '+')) {
                if (family != "IPHONE" && family != "IPAD") {
                    throw std::runtime_error("unsupported device family");
                }
            }
            products_.push_back(RawProduct{
                fields[0], fields[1], std::stoll(fields[2]), fields[3],
                parseBool(fields[4])});
        } catch (const std::exception& error) {
            rejections_.push_back(ProviderRejection{
                gameId, productId,
                "Invalid Apple App Store row: " + std::string(error.what())});
        }
    }
}

std::vector<ProviderRejection> AppleAppStoreProvider::findRejections(
    const std::string& gameId) const {
    std::vector<ProviderRejection> result;
    for (const auto& rejection : rejections_) {
        if (rejection.gameId == gameId) result.push_back(rejection);
    }
    return result;
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
