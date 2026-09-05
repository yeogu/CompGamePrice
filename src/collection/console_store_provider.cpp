#include "game_price/collection/console_store_provider.h"

#include "game_price/support/text_utils.h"

#include <fstream>
#include <stdexcept>

namespace game_price {
namespace {

Platform parsePlatform(const std::string& value) {
    if (value == "PS4") {
        return Platform::PlayStation4;
    }
    if (value == "PS5") {
        return Platform::PlayStation5;
    }
    if (value == "XBOX_ONE") {
        return Platform::XboxOne;
    }
    if (value == "XBOX_SERIES") {
        return Platform::XboxSeries;
    }
    throw std::runtime_error("unsupported console platform");
}

bool platformBelongsToStore(Store store, Platform platform) {
    if (store == Store::PlayStationStore) {
        return platform == Platform::PlayStation4 ||
            platform == Platform::PlayStation5;
    }
    if (store == Store::MicrosoftStore) {
        return platform == Platform::XboxOne ||
            platform == Platform::XboxSeries;
    }
    return false;
}

std::vector<Platform> parsePlatforms(Store store, const std::string& value) {
    std::vector<Platform> result;
    for (const auto& token : split(value, '|')) {
        const auto platform = parsePlatform(trim(token));
        if (!platformBelongsToStore(store, platform)) {
            throw std::runtime_error("platform does not belong to Store");
        }
        result.push_back(platform);
    }
    if (result.empty()) {
        throw std::runtime_error("console platforms are required");
    }
    return result;
}

}  // namespace

ConsoleStoreProvider::ConsoleStoreProvider(
    Store store,
    const std::string& dataPath)
    : store_(store) {
    if (store != Store::PlayStationStore && store != Store::MicrosoftStore) {
        throw std::invalid_argument("ConsoleStoreProvider requires a console Store");
    }
    std::ifstream input(dataPath);
    if (!input) {
        throw std::runtime_error("Cannot open console Store data: " + dataPath);
    }

    std::string line;
    std::getline(input, line);
    while (std::getline(input, line)) {
        line = trim(line);
        if (line.empty() || line.front() == '#') {
            continue;
        }
        const auto fields = split(line, ',');
        const auto productId = fields.empty() ? std::string{} : trim(fields[0]);
        const auto gameId = fields.size() > 1 ? trim(fields[1]) : std::string{};
        try {
            if (fields.size() != 8) {
                throw std::runtime_error("unexpected field count");
            }
            const auto regularPrice = std::stoll(trim(fields[2]));
            const auto currentPrice = std::stoll(trim(fields[3]));
            const auto discount = std::stoi(trim(fields[4]));
            const auto platforms = parsePlatforms(store, trim(fields[5]));
            if (productId.empty() || gameId.empty() ||
                regularPrice < currentPrice || currentPrice < 0 ||
                discount < 0 || discount > 100 || trim(fields[6]) != "KR") {
                throw std::runtime_error("invalid value");
            }
            products_.push_back(RawProduct{
                productId,
                gameId,
                regularPrice,
                currentPrice,
                discount,
                platforms,
                trim(fields[7]) == "AVAILABLE",
            });
        } catch (const std::exception& error) {
            rejections_.push_back(ProviderRejection{
                gameId,
                productId,
                "Invalid console Store product row: " +
                    std::string(error.what()),
            });
        }
    }
}

Store ConsoleStoreProvider::store() const noexcept {
    return store_;
}

std::vector<ProviderRejection> ConsoleStoreProvider::findRejections(
    const std::string& gameId) const {
    std::vector<ProviderRejection> result;
    for (const auto& rejection : rejections_) {
        if (rejection.gameId == gameId) {
            result.push_back(rejection);
        }
    }
    return result;
}

std::vector<StoreProduct> ConsoleStoreProvider::findProducts(
    const std::string& gameId) const {
    std::vector<StoreProduct> result;
    for (const auto& raw : products_) {
        if (raw.gameId != gameId) {
            continue;
        }
        result.push_back(StoreProduct{
            raw.productId,
            raw.gameId,
            store_,
            raw.platforms,
            Money{raw.currentPriceWon, Currency::KRW},
            raw.purchasable,
            std::nullopt,
            Money{raw.regularPriceWon, Currency::KRW},
            raw.discountPercent,
            Region::KR,
            GameEdition::Standard,
            OfferType::BaseGame,
        });
    }
    return result;
}

}  // namespace game_price
